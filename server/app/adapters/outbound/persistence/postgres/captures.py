"""Captures and model-evaluation records."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from server.app.domain.entities import CaptureEntity, EvalRecordEntity

from .conn import safe_uuid, Database, scoped_clause, scoped_where, transaction


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresCaptureRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, capture: CaptureEntity) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO captures (id, user_id, audio_path, duration_ms, status,
                    stage, error_class, error_message, retry_count, user_edited_title,
                    user_edited_summary, knowledge_item_id, has_audio, audio_on_server,
                    idempotency_key, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    audio_path = EXCLUDED.audio_path,
                    duration_ms = EXCLUDED.duration_ms,
                    status = EXCLUDED.status,
                    stage = EXCLUDED.stage,
                    error_class = EXCLUDED.error_class,
                    error_message = EXCLUDED.error_message,
                    retry_count = EXCLUDED.retry_count,
                    user_edited_title = EXCLUDED.user_edited_title,
                    user_edited_summary = EXCLUDED.user_edited_summary,
                    knowledge_item_id = EXCLUDED.knowledge_item_id,
                    has_audio = EXCLUDED.has_audio,
                    audio_on_server = EXCLUDED.audio_on_server,
                    idempotency_key = EXCLUDED.idempotency_key,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(capture.id),
                    uuid.UUID(capture.user_id),
                    capture.audio_path,
                    capture.duration_ms,
                    capture.status,
                    capture.stage,
                    capture.error_class,
                    capture.error_message,
                    capture.retry_count,
                    capture.user_edited_title,
                    capture.user_edited_summary,
                    uuid.UUID(capture.knowledge_item_id) if capture.knowledge_item_id else None,
                    capture.has_audio,
                    capture.audio_on_server,
                    capture.idempotency_key,
                    capture.created_at,
                    capture.updated_at,
                ),
            )

    def mark_error(self, capture_id: str, user_id: Optional[str] = None,
                   *, error_text: str) -> None:
        """Rule 5 (pipeline split): store the last ingest failure on the
        capture row in its OWN small transaction (the ingest UoW rollback has
        already happened when this runs)."""
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            conn.execute(
                f"""
                UPDATE captures
                SET last_error = %s,
                    last_error_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s{clause}
                """,
                (error_text[:1000], uuid.UUID(capture_id), *params),
            )

    def get_by_id(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> Optional[CaptureEntity]:
        parsed = safe_uuid(capture_id)
        if parsed is None:
            return None
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM captures WHERE id = %s{clause}",
                (parsed, *params),
            ).fetchone()
            return _row_to_capture(row) if row else None

    def get_by_idempotency_key(
        self, key: str, user_id: Optional[str] = None
    ) -> Optional[CaptureEntity]:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM captures WHERE idempotency_key = %s{clause}",
                (key, *params),
            ).fetchone()
            return _row_to_capture(row) if row else None

    def get_all(
        self,
        user_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[CaptureEntity]:
        sql, params = _all_query(user_id, limit, offset)
        with transaction(self.db) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_capture(r) for r in rows]

    def list_recent(
        self, limit: int = 50, user_id: Optional[str] = None
    ) -> List[CaptureEntity]:
        where, params = scoped_where("user_id", user_id)
        sql = f"SELECT * FROM captures{where} ORDER BY created_at DESC, id LIMIT %s"
        params.append(limit)
        with transaction(self.db) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_capture(r) for r in rows]

    def list_all(self, user_id: Optional[str] = None) -> List[CaptureEntity]:
        sql, params = _all_query(user_id, None, 0)
        with transaction(self.db) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_capture(r) for r in rows]

    def delete(self, capture_id: str, user_id: str) -> bool:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM captures WHERE id = %s AND user_id = %s",
                (uuid.UUID(capture_id), uuid.UUID(user_id)),
            )
            return cur.rowcount > 0

    def clear_audio_path(self, capture_id: str, user_id: str) -> bool:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "UPDATE captures SET audio_path = NULL, has_audio = FALSE "
                "WHERE id = %s AND user_id = %s",
                (uuid.UUID(capture_id), uuid.UUID(user_id)),
            )
            return cur.rowcount > 0

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM captures{where}", tuple(params)
            ).fetchone()
            return row["count"] if row else 0


class PostgresEvalRecordRepository:
    """Model evaluation records (captured consent-gated transcripts)."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, record: EvalRecordEntity) -> None:
        structured = record.structured_json
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO model_eval_records (id, user_id, capture_id, transcript,
                    structured_json, user_corrected, consent_given, pipeline_version, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.UUID(record.id),
                    uuid.UUID(record.user_id),
                    uuid.UUID(record.capture_id) if record.capture_id else None,
                    record.transcript,
                    structured,
                    bool(record.user_corrected),
                    bool(record.consent_given),
                    record.pipeline_version,
                    record.created_at,
                ),
            )

    def get_all_consented(self, user_id: Optional[str] = None) -> List[EvalRecordEntity]:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            rows = conn.execute(
                f"SELECT * FROM model_eval_records WHERE consent_given{where} "
                "ORDER BY created_at DESC",
                tuple(params),
            ).fetchall()
            return [_row_to_eval(r) for r in rows]

    def purge_unconsented(self, user_id: Optional[str] = None) -> int:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM model_eval_records WHERE NOT consent_given{where}",
                tuple(params),
            )
            return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM model_eval_records WHERE user_id = %s",
                (uuid.UUID(user_id),),
            )
            return cur.rowcount

    def delete_by_capture_id(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> int:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM model_eval_records WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            return cur.rowcount

    def purge_all(self) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute("DELETE FROM model_eval_records")
            return cur.rowcount


def _all_query(
    user_id: Optional[str], limit: Optional[int], offset: int
) -> Tuple[str, List[Any]]:
    where, params = scoped_where("user_id", user_id)
    sql = f"SELECT * FROM captures{where} ORDER BY created_at DESC, id"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    if offset:
        sql += " OFFSET %s"
        params.append(offset)
    return sql, params


def _row_to_eval(r) -> EvalRecordEntity:
    structured = r["structured_json"]
    if isinstance(structured, (dict, list)):
        import json as _json

        structured = _json.dumps(structured)
    return EvalRecordEntity(
        id=str(r["id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else None,
        transcript=r["transcript"] or "",
        structured_json=structured or "",
        user_id=str(r["user_id"]) if r["user_id"] else "",
        user_corrected=bool(r["user_corrected"]),
        consent_given=bool(r["consent_given"]),
        pipeline_version=r["pipeline_version"] or "",
        created_at=r["created_at"].isoformat() if r["created_at"] else "",
    )


def _row_to_capture(r) -> CaptureEntity:    return CaptureEntity(
        id=str(r["id"]),
        idempotency_key=r["idempotency_key"],
        user_id=str(r["user_id"]),
        audio_path=r["audio_path"],
        duration_ms=r["duration_ms"],
        status=r["status"],
        stage=r["stage"],
        error_class=r["error_class"],
        error_message=r["error_message"],
        retry_count=r["retry_count"],
        user_edited_title=r["user_edited_title"],
        user_edited_summary=r["user_edited_summary"],
        knowledge_item_id=str(r["knowledge_item_id"]) if r["knowledge_item_id"] else None,
        has_audio=r["has_audio"],
        audio_on_server=r["audio_on_server"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )
