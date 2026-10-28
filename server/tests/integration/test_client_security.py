import os
import uuid

from fastapi.testclient import TestClient

from server.app.main import app
from server.app.api.dependencies import get_container
from server.app.application.dto import ProcessingJobDTO
from server.app.domain.entities import (
    CaptureEntity,
    EvalRecordEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
)

from server.app.infrastructure.config import get_settings

client = TestClient(app)


def _headers():
    return {"Authorization": f"Bearer {get_settings().client_token}"}


def _container():
    return get_container()


def _insert_capture_with_audio(capture_id: str) -> str:
    container = _container()
    os.makedirs(container.settings.upload_dir, exist_ok=True)
    path = os.path.join(container.settings.upload_dir, f"{capture_id}.m4a")
    with open(path, "wb") as handle:
        handle.write(b"audio")
    container.capture_repo.save(
        CaptureEntity(
            id=capture_id,
            idempotency_key=capture_id,
            audio_path=path,
            duration_ms=1000,
            status="ready",
        )
    )
    return path


def _insert_knowledge(capture_id: str):
    container = _container()
    item = KnowledgeItemEntity.create(
        id=capture_id,
        capture_id=capture_id,
        title="Delete me",
        core_idea="A test idea",
        transcript="A test transcript",
    )
    container.knowledge_repo.save(item)
    container.embedding_repo.save(item.id, b"\x00" * 16)
    return item


def test_client_endpoints_require_token():
    token = get_settings().client_token
    assert client.get("/api/knowledge").status_code == 401
    assert client.get(
        "/api/knowledge", headers={"X-Client-Token": token}
    ).status_code == 200
    assert client.get(
        "/api/knowledge", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_client_auth_fails_closed_when_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "client_token", "")
    response = client.get("/api/knowledge")
    assert response.status_code == 503


def test_upload_rejects_non_uuid_capture_id():
    files = {"file": ("capture.m4a", b"\x00" * 32, "audio/mp4")}
    data = {
        "capture_id": "../escape",
        "idempotency_key": "key",
        "duration_ms": "1000",
    }
    response = client.post(
        "/api/captures/upload", files=files, data=data, headers=_headers()
    )
    assert response.status_code == 400
    upload_root = os.path.realpath(_container().settings.upload_dir)
    escaped = os.path.realpath(os.path.join(upload_root, "..", "escape.m4a"))
    assert not os.path.exists(escaped)


def test_upload_rejects_oversized_body(monkeypatch):
    container = _container()
    monkeypatch.setattr(container.settings, "max_upload_bytes", 10)
    capture_id = str(uuid.uuid4())
    files = {"file": ("capture.m4a", b"\x00" * 64, "audio/mp4")}
    data = {
        "capture_id": capture_id,
        "idempotency_key": capture_id,
        "duration_ms": "1000",
    }
    response = client.post(
        "/api/captures/upload", files=files, data=data, headers=_headers()
    )
    assert response.status_code == 413
    assert not os.path.exists(
        os.path.join(container.settings.upload_dir, f"{capture_id}.m4a")
    )


def test_delete_capture_removes_all_associated_data():
    capture_id = str(uuid.uuid4())
    audio_path = _insert_capture_with_audio(capture_id)
    item = _insert_knowledge(capture_id)

    container = _container()
    related = _insert_knowledge(str(uuid.uuid4()))
    relation = RelationshipEntity.create(
        from_id=item.id, to_id=related.id, id=str(uuid.uuid4())
    )
    container.rel_repo.save(relation)
    container.job_repo.record_job(
        ProcessingJobDTO(
            id=capture_id,
            capture_id=capture_id,
            stage="completed",
            status="ready",
            duration_ms=1000,
            error_message=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
    )
    container.eval_repo.save(
        EvalRecordEntity(
            id=str(uuid.uuid4()),
            capture_id=capture_id,
            transcript="test",
            structured_json="{}",
            consent_given=True,
        )
    )

    response = client.delete(f"/api/captures/{capture_id}", headers=_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["audio_removed"] is True
    assert not os.path.exists(audio_path)
    assert container.capture_repo.get_by_id(capture_id) is None
    assert container.knowledge_repo.get_by_id(capture_id) is None
    assert container.job_repo.get_by_capture_id(capture_id) is None
    assert container.eval_repo.get_all_consented() == []
    assert container.rel_repo.get_by_id(relation.id) is None


def test_delete_capture_is_idempotent():
    capture_id = str(uuid.uuid4())
    first = client.delete(f"/api/captures/{capture_id}", headers=_headers())
    second = client.delete(f"/api/captures/{capture_id}", headers=_headers())
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deleted"] is False


def test_consent_withdrawal_purges_retained_audio_and_eval_records():
    container = _container()
    capture_id = str(uuid.uuid4())
    audio_path = _insert_capture_with_audio(capture_id)
    container.eval_repo.save(
        EvalRecordEntity(
            id=str(uuid.uuid4()),
            capture_id=capture_id,
            transcript="test",
            structured_json="{}",
            consent_given=True,
        )
    )

    response = client.post(
        "/api/eval/consent",
        json={"consent_given": False},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["purged_audio_files"] >= 1
    assert not os.path.exists(audio_path)
    assert container.capture_repo.get_by_id(capture_id).audio_path == ""
    assert container.eval_repo.get_all_consented() == []
