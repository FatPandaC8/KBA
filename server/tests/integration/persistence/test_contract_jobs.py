"""JobQueuePort contract (R5 + D7 scheduling round-trip)."""

import time

from ._helpers import make_capture, make_job


def _job_row(container_, capture_id, user_id):
    return container_.job_repo.get_by_capture_id(capture_id, user_id=user_id)


def test_record_claim_complete_cycle(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    job = make_job(user.id, capture.id)
    container_.job_repo.record_job(job)

    claimed = container_.job_repo.claim(capture.id, "worker-a", 300)
    assert claimed is not None and claimed.status == "running"
    assert claimed.lease_owner == "worker-a"

    # A second claim from another owner must not steal a live lease.
    assert container_.job_repo.claim(capture.id, "worker-b", 300) is None

    container_.job_repo.complete(capture.id, user_id=user.id)
    row = _job_row(container_, capture.id, user.id)
    assert row.status == "ready"
    assert row.lease_owner == ""


def test_fail_schedules_retry_until_retry_limit(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    job = make_job(user.id, capture.id)
    container_.job_repo.record_job(job)
    container_.job_repo.claim(capture.id, "worker-a", 300)

    retry_at = "2099-01-01T00:00:01+00:00"
    terminal = container_.job_repo.fail(
        capture.id, 1, "network_error", "boom", retry_limit=3, retry_at=retry_at
    )
    assert terminal is False
    row = _job_row(container_, capture.id, user.id)
    assert row.status == "queued"
    assert row.attempt == 1
    assert row.next_attempt_at == retry_at
    assert row.lease_owner == ""

    container_.job_repo.fail(
        capture.id, 3, "network_error", "boom again", retry_limit=3
    )
    row = _job_row(container_, capture.id, user.id)
    assert row.status == "failed"
    assert row.next_attempt_at == ""


def test_claim_respects_next_attempt_schedule(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id))
    container_.job_repo.claim(capture.id, "worker-a", 300)
    # Retry scheduled in the future: not claimable right now.
    container_.job_repo.fail(
        capture.id, 1, "network_error", "boom",
        retry_limit=3, retry_at="2099-01-01T00:00:01+00:00",
    )
    assert container_.job_repo.claim(capture.id, "worker-b", 300) is None
    # A past schedule reopens the job.
    container_.job_repo.fail(
        capture.id, 1, "network_error", "boom",
        retry_limit=3, retry_at="2000-01-01T00:00:00+00:00",
    )
    claimed = container_.job_repo.claim(capture.id, "worker-b", 300)
    assert claimed is not None


def test_claim_next_is_exclusive_between_workers(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id))

    first = container_.job_repo.claim_next("worker-a", 300)
    second = container_.job_repo.claim_next("worker-b", 300)
    assert first is not None
    assert first.id != second.id if second else True


def test_reclaim_stale_costs_an_attempt_and_eventually_fails(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id))
    container_.job_repo.claim(capture.id, "lost-worker", 300)

    # Simulate the lease expiring.
    import psycopg

    from server.tests.postgres_testinfra import worker_database_url

    with psycopg.connect(worker_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE processing_jobs SET lease_expires_at = NOW() - INTERVAL '5 minutes' "
                "WHERE capture_id = %s",
                (capture.id,),
            )
    affected = container_.job_repo.reclaim_stale(retry_limit=3)
    assert affected == 1
    row = _job_row(container_, capture.id, user.id)
    assert row.status == "queued" and row.attempt == 1

    # Repeat until the budget is exhausted: terminate instead of looping.
    for attempt in range(2, 4):
        container_.job_repo.claim(capture.id, "lost-worker", 300)
        with psycopg.connect(worker_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE processing_jobs SET lease_expires_at = NOW() - INTERVAL '5 minutes' "
                    "WHERE capture_id = %s",
                    (capture.id,),
                )
        container_.job_repo.reclaim_stale(retry_limit=3)
    row = _job_row(container_, capture.id, user.id)
    assert row.status == "failed" and row.attempt == 3


def test_heartbeat_renews_only_the_owner(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id))
    claimed = container_.job_repo.claim(capture.id, "worker-a", 300)
    assert container_.job_repo.heartbeat(claimed.id, "worker-b", 300) is False
    assert container_.job_repo.heartbeat(claimed.id, "worker-a", 300) is True


def test_capture_id_focused_claim_and_release(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id))
    assert container_.job_repo.claim(capture.id, "worker-a", 300) is not None
    assert container_.job_repo.release(capture.id, "worker-b") is False
    assert container_.job_repo.release(capture.id, "worker-a") is True
    row = _job_row(container_, capture.id, user.id)
    assert row.status == "queued" and row.lease_owner == ""


def test_save_stage_output_merges_into_jsonb(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id))
    container_.job_repo.save_stage_output(capture.id, "extract", {"transcript": "hi"})
    container_.job_repo.save_stage_output(capture.id, "save", {"saved": True})
    row = _job_row(container_, capture.id, user.id)
    import json

    outputs = json.loads(row.stage_outputs)
    assert outputs == {"transcript": "hi", "saved": True}
