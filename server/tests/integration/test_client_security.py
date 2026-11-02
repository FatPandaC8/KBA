"""M2 client API security (pipeline split): session auth, ownership
isolation, transcript privacy, and the /api/stt + /api/text-kb boundaries."""

import os
import uuid

from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.domain.entities import (
    CaptureEntity,
    KnowledgeItemEntity,
)
from server.app.main import app

client = TestClient(app)


def _get_container():
    return get_container()


def _insert_capture(user_id: str, capture_id: str = None, with_audio: bool = False, status: str = "ready"):
    """Capture-truth row builder (pipeline split): no audio is stored in the
    normal flow; with_audio covers legacy rows still being deletable."""
    container = _get_container()
    capture_id = capture_id or str(uuid.uuid4())
    audio_path = ""
    if with_audio:
        user_dir = os.path.join(container.settings.upload_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        audio_path = os.path.join(user_dir, f"{capture_id}.m4a")
        with open(audio_path, "wb") as handle:
            handle.write(b"audio-bytes")
    capture = CaptureEntity(
        id=capture_id,
        idempotency_key=capture_id,
        audio_path=audio_path,
        user_id=user_id,
        duration_ms=1000,
        status=status,
    )
    container.capture_repo.save(capture)
    return capture, audio_path


def _insert_knowledge(user_id: str, capture_id: str, transcript: str = "private transcript"):
    container = _get_container()
    item = KnowledgeItemEntity.create(
        id=str(uuid.uuid4()),
        capture_id=capture_id,
        title="Private item",
        core_idea="A private idea",
        transcript=transcript,
        user_id=user_id,
    )
    container.knowledge_repo.save(item)
    container.embedding_repo.save(item.id, b"\x00" * 16, user_id=user_id)
    return item


def test_client_endpoints_require_a_session(user_factory):
    assert client.get("/api/recordings").status_code == 401
    assert client.get("/api/knowledge").status_code == 401
    assert client.get("/api/graph").status_code == 401
    assert client.get("/api/knowledge/semantic-search?q=hello").status_code == 401
    assert client.delete(f"/api/captures/{uuid.uuid4()}").status_code == 401
    assert client.post(
        "/api/stt", content=b"\x00" * 200, headers={"Content-Type": "audio/mp4"}
    ).status_code == 401
    assert client.post(
        "/api/text-kb", json={"capture_id": str(uuid.uuid4()), "text": "hi"}
    ).status_code == 401
    assert client.get(
        "/api/knowledge", headers={"Authorization": "Bearer not-a-session"}
    ).status_code == 401

    # The admin shared secret is not a user session and must not unlock client data.
    from server.app.infrastructure.config import get_settings

    assert client.get(
        "/api/knowledge",
        headers={"Authorization": f"Bearer {get_settings().admin_token}"},
    ).status_code == 401


def test_unverified_user_cannot_create_or_read_records(user_factory):
    user = user_factory(client, verified=False)
    assert client.get("/api/auth/me", headers=user.headers).status_code == 200
    assert client.get("/api/knowledge", headers=user.headers).status_code == 403
    assert client.get("/api/recordings", headers=user.headers).status_code == 403
    ingest = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": str(uuid.uuid4()), "text": "I met Uma near the office."},
    )
    assert ingest.status_code == 403


def test_missing_consent_blocks_data_routes(user_factory):
    user = user_factory(client, consent=False)
    assert client.get("/api/knowledge", headers=user.headers).status_code == 403
    assert client.get("/api/graph", headers=user.headers).status_code == 403
    assert client.get("/api/consent", headers=user.headers).json()["granted"] is False


def test_transcripts_are_never_exposed_to_clients(user_factory):
    user = user_factory(client)
    capture, _ = _insert_capture(user.id)
    item = _insert_knowledge(user.id, capture.id, transcript="TOP-SECRET-TRANSCRIPT")

    listing = client.get("/api/knowledge", headers=user.headers)
    assert listing.status_code == 200
    assert "TOP-SECRET-TRANSCRIPT" not in listing.text
    assert all("transcript" not in entry for entry in listing.json())

    detail = client.get(f"/api/knowledge/{item.id}", headers=user.headers)
    assert detail.status_code == 200
    assert "transcript" not in detail.json()
    assert "TOP-SECRET-TRANSCRIPT" not in detail.text


def test_users_cannot_read_or_mutate_each_others_records(user_factory):
    alice = user_factory(client)
    bob = user_factory(client)

    capture, _ = _insert_capture(alice.id)
    item = _insert_knowledge(alice.id, capture.id)
    capture2, _ = _insert_capture(alice.id)
    other = _insert_knowledge(alice.id, capture2.id)

    assert client.get("/api/knowledge", headers=bob.headers).json() == []
    assert client.get(f"/api/knowledge/{item.id}", headers=bob.headers).status_code == 404
    assert client.delete(f"/api/knowledge/{item.id}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/knowledge/{item.id}", headers=alice.headers).status_code == 200

    assert client.get("/api/recordings", headers=bob.headers).json() == []
    # capture_id taken by another account is a cross-user conflict (S4a).
    conflict = client.post(
        "/api/text-kb",
        headers=bob.headers,
        json={"capture_id": capture.id, "text": "I met Bob near the lab."},
    )
    assert conflict.status_code == 409, conflict.text


def test_text_kb_rejects_non_uuid_and_mismatched_ids(user_factory):
    user = user_factory(client)
    escape = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": "../escape", "text": "I met Eva at the harbor."},
    )
    assert escape.status_code == 400, escape.text

    non_canonical = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": uuid.uuid4().hex, "text": "I met Finn at the pier."},
    )
    assert non_canonical.status_code == 400, non_canonical.text


def test_text_kb_rejects_an_empty_or_oversized_text(user_factory, monkeypatch):
    user = user_factory(client)
    container = _get_container()

    empty = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": str(uuid.uuid4()), "text": "   "},
    )
    assert empty.status_code == 400, empty.text

    old_limit = get_container().ingestor.settings.max_text_chars
    monkeypatch.setattr(
        get_container().ingestor.settings, "max_text_chars", 10
    )
    capped = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": str(uuid.uuid4()), "text": "x" * 64},
    )
    assert capped.status_code == 422, capped.text
    assert capped.json()["detail"]["class"] == "invalid_input", capped.text


def test_text_kb_is_idempotent_per_user(user_factory):
    user = user_factory(client)
    capture, _ = _insert_capture(user.id, status="ready")
    item = _insert_knowledge(user.id, capture.id)
    # The existing capture implies a previous successful ingest for this id.
    replay = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": capture.id, "text": "replacement transcript text"},
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["capture_id"] == capture.id
    assert body["knowledge_item_id"] == item.id
    # Idempotent replay: no new capture was created for the same id.
    assert _get_container().capture_repo.count(user_id=user.id) == 1


def test_delete_capture_removes_all_owned_data(user_factory):
    user = user_factory(client)
    capture, audio_path = _insert_capture(user.id, with_audio=True)
    item = _insert_knowledge(user.id, capture.id)
    capture2, _ = _insert_capture(user.id)
    related = _insert_knowledge(user.id, capture2.id)

    # Delete the capture
    assert client.delete(f"/api/captures/{capture.id}", headers=user.headers).status_code == 200

    # Verify the deleted capture is gone from recordings list
    recordings = client.get("/api/recordings", headers=user.headers).json()
    capture_ids = [r["capture_id"] for r in recordings]
    assert capture.id not in capture_ids, "Deleted capture should not appear in recordings"
    assert capture2.id in capture_ids, "Other capture should still be present"

    # The knowledge item linked to the deleted capture should also be gone
    assert client.get(f"/api/knowledge/{item.id}", headers=user.headers).status_code == 404

    # The related knowledge item (linked to a different capture) should still exist
    assert client.get(f"/api/knowledge/{related.id}", headers=user.headers).status_code == 200

    # The audio file should be deleted
    assert not os.path.exists(os.path.join(get_container().settings.upload_dir, user.id, f"{capture.id}.m4a"))
