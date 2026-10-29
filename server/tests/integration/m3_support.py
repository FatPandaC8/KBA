"""Shared helpers for M3 integration tests."""

import uuid
from typing import List, Optional

from server.app.api.dependencies import get_container


def container():
    return get_container()


class FakeTranscriber:
    """Deterministic STT stub: tests control text, failures and call counts."""

    def __init__(
        self,
        text: str = "I met Alice about the Echo project. Echo depends on FastAPI.",
        errors: Optional[List[Exception]] = None,
    ):
        self.text = text
        self.errors = list(errors or [])
        self.calls = 0

    def transcribe(self, audio_file_path: str) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.text


def upload(client, user, *, audio: bytes = b"\x00" * 512, duration_ms: int = 2000):
    capture_id = str(uuid.uuid4())
    response = client.post(
        "/api/captures/upload",
        headers=user.headers,
        files={"file": ("capture.m4a", audio, "audio/mp4")},
        data={
            "capture_id": capture_id,
            "idempotency_key": capture_id,
            "duration_ms": str(duration_ms),
        },
    )
    assert response.status_code == 202, response.text
    return capture_id


def process(capture_id: str, worker_id: str = "test-worker"):
    container_ = container()
    capture = container_.capture_repo.get_by_id(capture_id)
    assert capture is not None, "capture must exist before processing"
    return container_.process_capture_uc.process(capture_id, capture.user_id, worker_id)


def ingest(client, user, transcript: str, monkeypatch=None) -> str:
    """Upload and run one capture to a terminal state with fake STT."""
    container_ = container()
    original = container_.process_capture_uc.transcriber
    if monkeypatch is not None:
        monkeypatch.setattr(
            container_.process_capture_uc, "transcriber", FakeTranscriber(transcript)
        )
    else:
        container_.process_capture_uc.transcriber = FakeTranscriber(transcript)
    try:
        capture_id = upload(client, user)
        job = process(capture_id)
    finally:
        if monkeypatch is None:
            container_.process_capture_uc.transcriber = original
    assert job is not None
    assert job.status == "ready", job
    return capture_id
