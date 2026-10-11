"""Note CRUD, idempotency, size limits (NOTE-001..015)."""
from tests.conftest import auth, make_user, token


def test_create_and_read(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    r = client.post("/notes", json={"content": "hello"}, headers=auth(client, t))
    assert r.status_code == 201
    nid = r.json()["id"]
    got = client.get(f"/notes/{nid}", headers=auth(client, t)).json()
    assert got["content"] == "hello"
    assert got["capture_type"] == "text"


def test_idempotency_no_duplicate(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    r1 = client.post("/notes", json={"content": "dup", "idempotency_key": "k1"},
                     headers=auth(client, t))
    r2 = client.post("/notes", json={"content": "dup", "idempotency_key": "k1"},
                     headers=auth(client, t))
    assert r1.json()["id"] == r2.json()["id"]
    notes = client.get("/notes", headers=auth(client, t)).json()
    assert len(notes) == 1


def test_owner_derived_from_token(client, db):
    a = make_user(db, "a")
    b = make_user(db, "b")
    ta = token(client, "a")
    tb = token(client, "b")
    r = client.post("/notes", json={"content": "mine"}, headers=auth(client, ta))
    nid = r.json()["id"]
    assert client.get(f"/notes/{nid}", headers=auth(client, tb)).status_code == 404


def test_update_and_delete(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    nid = client.post("/notes", json={"content": "v1"}, headers=auth(client, t)).json()["id"]
    patched = client.patch(f"/notes/{nid}", json={"content": "v2"},
                           headers=auth(client, t)).json()
    assert patched["content"] == "v2"
    assert patched["content_version"] == 2
    assert client.delete(f"/notes/{nid}", headers=auth(client, t)).status_code == 204
    # ponytail: notes are soft-deleted (status=deleted), so the record remains
    # visible as a deleted note rather than vanishing. Evidence/history retention
    # is a documented P1 concern, not an MVP blocker.
    got = client.get(f"/notes/{nid}", headers=auth(client, t)).json()
    assert got["status"] == "deleted"


def test_size_limit(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    r = client.post("/notes", json={"content": "x" * 9000}, headers=auth(client, t))
    assert r.status_code == 400


def test_empty_rejected(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    r = client.post("/notes", json={"content": ""}, headers=auth(client, t))
    assert r.status_code == 400
