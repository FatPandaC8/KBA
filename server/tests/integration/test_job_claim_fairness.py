"""Bug #5 regression tests (real Postgres, real adapter, no mocks): the worker
claim query must only claim QUEUED jobs.

Before the fix, claim_next had no status filter, so a COMPLETED job
(attempt stays 0, lease cleared) was re-claimed and re-processed forever, and
jobs created after it were starved (the FIFO cursor never advanced)."""

import pytest


@pytest.fixture()
def repo():
    from server.tests.postgres_testinfra import truncate_schema

    truncate_schema()
    from server.app.api.dependencies import get_container

    return get_container().job_repo


@pytest.fixture()
def user_id():
    import uuid

    from server.app.api.dependencies import get_container
    from server.app.domain.entities import UserEntity
    from server.app.security import hash_password
    from server.app.domain.entities import current_utc_iso

    container = get_container()
    user = UserEntity(
        id=str(uuid.uuid4()),
        email=f"claim-{uuid.uuid4().hex[:8]}@example.com",
        email_normalized="",
        password_hash=hash_password("EchoTest1234"),
        email_verified_at=current_utc_iso(),
    )
    container.user_repo.save(user)
    return user.id


def _record(repo, user_id, *, status="queued", stage="upload", attempt=0,
            error_class=""):
    import uuid

    from server.app.api.dependencies import get_container
    from server.app.domain.entities import (
        CaptureEntity,
        ProcessingJobDTO,
        current_utc_iso,
    )
    from server.app.domain.value_objects import JobStage, JobStatus

    container = get_container()
    now = current_utc_iso()
    cid = str(uuid.uuid4())
    capture = CaptureEntity(
        id=cid,
        idempotency_key=f"claim-{cid}",
        audio_path="",
        user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    container.capture_repo.save(capture)
    dto = ProcessingJobDTO(
        id=cid,
        capture_id=cid,
        user_id=user_id,
        stage=stage,
        status=status,
        attempt=attempt,
        error_class=error_class,
        lease_owner="",
        lease_expires_at=None,
        stage_outputs={},
        duration_ms=1000,
        error_message=None,
        created_at=now,
        updated_at=now,
        next_attempt_at=None,
    )
    repo.record_job(dto)
    JobStatus.QUEUED  # keep the stage/status constants referenced
    return cid


def test_completed_job_is_never_claimable(repo, user_id):
    from server.app.domain.value_objects import JobStage

    cid = _record(repo, user_id)
    repo.save_stage_output(cid, JobStage.COMPLETED, {"saved": True}, user_id=user_id)
    repo.complete(cid, user_id=user_id)

    assert repo.claim_next("w1", 300, 3) is None, "completed job was re-claimed"


def test_failed_job_is_never_claimable(repo, user_id):
    cid = _record(repo, user_id)
    job = repo.claim_next("w1", 300, 3)
    assert job and job.capture_id == cid
    repo.fail(cid, attempt=1, error_class="invalid_input",
              error_message="Test terminal failure.", retry_limit=3, user_id=user_id)

    assert repo.claim_next("w2", 300, 3) is None, "failed job was re-claimed"


def test_queued_after_completed_is_claimed_no_starvation(repo, user_id):
    """Bug #5 starvation: the queue must reach jobs created AFTER a completed
    one (before the fix the completed job was always the oldest claimable)."""
    from server.app.domain.value_objects import JobStage

    old_cid = _record(repo, user_id)
    repo.save_stage_output(old_cid, JobStage.COMPLETED, {"saved": True}, user_id=user_id)
    repo.complete(old_cid, user_id=user_id)

    later_cid = _record(repo, user_id)

    claimed = repo.claim_next("w1", 300, 3)
    assert claimed is not None
    assert claimed.capture_id == later_cid, (
        f"starved: claimed {claimed.capture_id} instead of the queued {later_cid}"
    )


def test_two_workers_never_claim_the_same_job(repo, user_id):
    cid = _record(repo, user_id)
    first = repo.claim_next("w1", 300, 3)
    assert first and first.capture_id == cid
    second = repo.claim_next("w2", 300, 3)
    assert second is None, "second worker stole the leased job"


def test_reclaim_stale_takes_only_running_jobs_with_expired_lease(repo, user_id):
    import time as _t

    cid = _record(repo, user_id)
    assert repo.claim_next("w1", 1, 3) is not None  # 1-second lease

    import psycopg
    from server.tests.postgres_testinfra import MAINTENANCE_DSN

    _t.sleep(1.2)
    with psycopg.connect(MAINTENANCE_DSN, dbname="echo_kb") as conn:
        conn.execute(
            "UPDATE processing_jobs SET lease_expires_at = now() - interval '5 seconds'"
            " WHERE capture_id = %s",
            (cid,),
        )
        conn.commit()

    assert repo.reclaim_stale(3) == 1
    job = repo.get_by_capture_id(cid, user_id=user_id)
    assert job.status == "queued", job.status

    # hygiene: park this job so later tests never see it claimable
    repo.fail(cid, attempt=1, error_class="invalid_input",
              error_message="cleanup", retry_limit=3, user_id=user_id)
