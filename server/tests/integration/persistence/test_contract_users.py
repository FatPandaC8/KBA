"""User/tombstone/support/registry contract coverage."""

import uuid

from server.app.domain.entities import RelationshipTypeRegistryEntry

from ._helpers import make_entity, make_capture, make_item


def test_user_upsert_roundtrip_and_delete(container_):
    import uuid as _uuid

    from server.app.domain.entities import UserEntity

    u = UserEntity(
        id=str(_uuid.uuid4()),
        email=f"contract-{_uuid.uuid4().hex}@example.com",
        email_normalized=None,
        password_hash=None,
        google_sub=None,
        email_verified_at="2026-01-01T00:00:00+00:00",
        is_locked=False,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    u.email_normalized = u.email
    container_.user_repo.save(u)
    got = container_.user_repo.get_by_email(u.email)
    assert got.id == u.id
    container_.user_repo.delete(u.id)
    assert container_.user_repo.get_by_id(u.id) is None


def test_tombstone_is_tombstoned_and_list(container_, user):
    repo = container_.tombstone_repo
    repo.add(user.id, "entity", "echo")
    assert repo.is_tombstoned(user.id, "entity", "echo") is True
    listed = repo.list_for_user(user.id)
    assert any(pair["kind"] == "entity" and pair["normalized_key"] == "echo" for pair in listed)
    assert repo.delete_for_user(user.id) >= 1
    assert repo.is_tombstoned(user.id, "entity", "echo") is False


def test_record_supports_index(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    entity = make_entity(user.id, "Support")
    container_.entity_repo.save(entity)
    repo = container_.support_repo
    repo.add(user.id, capture.id, "entity", entity.id)
    assert [s["target_id"] for s in repo.list_for_record(user.id, capture.id)] == [entity.id]
    assert repo.list_for_target(user.id, "entity", entity.id) == [capture.id]
    assert repo.delete_for_record(user.id, capture.id) == 1
    assert repo.list_for_target(user.id, "entity", entity.id) == []


def test_registry_case_insensitive_equivalents(container_, user):
    repo = container_.rel_type_repo
    entry = repo.ensure(user.id, "Works at", provenance="test")
    same = repo.ensure(user.id, "works at", provenance="test")
    assert same.id == entry.id
    assert repo.find_equivalent(user.id, ["works_at"]).normalized_key == entry.normalized_key

    first = repo.ensure(user.id, "Met with", provenance="test")
    listed = {e.canonical_name for e in repo.list_for_user(user.id)}
    assert "Met with" in listed
    again = repo.ensure(user.id, "Met with", provenance="test")
    assert again.id == first.id
    names_other = {e.canonical_name for e in repo.list_for_user(str(uuid.uuid4()))}
    assert "Met with" not in names_other
    # Seeds stay globally visible.
    assert {"Depends on", "Supports", "Related to"} <= names_other


def test_duplicates_records_and_flagged(container_, user):
    a = make_entity(user.id, "DupA")
    b = make_entity(user.id, "Dup A")
    repo = container_.entity_repo
    repo.save(a)
    repo.save(b)
    dup = container_.duplicate_repo
    dup.record(user.id, a.id, b.id, 0.8, "flagged")
    flagged = dup.list_flagged(user.id)
    assert len(flagged) == 1
    dup.decide(user.id, a.id, b.id, "accepted")
    assert dup.list_flagged(user.id) == []
    # A decided pair is not reopened by re-recording (INSERT ... DO NOTHING
    # semantics on the pair, like the SQLite base).
    dup.record(user.id, a.id, b.id, 0.9, "flagged")
    assert dup.list_flagged(user.id) == []
    assert dup.delete_for_entity(a.id, user_id=user.id) >= 1
