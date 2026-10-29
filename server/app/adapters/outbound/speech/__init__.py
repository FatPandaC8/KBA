import os
import subprocess

import numpy as np

from server.app.application.ports import AudioTranscriptionPort
from server.app.domain.errors import AudioProcessingError

_GLOBAL_WHISPER_MODEL = None

def get_whisper_model():
    """Lazily load faster-whisper tiny model on CPU for local STT."""
    global _GLOBAL_WHISPER_MODEL
    if _GLOBAL_WHISPER_MODEL is None:
        try:
            from faster_whisper import WhisperModel
            _GLOBAL_WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
        except Exception as e:
            print(f"[STT] Warning: Failed to load faster-whisper model: {e}")
            _GLOBAL_WHISPER_MODEL = None
    return _GLOBAL_WHISPER_MODEL

def decode_audio_ffmpeg(file_path: str, sr: int = 16000) -> np.ndarray:
    """Decodes audio via ffmpeg into normalized 16kHz float32 audio."""
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0", "-i", file_path,
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(sr), "-"
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise AudioProcessingError(f"FFmpeg audio decode error ({proc.returncode}): {proc.stderr.decode('utf-8', errors='ignore')}")
    raw_bytes = proc.stdout
    if not raw_bytes:
        raise AudioProcessingError("Audio file decoded to 0 bytes")
    return np.frombuffer(raw_bytes, np.int16).flatten().astype(np.float32) / 32768.0

class FasterWhisperSpeechAdapter(AudioTranscriptionPort):
    """Local faster-whisper STT. No remote or paid provider is used."""

    def __init__(self):
        pass

    def transcribe(self, audio_file_path: str) -> str:
        if not os.path.exists(audio_file_path):
            raise AudioProcessingError(f"Audio file not found: {audio_file_path}")

        file_size = os.path.getsize(audio_file_path)
        if file_size < 100:
            raise AudioProcessingError(f"Audio file is too small or corrupted ({file_size} bytes)")

        whisper_model = get_whisper_model()
        if whisper_model is None:
            raise AudioProcessingError("Local faster-whisper STT engine is not available")

        audio_arr = decode_audio_ffmpeg(audio_file_path, sr=16000)
        duration_sec = len(audio_arr) / 16000.0

        segments, _ = whisper_model.transcribe(
            audio_arr,
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        transcript = " ".join([seg.text.strip() for seg in segments]).strip()

        if not transcript:
            raise AudioProcessingError(f"Recording ({duration_sec:.1f}s) contained no intelligible speech or silence.")

        return transcript
