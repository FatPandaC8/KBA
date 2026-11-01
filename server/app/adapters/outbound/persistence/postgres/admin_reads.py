"""Admin console read/write repository (ADR R8: SQL lives in the adapter).

Backed by one connection per call (or an ambient UoW when open). Row shapes
match the previous inline queries in ``admin_console.py`` exactly.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from server.app.domain.errors import ValidationError

from .conn import Database, transaction


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresAdminRepository:
    """Data reads for the admin console plus the transcript-edit write."""

    def __init__(self, db: Database):
        self.db = db

    def _page(self, sql: str, params, limit: int, offset: int) -> Dict[str, Any]:
        with transaction(self.db) as conn:
            total = conn.execute(
                f"SELECT count(*) AS count FROM ({sql}) AS sub", tuple(params)
            ).fetchone()["count"]
            rows = conn.execute(
                f"{sql} LIMIT %s OFFSET %s", (*params, limit, offset)
            ).fetchall()
            return {
                "rows": [dict(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def overview_counts(self) -> Dict[str, Any]:
        with transaction(self.db) as conn:
            counts = {}
            for key, table in (("users", "users"), ("captures", "captures"), ("relationships", "relationships")):
                counts[key] = conn.execute(
                    f"SELECT count(*) AS count FROM {table}"
                ).fetchone()["count"]
            counts["entities"] = conn.execute(
                "SELECT count(*) AS count FROM entities WHERE is_self = FALSE"
            ).fetchone()["count"]
            return counts

    def overview_sections(self) -> Dict[str, Any]:
        with transaction(self.db) as conn:
            statuses = [
                dict(row)
                for row in conn.execute(
                    "SELECT status, count(*) AS count FROM captures "
                    "GROUP BY status ORDER BY status"
                ).fetchall()
            ]
            failures = [
                dict(row)
                for row in conn.execute(
                    "SELECT error_class, count(*) AS count FROM processing_jobs "
                    "WHERE status = 'failed' GROUP BY error_class ORDER BY count DESC"
                ).fetchall()
            ]
            recent = [
                dict(row)
                for row in conn.execute(
                    "SELECT actor, action, resource_type, outcome, created_at "
                    "FROM admin_audit_log ORDER BY created_at DESC LIMIT 8"
                ).fetchall()
            ]
            return {"capture_statuses": statuses, "processing_failures": failures, "recent_activity": recent}

    def users_page(self, q: str, limit: int, offset: int) -> Dict[str, Any]:
        term = f"%{q.strip().lower()}%"
        sql = """SELECT u.id, u.email, u.email_verified_at, u.created_at,
            (SELECT count(*) FROM captures c WHERE c.user_id = u.id) AS capture_count,
            (SELECT count(*) FROM entities e WHERE e.user_id = u.id AND e.is_self = FALSE) AS entity_count,
            (SELECT count(*) FROM relationships r WHERE r.user_id = u.id) AS relationship_count
            FROM users u WHERE lower(u.email) LIKE %s ORDER BY u.created_at DESC"""
        return self._page(sql, [term], limit, offset)

    def user_row(self, user_id: str) -> Optional[Dict[str, Any]]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT id, email, email_verified_at, created_at FROM users WHERE id = %s",
                (uuid.UUID(user_id),),
            ).fetchone()
            return dict(row) if row else None

    def user_detail_sections(self, user_id: str) -> Dict[str, Any]:
        with transaction(self.db) as conn:
            captures = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, created_at, status, duration_ms FROM captures "
                    "WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
                    (uuid.UUID(user_id),),
                ).fetchall()
            ]
            entities = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, name, entity_type, capture_id, is_self FROM entities "
                    "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                    (uuid.UUID(user_id),),
                ).fetchall()
            ]
            relationships = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, from_id, to_id, relation_type, source_capture_id "
                    "FROM relationships WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                    (uuid.UUID(user_id),),
                ).fetchall()
            ]
            return {"captures": captures, "entities": entities, "relationships": relationships}

    def captures_page(self, q: str, user_id: str, status: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if q.strip():
            clauses.append("(lower(c.id::text) LIKE %s OR lower(u.email) LIKE %s)")
            term = f"%{q.strip().lower()}%"
            params.extend([term, term])
        if user_id:
            clauses.append("c.user_id = %s")
            params.append(uuid.UUID(user_id))
        if status:
            clauses.append("coalesce(j.status, c.status) = %s")
            params.append(status)
        sql = f"""SELECT c.id::text AS capture_id, c.user_id::text AS user_id, u.email AS owner_email, c.created_at,
            c.duration_ms, c.status AS capture_status, coalesce(j.stage, c.status) AS stage,
            coalesce(j.status, c.status) AS status, j.error_class, j.error_message,
            CASE WHEN c.audio_path IS NOT NULL AND c.audio_path <> '' THEN 1 ELSE 0 END AS has_audio
            FROM captures c JOIN users u ON u.id = c.user_id
            LEFT JOIN processing_jobs j ON j.capture_id = c.id
            WHERE {' AND '.join(clauses)} ORDER BY c.created_at DESC"""
        return self._page(sql, params, limit, offset)

    def capture_detail(self, capture_id: str) -> Optional[Dict[str, Any]]:
        with transaction(self.db) as conn:
            row = conn.execute(
                """SELECT c.id::text AS capture_id, c.user_id::text AS user_id, u.email AS owner_email, c.created_at,
                    c.duration_ms, c.audio_path, c.status AS capture_status, coalesce(j.stage, c.status) AS stage,
                    coalesce(j.status, c.status) AS status, j.error_class, j.error_message
                    FROM captures c JOIN users u ON u.id = c.user_id LEFT JOIN processing_jobs j
                    ON j.capture_id = c.id WHERE c.id = %s""",
                (uuid.UUID(capture_id),),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            item = conn.execute(
                "SELECT id, transcript, title, core_idea, provenance FROM knowledge_items "
                "WHERE capture_id = %s AND user_id = %s",
                (uuid.UUID(capture_id), uuid.UUID(data["user_id"])),
            ).fetchone()
            data["knowledge_item"] = dict(item) if item else None
            data["entities"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, name, entity_type, description, confidence, certainty, capture_id "
                    "FROM entities WHERE user_id = %s AND capture_id = %s ORDER BY name",
                    (uuid.UUID(data["user_id"]), uuid.UUID(capture_id)),
                ).fetchall()
            ]
            data["relationships"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, from_id, to_id, relation_type, status, confidence, certainty, source_capture_id "
                    "FROM relationships WHERE user_id = %s AND source_capture_id = %s ORDER BY relation_type",
                    (uuid.UUID(data["user_id"]), uuid.UUID(capture_id)),
                ).fetchall()
            ]
            data["audio_path"] = bool(data.get("audio_path"))
            return data

    def update_transcript(self, capture_id: str, transcript: str) -> None:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT user_id FROM captures WHERE id = %s", (uuid.UUID(capture_id),)
            ).fetchone()
            if not row:
                raise KeyError(capture_id)
            item = conn.execute(
                "SELECT id FROM knowledge_items WHERE capture_id = %s AND user_id = %s",
                (uuid.UUID(capture_id), row["user_id"]),
            ).fetchone()
            if not item:
                raise ValidationError("This capture has no transcript record yet.")
            conn.execute(
                "UPDATE knowledge_items SET transcript = %s, updated_at = NOW() "
                "WHERE id = %s AND user_id = %s",
                (transcript.strip(), item["id"], row["user_id"]),
            )

    def graph_entities_page(self, q: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if q.strip():
            clauses.append("(lower(e.name) LIKE %s OR lower(e.description) LIKE %s)")
            params.extend([f"%{q.strip().lower()}%"] * 2)
        if user_id:
            clauses.append("e.user_id = %s")
            params.append(uuid.UUID(user_id))
        sql = f"""SELECT e.id::text, e.user_id::text AS user_id, e.name, e.entity_type, e.description,
            e.confidence, e.certainty, e.capture_id::text AS capture_id, e.created_at, e.is_self
            FROM entities e WHERE {' AND '.join(clauses)} ORDER BY e.created_at DESC"""
        return self._page(sql, params, limit, offset)

    def graph_relationships_page(self, q: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if q.strip():
            clauses.append("lower(r.relation_type) LIKE %s")
            params.append(f"%{q.strip().lower()}%")
        if user_id:
            clauses.append("r.user_id = %s")
            params.append(uuid.UUID(user_id))
        sql = f"""SELECT r.id::text, r.user_id::text AS user_id, r.from_id::text AS from_id,
            r.to_id::text AS to_id, r.relation_type, r.status, r.confidence, r.certainty,
            r.source_capture_id::text AS source_capture_id, r.created_at
            FROM relationships r WHERE {' AND '.join(clauses)} ORDER BY r.created_at DESC"""
        return self._page(sql, params, limit, offset)

    def audit_page(self, action: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if action:
            clauses.append("action = %s")
            params.append(action)
        if user_id:
            clauses.append("user_id = %s")
            params.append(uuid.UUID(user_id))
        sql = f"""SELECT id::text, actor, action, resource_type, resource_id, user_id::text AS user_id,
            outcome, detail, created_at FROM admin_audit_log
            WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"""
        return self._page(sql, params, limit, offset)


class PostgresAdminAuditLogRepository:
    """Append-only admin audit trail (U4); matches AdminAuditLogPort."""

    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        action: str,
        resource_type: str = "",
        resource_id: str = "",
        user_id: str = "",
        ip_address: str = "unknown",
        outcome: str = "success",
        detail: str = "",
        actor: str = "admin",
    ) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO admin_audit_log (id, actor, action, resource_type,
                    resource_id, user_id, ip_address, outcome, detail, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    uuid.uuid4(),
                    actor,
                    action,
                    resource_type,
                    resource_id,
                    uuid.UUID(user_id) if user_id else None,
                    ip_address,
                    outcome,
                    detail,
                ),
            )

    def list_recent(self, limit: int = 50) -> list:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT id::text AS id, actor, action, resource_type, "
                "resource_id, COALESCE(user_id::text, '') AS user_id, ip_address, "
                "outcome, detail, created_at FROM admin_audit_log "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM admin_audit_log WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            return cur.rowcount


class PostgresLLMUsageRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        *,
        user_id: str,
        provider: str,
        model: str,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        status: str = "success",
    ) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO llm_usage (id, user_id, provider_id, model, operation,
                    prompt_tokens, completion_tokens, total_tokens, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id) if user_id else None,
                    provider,
                    model,
                    operation,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    status,
                ),
            )

    def log_usage(
        self,
        user_id: str,
        provider_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: Optional[float] = None,
        operation: str = "",
        status: str = "success",
    ) -> None:
        self.record(
            user_id=user_id,
            provider=provider_id,
            model=model,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status=status,
        )

    def usage_since(self, since: str) -> Dict[str, int]:
        with transaction(self.db) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(COUNT(*), 0) AS calls, COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM llm_usage WHERE created_at >= %s
                """,
                (since,),
            ).fetchone()
            return {"calls": row["calls"] or 0, "total_tokens": int(row["total_tokens"] or 0)}

    def last_calls(self, limit: int = 10) -> list:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT * FROM llm_usage ORDER BY created_at DESC LIMIT %s", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]


class PostgresAppSettingsRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> Optional[str]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key, value),
            )

    def all(self) -> Dict[str, str]:
        with transaction(self.db) as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def delete(self, key: str) -> None:
        with transaction(self.db) as conn:
            conn.execute("DELETE FROM app_settings WHERE key = %s", (key,))
