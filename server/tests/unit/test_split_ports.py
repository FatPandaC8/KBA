"""Unit tests for the two pipeline-split ports (S1) with in-memory fakes.

- Transcriber.transcribe(audio, content_type, language_hint) -> TranscriptDTO
- KnowledgeIngestorPort.ingest(user_id, capture_id, text) -> IngestResultDTO
- Composition-root selection from settings (S3): ECHO_STT_PROVIDER and
  ECHO_KB_EXTRACTOR; unknown values fail closed, never per-request params.
"""

import uuid

import pytest

from server.app.adapters.outbound.speech import FasterWhisperSpeechAdapter
from server.app.application.ports import (
    IngestResultDTO,
    KnowledgeIngestorPort,
    TranscriptDTO,
)
from server.app.domain.errors import (
    DomainError,
    InvalidInputAudioError,
    TooLongAudioError,
)
from server.app.api.dependencies import get_container


# ------------------------------------------------------------- Transcriber
class FakeTranscriber:
    """Fake STT port implementation capturing the exact port signature."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio: bytes, content_type: str, language_hint=None):
        self.calls.append((audio, content_type, language_hint))
        return TranscriptDTO(
            text="I met Anna at the cafe yesterday.",
            language="en",
            confidence=0.97,
            provider="fake",
        )


def test_transcriber_port_signature_and_shape():
    fake = FakeTranscriber()
    out = fake.transcribe(b"audio-bytes", "audio/mp4", language_hint="en")
    assert isinstance(out, TranscriptDTO)
    assert out.text and out.provider == "fake"
    assert fake.calls[0][1] == "audio/mp4"
    assert fake.calls[0][2] == "en"


def test_faster_whisper_transcribe_rejects_too_long_audio(monkeypatch):
    """S4 input limit: over-duration audio raises the typed too_large error
    with the measured and allowed seconds."""
    import numpy as np

    adapter = FasterWhisperSpeechAdapter(max_seconds=120)
    monkeypatch.setattr(
        "server.app.adapters.outbound.speech.decode_audio_from_bytes",
        lambda audio, sr=16000: np.zeros(sr * 121, dtype=np.float32),
    )
    with pytest.raises(TooLongAudioError) as excinfo:
        adapter.transcribe(b"x" * 200, "audio/mp4")
    assert excinfo.value.error_class == "too_large"
    assert excinfo.value.seconds == 121 and excinfo.value.limit_seconds == 120


def test_faster_whisper_transcribe_rejects_tiny_audio():
    adapter = FasterWhisperSpeechAdapter(max_seconds=120)
    with pytest.raises(InvalidInputAudioError):
        adapter.transcribe(b"\x00" * 10, "audio/mp4")


# --------------------------------------------------------- KnowledgeIngestor
class FakeIngestor(KnowledgeIngestorPort):
    """Fake Text-KB port: records calls and counts idempotent replays."""

    def __init__(self):
        self.calls = []
        self.capture_ids = set()

    def ingest(self, user_id: str, capture_id: str, text: str) -> IngestResultDTO:
        self.calls.append((user_id, capture_id, text))
        if capture_id in self.capture_ids:
            return IngestResultDTO(
                capture_id=capture_id,
                knowledge_item_id="existing",
                entities_added=1,
                relationships_added=0,
                provider="replayed",
            )
        self.capture_ids.add(capture_id)
        return IngestResultDTO(
            capture_id=capture_id,
            knowledge_item_id=f"item-{capture_id}",
            entities_added=2,
            relationships_added=1,
            provider="fake-extractor",
        )


def test_ingestor_port_shape_and_idempotent_replay():
    fake = FakeIngestor()
    user_id = str(uuid.uuid4())
    capture_id = str(uuid.uuid4())
    assert isinstance(fake, KnowledgeIngestorPort)

    first = fake.ingest(user_id, capture_id, "Echo depends on FastAPI.")
    second = fake.ingest(user_id, capture_id, "Echo depends on FastAPI.")

    assert first.knowledge_item_id == "item-" + capture_id
    assert second.provider == "replayed"
    assert second.knowledge_item_id == "existing"
    # one capture id, called twice with the same (user, capture, text)
    assert len(fake.capture_ids) == 1
    assert len(fake.calls) == 2


# ------------------------------------------------------------ S3 selection
def test_unknown_stt_provider_fails_closed_at_composition(monkeypatch):
    from server.app.infrastructure.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "stt_provider", "elevenlabs")
    with pytest.raises(DomainError, match="Unknown ECHO_STT_PROVIDER"):
        _build_container_once()


def _build_container_once():
    """Composition root: a fresh Container validates provider selection in
    its own constructor."""
    from server.app.api.dependencies import Container
    from server.app.infrastructure.config import get_settings

    Container(get_settings())


def test_unknown_kb_extractor_fails_closed_at_composition(monkeypatch):
    from server.app.infrastructure.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "kb_extractor", "openai")
    with pytest.raises(DomainError, match="Unknown ECHO_KB_EXTRACTOR"):
        _build_container_once()


def test_groq_extractor_without_key_fails_closed(monkeypatch):
    """S3: ECHO_KB_EXTRACTOR=groq with no configured LLM fails closed (no
    silent fallback to the local extractor)."""
    from server.app.api.dependencies import get_container, reset_container
    from server.app.infrastructure.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "kb_extractor", "groq")
    monkeypatch.setattr(settings, "llm_provider", "rule_based")
    reset_container()
    with pytest.raises(DomainError, match="fails closed"):
        get_container()
