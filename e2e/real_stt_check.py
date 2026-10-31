"""One-shot real-STT verification for the E2E report.

The Playwright harness stubs FasterWhisperSpeechAdapter for determinism. This
script proves the REAL local STT adapter works on genuinely synthesised speech
so the E2E claim "everything downstream of the transcript is real" is bounded.

Run: python3 e2e/real_stt_check.py
"""

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("ECHO_ENV", "test")
os.environ.setdefault("ECHO_LLM_PROVIDER", "rule_based")
os.environ.setdefault("ECHO_ALLOW_REAL_LLM", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.app.adapters.outbound.speech import FasterWhisperSpeechAdapter  # noqa: E402

SENTENCE = "Echo depends on fast transport."

with tempfile.TemporaryDirectory() as tmp:
    wav = os.path.join(tmp, "speech.wav")
    subprocess.run(
        ["espeak-ng", "-v", "en-us", "-w", wav, SENTENCE],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    size = os.path.getsize(wav)
    print(f"[real-stt] synthesised speech wav: {size} bytes")

    adapter = FasterWhisperSpeechAdapter()
    transcript = adapter.transcribe(wav)
    print(f"[real-stt] transcript: {transcript!r}")

    lowered = transcript.lower()
    checks = [word in lowered for word in ("echo", "depends", "fast", "transport")]
    if not any(checks):
        print("[real-stt] FAIL: transcript does not echo any expected keyword")
        sys.exit(1)
    print("[real-stt] PASS: real faster-whisper produced recognisable speech text")
