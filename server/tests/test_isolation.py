"""Cross-user isolation tests (ISO-001..018)."""
from tests.conftest import auth, make_user, token


def _create_note(client, t, content="hello"):
    r = client.post("/notes", json={"content": content}, headers=auth(client, t))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_user_cannot_read_other_note(client, db):
    a = make_user(db, "a")
    b = make_user(db, "b")
    ta = token(client, "a")
    tb = token(client, "b")
    note_a = _create_note(client, ta, "alice private")
    r = client.get(f"/notes/{note_a}", headers=auth(client, tb))
    assert r.status_code == 404


def test_user_cannot_delete_other_note(client, db):
    a = make_user(db, "a")
    b = make_user(db, "b")
    ta = token(client, "a")
    tb = token(client, "b")
    note_a = _create_note(client, ta, "secret")
    r = client.delete(f"/notes/{note_a}", headers=auth(client, tb))
    assert r.status_code == 404
    # confirm a still has it
    assert client.get(f"/notes/{note_a}", headers=auth(client, ta)).status_code == 200


def test_list_only_own_notes(client, db):
    a = make_user(db, "a")
    b = make_user(db, "b")
    ta = token(client, "a")
    tb = token(client, "b")
    _create_note(client, ta, "a-note")
    _create_note(client, tb, "b-note")
    mine = client.get("/notes", headers=auth(client, ta)).json()
    assert all(n["content"] == "a-note" for n in mine)
    assert len(mine) == 1


def test_admin_cannot_read_other_note(client, db):
    admin = make_user(db, "admin2", role="admin")
    a = make_user(db, "a")
    ta = token(client, "a")
    tadmin = token(client, "admin2")
    note_a = _create_note(client, ta, "private")
    r = client.get(f"/notes/{note_a}", headers=auth(client, tadmin))
    assert r.status_code == 404


def test_forged_user_id_ignored(client, db):
    a = make_user(db, "a")
    ta = token(client, "a")
    other = "00000000-0000-0000-0000-000000000000"
    r = client.post("/notes", json={"content": "x"}, headers=auth(client, ta))
    assert r.status_code == 201
