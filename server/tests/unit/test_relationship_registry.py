"""U1: open-ended relationship registry semantics and invalid proposals."""

import pytest

from server.app.adapters.outbound.persistence import (
    SqliteRelationshipTypeRegistryRepository,
)
from server.app.domain.entities import RelationshipTypeRegistryEntry
from server.app.domain.errors import ValidationError
from server.app.infrastructure.database import DatabaseManager


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager(str(tmp_path / "echo.db"))
    manager.init_database()
    return manager


def test_semantically_equivalent_proposal_reuses_canonical(db_manager):
    repo = SqliteRelationshipTypeRegistryRepository(db_manager)
    entry = repo.ensure("alice", "Works at", provenance="extraction-proposal")
    same = repo.ensure("alice", "works at", provenance="extraction-proposal")
    assert same.id == entry.id


def test_alias_reuses_the_canonical_entry(db_manager):
    repo = SqliteRelationshipTypeRegistryRepository(db_manager)
    entry = repo.ensure("alice", "Depends on")
    same = repo.find_equivalent("alice", ["relies on"])
    assert same is not None and same.normalized_key == entry.normalized_key


def test_new_meaning_creates_registry_entry_and_is_reused(db_manager):
    repo = SqliteRelationshipTypeRegistryRepository(db_manager)
    first = repo.ensure("alice", "Met with")
    listed = {e.canonical_name for e in repo.list_for_user("alice")}
    assert "Met with" in listed
    again = repo.ensure("alice", "Met with")
    assert again.id == first.id


def test_matches_survive_casing_and_underscores(db_manager):
    repo = SqliteRelationshipTypeRegistryRepository(db_manager)
    entry = repo.ensure("alice", "Works At")
    assert repo.find_equivalent("alice", ["works_at"]).normalized_key == entry.normalized_key
    assert repo.find_equivalent("alice", ["Works at"]).normalized_key == entry.normalized_key


def test_registry_is_scoped_per_user_with_shared_seeds(db_manager):
    repo = SqliteRelationshipTypeRegistryRepository(db_manager)
    repo.ensure("alice", "Met with")
    names_bob = {e.canonical_name for e in repo.list_for_user("bob")}
    names_alice = {e.canonical_name for e in repo.list_for_user("alice")}
    assert "Met with" not in names_bob
    assert "Met with" in names_alice
    # Seed meanings stay available for everyone.
    assert {"Depends on", "Supports", "Related to"} <= names_bob


def test_invalid_canonical_names_are_refused():
    with pytest.raises(ValidationError):
        RelationshipTypeRegistryEntry.create("", "")
    with pytest.raises(ValidationError):
        RelationshipTypeRegistryEntry.create("   ", "")
    with pytest.raises(ValidationError):
        RelationshipTypeRegistryEntry.create(None, "")  # type: ignore[arg-type]
