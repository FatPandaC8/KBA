"""Auth and account-lifecycle tests (AUTH-001..012)."""
from tests.conftest import auth, make_user, token


def test_login_success(client):
    t = token(client, "admin")
    assert t


def test_login_bad_credentials(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_unauth_rejected(client):
    r = client.get("/notes")
    assert r.status_code == 401


def test_disabled_account_rejected(client, db):
    u = make_user(db, "bob", status="disabled")
    r = client.post("/auth/login", json={"username": "bob", "password": "pw"})
    assert r.status_code == 401


def test_me_returns_identity(client):
    t = token(client, "admin")
    r = client.get("/auth/me", headers=auth(client, t))
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin"
    assert body["status"] == "active"


def test_self_role_change_blocked(client, db):
    u = make_user(db, "alice")
    t = token(client, "alice")
    r = client.put("/admin/users/{}/role".format(u.id),
                   json={"role": "admin", "reason": "x"},
                   headers=auth(client, t))
    assert r.status_code == 403  # not an admin


def test_non_admin_cannot_access_admin_routes(client, db):
    u = make_user(db, "alice")
    t = token(client, "alice")
    r = client.get("/admin/users", headers=auth(client, t))
    assert r.status_code == 403
