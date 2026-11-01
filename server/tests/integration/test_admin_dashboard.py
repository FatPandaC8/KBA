import uuid
import pytest

from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.domain.entities import CaptureEntity, KnowledgeItemEntity, UserEntity
from server.app.infrastructure.config import get_settings
from server.app.main import app
from server.app.security import hash_password

client = TestClient(app)

# System user ID for admin tests (must be valid UUID for FK)
SYSTEM_USER_ID = "11111111-1111-1111-1111-111111111111"


def _admin_headers():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


@pytest.fixture(scope="session", autouse=True)
def create_system_user():
    """Create a system user for admin tests."""
    container = get_container()
    system_user_id = "11111111-1111-1111-1111-111111111111"
    print(f"[DEBUG] Creating system user: {system_user_id}", flush=True)
    container.user_repo.save(
        UserEntity(
            id=system_user_id,
            email="system@echo.local",
            email_normalized="system@echo.local",
            password_hash=hash_password("system"),
            is_locked=False,
        )
    )
    print(f"[DEBUG] System user created", flush=True)
    yield
    # Cleanup (optional, but good practice)
    container.user_repo.delete(system_user_id)


def _admin_headers():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


def test_dashboard_serves_react_app_without_inline_scripts():
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text

    # Should serve the React SPA entry point, not inline HTML with scripts
    assert "echo-admin-secure-key-2026" not in html
    assert "?auth=" not in html
    assert "onclick=" not in html
    assert "onchange=" not in html
    # Should load JS/CSS as external modules, not inline
    assert 'src="/admin-app/assets/index' in html
    assert 'href="/admin-app/assets/index' in html
    # No inline event handlers or scripts
    assert "<script>" not in html or "type=\"module\"" in html


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
            user_id=SYSTEM_USER_ID,
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
            user_id=SYSTEM_USER_ID,
        )
    )
    response = client.get(
        f"/api/admin/captures/{capture_id}/audio", headers=_admin_headers()
    )
    assert response.status_code == 404
    container.capture_repo.delete(capture_id, SYSTEM_USER_ID)


def test_admin_knowledge_delete_requires_admin_token_and_cleans_up():
    container = get_container()
    item_id = str(uuid.uuid4())
    # Create a capture first (FK requirement)
    container.capture_repo.save(
        CaptureEntity(
            id=item_id,
            idempotency_key=item_id,
            audio_path="",
            duration_ms=0,
            status="ready",
            user_id=SYSTEM_USER_ID,
        )
    )
    container.knowledge_repo.save(
        KnowledgeItemEntity.create(
            id=item_id,
            capture_id=item_id,
            title="Admin delete me",
            core_idea="idea",
            transcript="",
            user_id=SYSTEM_USER_ID,
        )
    )
    container.embedding_repo.save(item_id, b"\x00" * 8, user_id=SYSTEM_USER_ID)

    url = f"/api/admin/knowledge/{item_id}"
    assert client.delete(url).status_code == 401
    assert client.delete(url, headers=_admin_headers()).status_code == 200
    assert container.knowledge_repo.get_by_id(item_id) is None
    assert container.embedding_repo.get_by_item_id(item_id) is None
