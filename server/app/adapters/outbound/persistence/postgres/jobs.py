"""JobQueue port implementation (R5).

State transitions live in ``app/domain/job_state.py``; this adapter stores and
schedules them. Claim uses ``FOR UPDATE SKIP LOCKED`` inside a short
transaction so two workers can never claim the same job.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from server.app.application.dto import ProcessingJobDTO

from .conn import Database, scoped_clause, scoped_where, transaction


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


class PostgresJobRepository:
    def __init__(self, db: Database):
        self.db = db

    def record_job(self, job: ProcessingJobDTO) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO processing_jobs (id, user_id, capture_id, stage, status,
                    attempt, error_class, error_message, lease_owner, lease_expires_at,
                    next_attempt_at, stage_outputs, duration_ms, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    status = EXCLUDED.status,
                    attempt = EXCLUDED.attempt,
                    error_class = EXCLUDED.error_class,
                    error_message = EXCLUDED.error_message,
                    lease_owner = EXCLUDED.lease_owner,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    next_attempt_at = EXCLUDED.next_attempt_at,
                    stage_outputs = EXCLUDED.stage_outputs,
                    duration_ms = EXCLUDED.duration_ms,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(job.id),
                    uuid.UUID(job.user_id),
                    uuid.UUID(job.capture_id) if job.capture_id else None,
                    job.stage,
                    job.status,
                    job.attempt,
                    job.error_class,
                    job.error_message,
                    job.lease_owner,
                    _parse_iso(job.lease_expires_at),
                    _parse_iso(job.next_attempt_at),
                    json.dumps(job.stage_outputs)
                    if not isinstance(job.stage_outputs, str)
                    else job.stage_outputs,
                    job.duration_ms,
                    job.created_at,
                    job.updated_at,
                ),
            )

    def claim(
        self,
        capture_id: str,
        lease_owner: str,
        lease_seconds: int,
        user_id: Optional[str] = None,
        retry_limit: int = 3,
    ) -> Optional[ProcessingJobDTO]:
        """Claim one capture's job (compatibility entry point)."""
        with transaction(self.db) as conn:
            now = _utcnow()
            expires = now + timedelta(seconds=lease_seconds)
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET lease_owner = %s, lease_expires_at = %s, status = 'running',
                    updated_at = NOW()
                WHERE capture_id = %s AND attempt < %s
                  AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                  AND (status = 'queued'
                       OR ((status = 'running') AND
                           (lease_owner = '' OR lease_expires_at < %s)))
                  {clause}
                RETURNING *
                """,
                (lease_owner, expires, uuid.UUID(capture_id), retry_limit, now, now, *params),
            )
            row = cur.fetchone()
            return _row_to_job(row) if row else None

    def claim_next(
        self,
        lease_owner: str,
        lease_seconds: int,
        retry_limit: int = 3,
    ) -> Optional[ProcessingJobDTO]:
        """FIFO claim across all jobs (R5); FOR UPDATE SKIP LOCKED."""
        with transaction(self.db) as conn:
            now = _utcnow()
            expires = now + timedelta(seconds=lease_seconds)
            cur = conn.execute(
                """
                UPDATE processing_jobs
                SET lease_owner = %s, lease_expires_at = %s, status = 'running',
                    next_attempt_at = NULL, updated_at = NOW()
                WHERE id = (
                    SELECT id FROM processing_jobs
                    WHERE status = 'queued'
                      AND attempt < %s
                      AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                      AND (lease_owner = '' OR lease_expires_at < %s)
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                (lease_owner, expires, retry_limit, now, now),
            )
            row = cur.fetchone()
            return _row_to_job(row) if row else None

    def reclaim_stale(self, retry_limit: int = 3) -> int:
        """Requeue jobs whose leases expired; each loss costs one attempt.

        The next attempt is scheduled with the domain RetryPolicy bands
        (4a); a job whose budget is spent fails terminally as ``worker_lost``.
        """
        from server.app.domain.job_state import RetryPolicy

        policy = RetryPolicy(max_attempts=retry_limit)
        # Row-aware bands: the FIRST retry (new attempt 1) uses delays[0],
        # later retries delays[1] ... (set statically; jitter only applies to
        # provider retries, reclaim backoff is deterministic for testability).
        base1, base2 = (list(policy.base_backoff_seconds) + [policy.base_backoff_seconds[-1]])[:2]
        with transaction(self.db) as conn:
            cur = conn.execute(
                """
                UPDATE processing_jobs
                SET status = CASE WHEN attempt + 1 >= %s THEN 'failed'
                                  ELSE 'queued' END,
                    attempt = attempt + 1,
                    lease_owner = '',
                    lease_expires_at = NULL,
                    next_attempt_at = CASE
                        WHEN attempt + 1 >= %s THEN NULL
                        WHEN attempt + 1 = 1 THEN
                            now() + make_interval(secs => %s::double precision)
                        ELSE now() + make_interval(secs => %s::double precision)
                        END,
                    error_class = CASE WHEN attempt + 1 >= %s THEN 'worker_lost' ELSE '' END,
                    error_message = CASE WHEN attempt + 1 >= %s
                        THEN 'Worker lost its lease before completing the job.' ELSE NULL END,
                    updated_at = NOW()
                WHERE status = 'running'
                  AND lease_owner <> '' AND lease_expires_at < NOW()
                  AND attempt + 1 <= %s
                """,
                (
                    retry_limit,
                    retry_limit,
                    base1,
                    base2,
                    retry_limit,
                    retry_limit,
                    retry_limit,
                ),
            )
            return cur.rowcount
        with transaction(self.db) as conn:
            cur = conn.execute(
                """
                UPDATE processing_jobs
                SET status = CASE WHEN attempt + 1 >= %s THEN 'failed'
                                  ELSE 'queued' END,
                    attempt = attempt + 1,
                    lease_owner = '',
                    lease_expires_at = NULL,
                    next_attempt_at = CASE WHEN attempt + 1 >= %s THEN NULL
                        ELSE to_timestamp(%s::double precision) END,
                    error_class = CASE WHEN attempt + 1 >= %s THEN 'worker_lost' ELSE '' END,
                    error_message = CASE WHEN attempt + 1 >= %s
                        THEN 'Worker lost its lease before completing the job.' ELSE NULL END,
                    updated_at = NOW()
                WHERE status = 'running'
                  AND lease_owner <> '' AND lease_expires_at < NOW()
                  AND attempt + 1 <= %s
                """,
                (
                    retry_limit,
                    retry_limit,
                    retry_gap_seconds,
                    retry_limit,
                    retry_limit,
                    retry_limit,
                ),
            )
            return cur.rowcount

    def list_resumable(self, now: str, retry_limit: int = 3) -> List[ProcessingJobDTO]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                """
                SELECT * FROM processing_jobs
                WHERE attempt < %s
                  AND status = 'queued'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
                  AND lease_owner = ''
                ORDER BY created_at, id
                LIMIT %s
                """,
                (retry_limit, max(50, retry_limit * 10)),
            ).fetchall()
            return [_row_to_job(r) for r in rows]

    def get_by_capture_id(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> Optional[ProcessingJobDTO]:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM processing_jobs WHERE capture_id = %s{clause} "
                "ORDER BY created_at DESC LIMIT 1",
                (uuid.UUID(capture_id), *params),
            ).fetchone()
            return _row_to_job(row) if row else None

    def get_recent_jobs(
        self, limit: int = 50, user_id: Optional[str] = None
    ) -> List[ProcessingJobDTO]:
        with transaction(self.db) as conn:
            clause, params = scoped_where("user_id", user_id)
            sql = f"SELECT * FROM processing_jobs{clause} ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_job(r) for r in rows]

    def save_stage_output(
        self,
        capture_id: str,
        stage: str,
        output: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> None:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            conn.execute(
                f"""
                UPDATE processing_jobs
                SET stage = %s, stage_outputs = stage_outputs || %s::jsonb, updated_at = NOW()
                WHERE capture_id = %s{clause}
                """,
                (stage, json.dumps(output), uuid.UUID(capture_id), *params),
            )

    def get_stage_outputs(self, capture_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        row_job = self.get_by_capture_id(capture_id, user_id)
        return dict(row_job.stage_outputs or {}) if row_job else {}

    def heartbeat(
        self,
        job_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        """Renew the lease for the owner of a running job."""
        with transaction(self.db) as conn:
            expires = _utcnow() + timedelta(seconds=lease_seconds)
            cur = conn.execute(
                """
                UPDATE processing_jobs SET lease_expires_at = %s, updated_at = NOW()
                WHERE id = %s AND lease_owner = %s AND status = 'running'
                    AND lease_expires_at > NOW() - INTERVAL '1 hour'
                """,
                (expires, uuid.UUID(job_id), lease_owner),
            )
            return cur.rowcount > 0

    def renew_lease(
        self,
        capture_id: str,
        lease_owner: str,
        lease_seconds: int,
        user_id: Optional[str] = None,
    ) -> bool:
        with transaction(self.db) as conn:
            expires = _utcnow() + timedelta(seconds=lease_seconds)
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs SET lease_expires_at = %s, updated_at = NOW()
                WHERE capture_id = %s AND lease_owner = %s{clause}
                """,
                (expires, uuid.UUID(capture_id), lease_owner, *params),
            )
            return cur.rowcount > 0

    def complete(self, capture_id: str, user_id: Optional[str] = None) -> None:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            conn.execute(
                f"""
                UPDATE processing_jobs
                SET status = 'ready', stage = 'completed',
                    lease_owner = '', lease_expires_at = NULL,
                    next_attempt_at = NULL, updated_at = NOW()
                WHERE capture_id = %s{clause}
                """,
                (uuid.UUID(capture_id), *params),
            )

    def fail(
        self,
        capture_id: str,
        attempt: int,
        error_class: str,
        error_message: Optional[str],
        retry_limit: int = 3,
        retry_at: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Record one failed attempt; scheduled retry or terminal failure.

        Terminal when the error class is not retryable or the retry budget
        is spent (D7: 3 attempts total). Retryable failures without an
        explicit ``retry_at`` schedule the next attempt with the domain
        RetryPolicy (30 s / 120 s +/- 20 % jitter) right here, so callers
        cannot accidentally create an immediately-claimed retry (4a)."""
        from datetime import datetime, timedelta, timezone

        from server.app.domain.job_state import (
            RetryPolicy,
            decides_terminal,
            retry_delay,
        )

        terminal = decides_terminal(error_class, attempt, RetryPolicy(max_attempts=retry_limit))
        next_attempt_at_value: Optional[str] = None
        if not terminal:
            if retry_at:
                next_attempt_at_value = _parse_iso(retry_at).isoformat()
            else:
                delta = retry_delay(attempt, RetryPolicy(max_attempts=retry_limit))
                base = datetime.now(timezone.utc)
                next_attempt = base + delta if delta else base
                next_attempt_at_value = next_attempt.isoformat()
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET attempt = %s,
                    error_class = %s,
                    error_message = %s,
                    status = CASE WHEN %s THEN 'failed' ELSE 'queued' END,
                    lease_owner = '',
                    lease_expires_at = NULL,
                    next_attempt_at = CASE WHEN %s THEN NULL
                        ELSE NULLIF(%s::text, '')::timestamptz END,
                    updated_at = NOW()
                WHERE capture_id = %s{clause}
                """,
                (
                    attempt,
                    error_class,
                    error_message,
                    terminal,
                    terminal,
                    next_attempt_at_value,
                    uuid.UUID(capture_id),
                    *params,
                ),
            )
            return terminal

    def record_attempt(
        self,
        capture_id: str,
        attempt: int,
        error_class: str,
        error_message: str,
        user_id: Optional[str] = None,
        retry_limit: int = 3,
        retry_at: Optional[str] = None,
    ) -> None:
        self.fail(
            capture_id,
            attempt,
            error_class,
            error_message,
            retry_limit=retry_limit,
            retry_at=retry_at,
            user_id=user_id,
        )

    def release(self, capture_id: str, lease_owner: str, user_id: Optional[str] = None) -> bool:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET status = 'queued', lease_owner = '', lease_expires_at = NULL, updated_at = NOW()
                WHERE capture_id = %s AND lease_owner = %s{clause}
                """,
                (uuid.UUID(capture_id), lease_owner, *params),
            )
            return cur.rowcount > 0

    def reset_for_retry(self, capture_id: str, user_id: Optional[str] = None) -> bool:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET status = 'queued', attempt = 0, stage = 'queued',
                    error_class = '', error_message = NULL,
                    lease_owner = '', lease_expires_at = NULL,
                    next_attempt_at = NULL, updated_at = NOW()
                WHERE capture_id = %s{clause}
                """,
                (uuid.UUID(capture_id), *params),
            )
            return cur.rowcount > 0

    def update_job_status(
        self,
        capture_id: str,
        stage: str,
        status: str,
        error_message: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            conn.execute(
                f"""
                UPDATE processing_jobs
                SET stage = %s, status = %s, error_message = COALESCE(%s, error_message),
                    updated_at = NOW()
                WHERE capture_id = %s{clause}
                """,
                (stage, status, error_message, uuid.UUID(capture_id), *params),
            )

    def delete_by_capture_id(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> int:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM processing_jobs WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            return cur.rowcount


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _row_to_job(r) -> ProcessingJobDTO:
    outputs = r["stage_outputs"]
    if not isinstance(outputs, str):
        outputs = json.dumps(outputs)
    return ProcessingJobDTO(
        id=str(r["id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else "",
        stage=r["stage"],
        status=r["status"],
        duration_ms=r["duration_ms"] or 0,
        error_message=r["error_message"],
        created_at=r["created_at"].isoformat() if r["created_at"] else "",
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else "",
        user_id=str(r["user_id"]),
        attempt=r["attempt"] or 0,
        error_class=r["error_class"] or "",
        lease_owner=r["lease_owner"] or "",
        lease_expires_at=_iso(r["lease_expires_at"]) or "",
        stage_outputs=outputs or "{}",
        next_attempt_at=_iso(r["next_attempt_at"]) or "",
    )
