import uuid

from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.domain.entities import CaptureEntity, KnowledgeItemEntity
from server.app.infrastructure.config import get_settings
from server.app.main import app

client = TestClient(app)


def _admin_headers():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


def test_dashboard_has_no_default_token_query_token_or_inline_handlers():
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text

    assert "echo-admin-secure-key-2026" not in html
    assert "?auth=" not in html
    assert "onclick=" not in html
    assert "onchange=" not in html
    # Untrusted values must be routed through the escaping helper.
    assert "function escapeHtml" in html
    assert "escapeHtml(k.title)" in html
    assert "escapeHtml(l.message)" in html
    # Audio is fetched with the auth header, not a query string.
    assert "buildAuthenticatedAudio" in html
    assert "Authorization" in html


def test_admin_endpoints_reject_missing_or_query_tokens():
    capture_id = str(uuid.uuid4())
    container = get_container()
    container.capture_repo.save(
        CaptureEntity(
            id=capture_id,
            idempotency_key=capture_id,
            audio_path="",
            duration_ms=0,
            status="ready",
        )
    )

    assert client.get("/api/admin/status").status_code == 401
    assert (
        client.get(f"/api/admin/captures/{capture_id}/audio?auth=anything").status_code
        == 401
    )
    assert client.get("/api/admin/status", headers=_admin_headers()).status_code == 200


def test_admin_auth_fails_closed_when_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "")
    assert client.get("/api/admin/status").status_code == 503


def test_admin_audio_rejects_paths_outside_upload_directory():
    capture_id = str(uuid.uuid4())
    container = get_container()
    container.capture_repo.save(
        CaptureEntity(
            id=capture_id,
            idempotency_key=capture_id,
            audio_path="/etc/passwd",
            duration_ms=0,
            status="ready",
        )
    )
    response = client.get(
        f"/api/admin/captures/{capture_id}/audio", headers=_admin_headers()
    )
    assert response.status_code == 404
    container.capture_repo.delete(capture_id)


def test_admin_knowledge_delete_requires_admin_token_and_cleans_up():
    container = get_container()
    item_id = str(uuid.uuid4())
    container.knowledge_repo.save(
        KnowledgeItemEntity.create(
            id=item_id,
            capture_id=item_id,
            title="Admin delete me",
            core_idea="idea",
            transcript="",
        )
    )
    container.embedding_repo.save(item_id, b"\x00" * 8)

    url = f"/api/admin/knowledge/{item_id}"
    assert client.delete(url).status_code == 401
    assert client.delete(url, headers=_admin_headers()).status_code == 200
    assert container.knowledge_repo.get_by_id(item_id) is None
    assert container.embedding_repo.get_by_item_id(item_id) is None
