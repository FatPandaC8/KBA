"""EntityRepositoryPort contract (ADR R2/R3)."""

import threading

from server.app.adapters.outbound.persistence.postgres.entities import (
    PostgresEntityRepository,
)

from ._helpers import make_entity, make_capture, make_item


def test_get_or_create_self_is_idempotent_and_single(container_, user):
    first = container_.entity_repo.get_or_create_self(user.id)
    second = container_.entity_repo.get_or_create_self(user.id)
    assert first.id == second.id
    assert first.is_self and first.name == "Me"
    selfs = [e for e in container_.entity_repo.get_all(user_id=user.id) if e.is_self]
    assert len(selfs) == 1


def test_get_or_create_self_survives_a_concurrent_first_writer(container_, user):
    """Two concurrent first-time calls must still yield one self entity.

    The partial unique index is the DB safety net; the ON CONFLICT ... DO
    NOTHING upsert is the app-level rule (R3).
    """
    import psycopg

    from server.tests.postgres_testinfra import worker_database_url

    results: list = []

    def raw_insert():
        with psycopg.connect(worker_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entities (id, user_id, capture_id, name, normalized_name,
                        entity_type, description, confidence, certainty, provenance,
                        provider_id, model_version, user_edited, is_self)
                    VALUES (gen_random_uuid(), %s, NULL, 'Me', 'me', 'self', '', 1.0,
                            'confirmed', 'racer', '', '', FALSE, TRUE)
                    ON CONFLICT (user_id) WHERE is_self DO NOTHING
                    """,
                    (user.id,),
                )

    thread = threading.Thread(target=raw_insert)
    thread.start()
    try:
        results.append(container_.entity_repo.get_or_create_self(user.id))
    finally:
        thread.join()
    selfs = [e for e in container_.entity_repo.get_all(user_id=user.id) if e.is_self]
    assert len(selfs) == 1


def test_cleanup_orphans_never_touches_the_self_entity(container_, user):
    repo = container_.entity_repo
    self_entity = repo.get_or_create_self(user.id)
    orphan = make_entity(user.id, "Lone")  # no relationships
    repo.save(orphan)
    deleted = repo.cleanup_orphans(user.id)
    assert deleted >= 1
    assert repo.get_by_id(orphan.id, user_id=user.id) is None
    # R3: the self entity is never pruned by dedup or orphan cleanup.
    assert repo.get_by_id(self_entity.id, user_id=user.id) is not None


def test_get_or_create_self_fills_entity_type_and_audit_fields(container_, user):
    entity = container_.entity_repo.get_or_create_self(user.id)
    assert entity.entity_type == "self"
    assert entity.provenance == "system"
    assert entity.created_at and entity.updated_at


def test_partial_unique_index_is_present(container_, user):
    import psycopg

    from server.tests.postgres_testinfra import worker_database_url

    with psycopg.connect(worker_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT array_agg(indexdef) FROM pg_indexes "
                "WHERE tablename = 'entities' AND indexdef LIKE '%WHERE is_self%'"
            )
            (defs,) = cur.fetchone()
    assert defs and any("CREATE UNIQUE INDEX" in d for d in defs)
