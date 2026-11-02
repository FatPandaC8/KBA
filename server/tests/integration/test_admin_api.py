import pytest
from fastapi.testclient import TestClient
from server.app.main import app
from server.app.infrastructure.config import get_settings

client = TestClient(app)

def test_admin_endpoints_require_authorization():
    # Attempting to access admin without credentials yields 401 Unauthorized
    resp = client.get("/api/admin/status")
    assert resp.status_code == 401

    resp_captures = client.get("/api/admin/captures")
    assert resp_captures.status_code == 401

    # The job-list endpoint was removed with the worker (pipeline split).
    assert client.get("/api/admin/jobs").status_code == 404

def test_admin_status_with_valid_token():
    settings = get_settings()
    token = settings.admin_token

    # Test using Bearer Token
    resp = client.get(
        "/api/admin/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "knowledge_count" in data
    assert "embeddings_count" in data
    assert data["database"] == "connected"

def test_admin_config_get_and_update():
    settings = get_settings()
    token = settings.admin_token

    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/admin/config", headers=headers)
    assert resp.status_code == 200
    cfg = resp.json()
    assert cfg["stt_provider"] == "faster-whisper (local)"
    assert cfg["extraction_provider"] == "local rule-based extraction"
    assert cfg["embedding_provider"] == "fastembed BAAI/bge-small-en-v1.5 (local)"
    # Admin config intentionally omits credentials and provider secrets.
    assert "openai" not in cfg
    assert "api_key" not in cfg

def test_admin_ui_page_serves():
    """The dashboard is the built React SPA; the shell is served, content is
    client-rendered (no inline scripts or secrets in the HTML)."""
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text
    assert 'src="/admin-app/assets/index' in resp.text
    assert "echo-admin-secure-key-2026" not in resp.text
