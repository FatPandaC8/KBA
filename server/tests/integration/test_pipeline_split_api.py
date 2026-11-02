"""Contract tests for the pipeline-split endpoints (Step 2).

POST /api/stt    — stateless transcription (auth only, nothing persisted)
POST /api/text-kb — one-UoW ingest, idempotent on capture_id (auth+consent)

Proves the split: /api/text-kb MUST work with no STT provider configured at
all (the container's transcriber is deleted for the duration)."""

import json
import uuid

import pytest

from server.app.main import app

from fastapi.testclient import TestClient

client = TestClient(app)

PASSWORD = "EchoTest1234"


@pytest.fixture()
def user():
    import uuid as _uuid

    email = f"split-{_uuid.uuid4().hex[:8]}@example.com"
    signup = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert signup.status_code == 200, signup.text
    token = signup.json()["dev_verification_token"]
    assert client.post(
        "/api/auth/verify-email", json={"token": token}
    ).status_code == 200
    login = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    consent = client.post("/api/consent", json={"granted": True}, headers=headers)
    assert consent.status_code == 200, consent.text
    return headers


def _auth_only(user):
    """Reuse the user's headers for the auth-only /api/stt route."""
    return user


def _capture_id() -> str:
    return str(uuid.uuid4())


def test_stt_requires_auth(user):
    response = client.post(
        "/api/stt", content=b"\x00" * 200, headers={"Content-Type": "audio/mp4"}
    )
    assert response.status_code == 401, response.text


def test_stt_rejects_empty_body_and_too_large(user):
    headers = _auth_only(user)
    empty = client.post("/api/stt", content=b"", headers=headers)
    assert empty.status_code == 400, empty.text
    assert empty.json()["detail"]["class"] == "invalid_input", empty.text

    huge = client.post(
        "/api/stt",
        content=b"\x00" * (300 * 1024 * 1024 * 0 + 26 * 1024 * 1024),
        headers={**headers, "Content-Length": str(26 * 1024 * 1024)},
    )
    assert huge.status_code in (413, 400), huge.text


def test_stt_typed_unsupported_language(user, monkeypatch):
    from server.app.api.dependencies import get_container
    from server.app.domain.errors import AudioProcessingError

    class FakeSTT:
        def transcribe(self, audio, content_type, language_hint=None):
            raise AudioProcessingError(
                "English audio only. Detected language: tl."
            )

    container = get_container()
    original = container.transcriber
    container.transcriber = FakeSTT()
    try:
        response = client.post(
            "/api/stt",
            content=b"\x00" * 200,
            headers={**_auth_only(user), "Content-Type": "audio/mp4"},
        )
    finally:
        container.transcriber = original
    assert response.status_code == 400, response.text
    body = response.json()["detail"]
    assert body["class"] == "unsupported_language", body
    assert "Detected language" in body["message"], body


def test_text_kb_requires_auth_and_consent():
    fresh = TestClient(app)
    r = fresh.post(
        "/api/text-kb",
        json={"capture_id": _capture_id(), "text": "I met Zara at the office today"},
    )
    assert r.status_code == 401, r.text

    # signed in BUT no consent -> 403 with the consent detail
    import uuid as _uuid

    email = f"nocsent-{_uuid.uuid4().hex[:8]}@example.com"
    signup = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    token = signup.json()["dev_verification_token"]
    client.post("/api/auth/verify-email", json={"token": token})
    login = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    denied = client.post(
        "/api/text-kb",
        json={"capture_id": _capture_id(), "text": "I met Vera near the park today."},
        headers=headers,
    )
    assert denied.status_code == 403, denied.text
    assert "consent" in denied.json()["detail"].lower(), denied.text


def test_text_kb_success_and_idempotency(user):
    capture_id = _capture_id()
    first = client.post(
        "/api/text-kb",
        json={"capture_id": capture_id, "text": "I met Anna at the cafe yesterday."},
        headers=user,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["capture_id"] == capture_id
    assert body["provider"].isdigit() is False

    second = client.post(
        "/api/text-kb",
        json={"capture_id": capture_id, "text": "I met Anna at the cafe yesterday."},
        headers=user,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    # idempotent replay: nothing new created
    assert second_body["provider"] == "replayed", second_body
    assert second_body["knowledge_item_id"] == body["knowledge_item_id"]

    # exactly one capture and one knowledge item for this capture_id
    from server.app.api.dependencies import get_container

    container = get_container()
    capture = container.capture_repo.get_by_id(
        capture_id, user_id=None
    )
    item = container.knowledge_repo.get_by_capture_id(capture_id)
    assert capture is not None and item is not None


def test_text_kb_invalid_uuid_and_too_long_text(user):
    bad = client.post(
        "/api/text-kb", json={"capture_id": "not-a-uuid", "text": "x"}, headers=user
    )
    assert bad.status_code == 400 and bad.json()["detail"]["class"] == "invalid_input"

    long_text = "I met Zigfrid Wordly Longwordson somewhere around here. " * 420
    capped = client.post(
        "/api/text-kb", json={"capture_id": _capture_id(), "text": long_text},
        headers=user,
    )
    assert capped.status_code == 422, capped.text
    assert "too long" in capped.json()["detail"]["message"], capped.text


def test_text_kb_works_without_stt_provider(user):
    """The split proof: text-kb must work with NO transcriber configured."""
    from server.app.api.dependencies import get_container

    container = get_container()
    missing = object()  # delete the STT port entirely
    had = hasattr(container, "transcriber")
    original = container.transcriber if had else None
    try:
        delattr(container, "transcriber")
        response = client.post(
            "/api/text-kb",
            json={
                "capture_id": _capture_id(),
                "text": "I met Otto at the library today.",
            },
            headers=user,
        )
    finally:
        if had:
            container.transcriber = original
        else:
            pass
    assert response.status_code == 200, response.text
    assert response.json()["capture_id"]
