from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.main import app

client = TestClient(app)


def admin_headers():
    return {"X-Admin-Token": get_container().settings.admin_token}


def test_console_endpoints_require_admin_auth():
    for path in ("/api/admin/overview", "/api/admin/users", "/api/admin/captures-page", "/api/admin/graph/entities"):
        assert client.get(path).status_code == 401


def test_console_lists_paginated_real_data(user_factory):
    user_factory(client)
    response = client.get("/api/admin/users?limit=1&offset=0", headers=admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert body["total"] >= 1
    assert len(body["rows"]) == 1


def test_console_does_not_expose_graph_mutation_routes():
    headers = admin_headers()
    assert client.post("/api/admin/graph/entities", headers=headers, json={}).status_code == 405
    assert client.delete("/api/admin/graph/entities/no-such-id", headers=headers).status_code == 405
    assert client.delete("/api/admin/graph/relationships/no-such-id", headers=headers).status_code == 405
