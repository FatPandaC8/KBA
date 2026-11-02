import os
import subprocess
from typing import Optional

import numpy as np

from server.app.application.ports import (
    AudioTranscriptionPort,
    TranscriptDTO,
)
from server.app.domain.errors import (
    InvalidInputAudioError,
    TooLongAudioError,
    ProviderError,
)

_GLOBAL_WHISPER_MODEL = None
_GLOBAL_WHISPER_MODEL_NAME = None

# `tiny` is the default because it runs comfortably on a CPU-only server.
# `base.en` / `small.en` raise accuracy for English and are opt-in via env.
WHISPER_MODEL_NAME = os.getenv("ECHO_WHISPER_MODEL", "tiny")
WHISPER_COMPUTE_TYPE = os.getenv("ECHO_WHISPER_COMPUTE_TYPE", "int8")

def get_whisper_model():
    """Lazily load the configured faster-whisper model on CPU for local STT."""
    global _GLOBAL_WHISPER_MODEL, _GLOBAL_WHISPER_MODEL_NAME
    if _GLOBAL_WHISPER_MODEL is not None and _GLOBAL_WHISPER_MODEL_NAME == WHISPER_MODEL_NAME:
        return _GLOBAL_WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
        _GLOBAL_WHISPER_MODEL = WhisperModel(
            WHISPER_MODEL_NAME, device="cpu", compute_type=WHISPER_COMPUTE_TYPE
        )
        _GLOBAL_WHISPER_MODEL_NAME = WHISPER_MODEL_NAME
    except Exception as e:
        print(f"[STT] Warning: Failed to load faster-whisper model {WHISPER_MODEL_NAME!r}: {e}")
        _GLOBAL_WHISPER_MODEL = None
        _GLOBAL_WHISPER_MODEL_NAME = None
    return _GLOBAL_WHISPER_MODEL

def decode_audio_from_bytes(audio: bytes, sr: int = 16000):
    """ffmpeg decode straight from bytes (no server-side file)."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-ac", "1",
        "-ar", str(sr),
        "-f", "s16le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise InvalidInputAudioError(
            f"FFmpeg audio decode error ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='ignore')}"
        )
    raw_bytes = proc.stdout
    if not raw_bytes:
        raise InvalidInputAudioError("Audio file decoded to 0 bytes")
    return np.frombuffer(raw_bytes, np.int16).flatten().astype(np.float32) / 32768.0

class FasterWhisperSpeechAdapter(AudioTranscriptionPort):
    """Local faster-whisper STT. No remote or paid provider is used."""

    def __init__(self, language: str = "en", max_seconds: int = 120):
        self.language = language
        self.max_seconds = max_seconds

    def _transcribe_array(self, audio_arr, duration_hint=""):
        """Core whisper decode (bytes in)."""
        whisper_model = get_whisper_model()
        if whisper_model is None:
            raise ProviderError("Local faster-whisper STT engine is not available")

        segments, info = whisper_model.transcribe(
            audio_arr,
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        transcript = " ".join([seg.text.strip() for seg in segments]).strip()

        detected = getattr(info, "language", None)
        if detected and detected != self.language:
            raise InvalidInputAudioError(
                f"English audio only. Detected language: {detected}."
            )

        if not transcript:
            raise InvalidInputAudioError(
                f"Recording ({duration_hint}) contained no intelligible speech or silence."
            )

        return transcript, detected

    def transcribe(
        self,
        audio: bytes,
        content_type: str,
        language_hint: Optional[str] = None,
    ) -> "TranscriptDTO":
        """STT port (S1): bytes in, typed TranscriptDTO out, nothing stored.
        language_hint is advisory (ignored by the English-only local STT)."""
        del language_hint, content_type  # English-only local engine keeps none
        if len(audio) < 100:
            raise InvalidInputAudioError("Audio is too small or corrupted (<100 bytes)")
        try:
            audio_arr = decode_audio_from_bytes(audio, sr=16000)
        except InvalidInputAudioError:
            raise
        except Exception as exc:
            raise InvalidInputAudioError(f"Unsupported audio content: {exc}")
        duration_sec = len(audio_arr) / 16000.0
        # Input limit (S4): reject over-long recordings with a clear message
        # before any model work; the HTTP route maps this to 413.
        if duration_sec > self.max_seconds:
            raise TooLongAudioError(
                f"Audio is {duration_sec:.0f}s long; the maximum is "
                f"{self.max_seconds}s. Record a shorter note.",
                seconds=int(duration_sec),
                limit_seconds=self.max_seconds,
            )
        text, detected = self._transcribe_array(audio_arr, f"{duration_sec:.1f}s")
        return TranscriptDTO(text=text, language=detected, provider="faster-whisper")


def decode_audio_from_bytes(audio: bytes, sr: int = 16000):
    """ffmpeg decode straight from bytes (no server-side temp file)."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-ac", "1",
        "-ar", str(sr),
        "-f", "s16le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise InvalidInputAudioError(
            f"FFmpeg audio decode error ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='ignore')}"
        )
    raw_bytes = proc.stdout
    if not raw_bytes:
        raise InvalidInputAudioError("Audio decoded to 0 bytes")
    return np.frombuffer(raw_bytes, np.int16).flatten().astype(np.float32) / 32768.0
