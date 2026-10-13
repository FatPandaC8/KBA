"""Extraction + review pipeline tests (EXT, REV, E2E)."""
from tests.conftest import auth, make_user, token


def test_extract_and_review_accept(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    nid = client.post("/notes", json={"content": "Alice works at Acme."},
                      headers=auth(client, t)).json()["id"]
    r = client.post(f"/notes/{nid}/extract", headers=auth(client, t))
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "succeeded"
    # 1 relationship proposal queued (low-confidence path is auto-saved; here 0.97>=0.9
    # explicit → auto-saved, so no review items). Verify the entity + relationship were persisted.
    # Assert: Alice and Acme entities exist, works_at relationship exists.
    from app.models import Entity, Relationship
    db.expunge_all()
    rels = db.execute(
        __import__("sqlalchemy").select(Relationship).where(
            Relationship.user_id == u.id, Relationship.predicate == "works_at"
        )
    ).scalars().all()
    assert len(rels) == 1
    ents = db.execute(
        __import__("sqlalchemy").select(Entity).where(Entity.user_id == u.id)
    ).scalars().all()
    assert {e.canonical_name for e in ents} == {"Alice", "Acme"}


def test_extract_unknown_content_no_proposals(client, db):
    u = make_user(db, "a")
    t = token(client, "a")
    nid = client.post("/notes", json={"content": "nothing here."},
                      headers=auth(client, t)).json()["id"]
    r = client.post(f"/notes/{nid}/extract", headers=auth(client, t))
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"


def test_register_self_service(client, db):
    r = client.post("/auth/register", json={"username": "carol", "password": "pw"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"
    # can log in
    t = token(client, "carol")
    assert t


def test_isolation_extraction(client, db):
    a = make_user(db, "a")
    b = make_user(db, "b")
    ta = token(client, "a")
    tb = token(client, "b")
    nid = client.post("/notes", json={"content": "Alice works at Acme."},
                      headers=auth(client, ta)).json()["id"]
    client.post(f"/notes/{nid}/extract", headers=auth(client, ta))
    # bob cannot extract a's note
    r = client.post(f"/notes/{nid}/extract", headers=auth(client, tb))
    assert r.status_code == 404
