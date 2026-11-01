"""M2 client API security: session auth, ownership isolation, transcript privacy."""

import os
import uuid

from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.application.dto import ProcessingJobDTO
from server.app.domain.entities import (
    CaptureEntity,
    EvalRecordEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
)
from server.app.main import app

client = TestClient(app)


def _get_container():
    return get_container()


def _insert_capture(user_id: str, capture_id: str = None, with_audio: bool = True, status: str = "ready"):
    container = _get_container()
    capture_id = capture_id or str(uuid.uuid4())
    user_dir = os.path.join(container.settings.upload_dir, user_id)
    os.makedirs(user_dir, exist_ok=True)
    audio_path = os.path.join(user_dir, f"{capture_id}.m4a")
    if with_audio:
        with open(audio_path, "wb") as handle:
            handle.write(b"audio-bytes")
    capture = CaptureEntity(
        id=capture_id,
        idempotency_key=f"key-{capture_id}",
        audio_path=audio_path if with_audio else "",
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
    assert client.get(f"/api/recordings/{uuid.uuid4()}/audio").status_code == 401
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
    upload = client.post(
        "/api/captures/upload",
        headers=user.headers,
        files={"file": ("capture.m4a", b"\x00" * 32, "audio/mp4")},
        data={
            "capture_id": str(uuid.uuid4()),
            "idempotency_key": str(uuid.uuid4()),
            "duration_ms": "1000",
        },
    )
    assert upload.status_code == 403


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

    # The owner may still play the retained audio, but never receives the text.
    audio = client.get(f"/api/recordings/{capture.id}/audio", headers=user.headers)
    assert audio.status_code == 200
    assert audio.content == b"audio-bytes"


def test_users_cannot_read_or_mutate_each_others_records(user_factory):
    alice = user_factory(client)
    bob = user_factory(client)

    capture, audio_path = _insert_capture(alice.id)
    item = _insert_knowledge(alice.id, capture.id)
    capture2, _ = _insert_capture(alice.id)
    other = _insert_knowledge(alice.id, capture2.id)
    _get_container().job_repo.record_job(
        ProcessingJobDTO(
            id=capture.id,
            capture_id=capture.id,
            stage="completed",
            status="ready",
            attempt=0,
            error_class="",
            lease_owner="",
            lease_expires_at=None,
            stage_outputs={},
            duration_ms=1000,
            error_message=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            user_id=alice.id,
        )
    )

    assert client.get("/api/knowledge", headers=bob.headers).json() == []
    assert client.get(f"/api/knowledge/{item.id}", headers=bob.headers).status_code == 404
    assert client.delete(f"/api/knowledge/{item.id}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/knowledge/{item.id}", headers=alice.headers).status_code == 200

    assert client.get("/api/recordings", headers=bob.headers).json() == []
    assert client.get(f"/api/recordings/{capture.id}/status", headers=bob.headers).status_code == 404
    assert client.get(f"/api/recordings/{capture.id}/audio", headers=bob.headers).status_code == 404

def test_upload_rejects_non_uuid_and_foreign_capture_ids(user_factory):
    alice = user_factory(client)
    bob = user_factory(client)
    alice_capture, alice_audio = _insert_capture(alice.id)

    escape = client.post(
        "/api/captures/upload",
        headers=bob.headers,
        files={"file": ("capture.m4a", b"\x00" * 32, "audio/mp4")},
        data={
            "capture_id": "../escape",
            "idempotency_key": "key",
            "duration_ms": "1000",
        },
    )
    assert escape.status_code == 400
    upload_root = os.path.realpath(_get_container().settings.upload_dir)
    assert not os.path.exists(os.path.realpath(os.path.join(upload_root, "..", "escape.m4a")))

    conflict = client.post(
        "/api/captures/upload",
        headers=bob.headers,
        files={"file": ("capture.m4a", b"bob-audio", "audio/mp4")},
        data={
            "capture_id": alice_capture.id,
            "idempotency_key": str(uuid.uuid4()),
            "duration_ms": "1000",
        },
    )
    assert conflict.status_code == 409
    with open(alice_audio, "rb") as handle:
        assert handle.read() == b"audio-bytes"


def test_upload_rejects_oversized_body(user_factory, monkeypatch):
    user = user_factory(client)
    container = _get_container()
    monkeypatch.setattr(container.settings, "max_upload_bytes", 10)
    capture_id = str(uuid.uuid4())

    response = client.post(
        "/api/captures/upload",
        headers=user.headers,
        files={"file": ("capture.m4a", b"\x00" * 64, "audio/mp4")},
        data={
            "capture_id": capture_id,
            "idempotency_key": capture_id,
            "duration_ms": "1000",
        },
    )
    assert response.status_code == 413
    # The partial file is removed and never escapes the user's own directory.
    assert not os.path.exists(
        os.path.join(container.settings.upload_dir, user.id, f"{capture_id}.m4a")
    )


def test_upload_is_idempotent_per_user(user_factory):
    user = user_factory(client)
    capture, _ = _insert_capture(user.id, status="ready")
    item = _insert_knowledge(user.id, capture.id)
    # The existing capture uses this idempotency key.
    idem = capture.idempotency_key

    response = client.post(
        "/api/captures/upload",
        headers=user.headers,
        files={"file": ("capture.m4a", b"replacement-audio", "audio/mp4")},
        data={
            "capture_id": str(uuid.uuid4()),
            "idempotency_key": idem,
            "duration_ms": "1000",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["capture_id"] == capture.id
    assert body["knowledge_item"]["id"] == item.id
    assert "transcript" not in body["knowledge_item"]
    # No new capture was created for the same key.
    assert _get_container().capture_repo.count(user_id=user.id) == 1


def test_delete_capture_removes_all_owned_data(user_factory):
    user = user_factory(client)
    capture, audio_path = _insert_capture(user.id)
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