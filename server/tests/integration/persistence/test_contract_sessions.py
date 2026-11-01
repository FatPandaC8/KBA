"""SessionRepositoryPort contract (R6: conditional touch, read paths)."""

import uuid

import psycopg

from server.tests.postgres_testinfra import worker_database_url


def _session_row(token_hash: str):
    with psycopg.connect(worker_database_url(), autocommit=True, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE token_hash = %s", (token_hash,))
            return cur.fetchone()


def test_create_and_lookup(container_, user):
    token_hash = f"hash-{uuid.uuid4().hex}"
    expires = "2099-01-01T00:00:00+00:00"
    container_.session_repo.create(user.id, token_hash, expires)
    row = _session_row(token_hash)
    assert row is not None and str(row["user_id"]) == user.id
    assert row["revoked_at"] is None
    assert str(container_.session_repo.get_user_by_token_hash(token_hash).id) == user.id


def test_touch_skips_fresh_sessions_and_updates_stale_ones(container_, user):
    token_hash = f"hash-{uuid.uuid4().hex}"
    container_.session_repo.create(user.id, token_hash, "2099-01-01T00:00:00+00:00")
    # Fresh session: last_used_at was stamped at create; touch must be a no-op
    # write (predicate matches zero rows; R6).
    before = _session_row(token_hash)["last_used_at"]
    container_.session_repo.touch(token_hash)
    after = _session_row(token_hash)["last_used_at"]
    assert before is not None
    # Rewind last_used_at to make the session stale, then a touch must move it.
    with psycopg.connect(worker_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET last_used_at = NOW() - INTERVAL '5 minutes' "
                "WHERE token_hash = %s",
                (token_hash,),
            )
    stale = _session_row(token_hash)["last_used_at"]
    container_.session_repo.touch(token_hash)
    fresh = _session_row(token_hash)["last_used_at"]
    assert fresh > stale


def test_revoke_and_revoke_all(container_, user):
    h1 = f"hash-{uuid.uuid4().hex}"
    h2 = f"hash-{uuid.uuid4().hex}"
    container_.session_repo.create(user.id, h1, "2099-01-01T00:00:00+00:00")
    container_.session_repo.create(user.id, h2, "2099-01-01T00:00:00+00:00")
    container_.session_repo.revoke(h1)
    assert container_.session_repo.get_user_by_token_hash(h1) is None
    assert container_.session_repo.get_user_by_token_hash(h2) is not None
    # >= 1: the signup/login flow may have created additional sessions for the
    # user; the contract is that every live session of the user is revoked.
    assert container_.session_repo.revoke_all_for_user(user.id) >= 1
    assert container_.session_repo.get_user_by_token_hash(h2) is None


def test_expired_sessions_do_not_authenticate(container_, user):
    token_hash = f"hash-{uuid.uuid4().hex}"
    container_.session_repo.create(user.id, token_hash, "2000-01-01T00:00:00+00:00")
    assert container_.session_repo.get_user_by_token_hash(token_hash) is None
