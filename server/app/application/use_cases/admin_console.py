"""Business operations used by the admin console.

The HTTP layer only validates input and maps DTOs. All cross-table reads and
destructive operations live here so the admin UI cannot bypass ownership
scoping or the existing capture/account deletion rules.
"""

import os
import sqlite3
from typing import Any, Dict, Optional

from server.app.domain.entities import UserEntity
from server.app.security import hash_password, normalize_email, validate_password
from server.app.domain.errors import ValidationError


class AdminConsoleUseCase:
    def __init__(self, db, auth_service, user_repo, account_delete, capture_delete, process_capture, worker, upload_dir, password_min_length):
        self.db = db
        self.auth_service = auth_service
        self.user_repo = user_repo
        self.account_delete = account_delete
        self.capture_delete = capture_delete
        self.process_capture = process_capture
        self.worker = worker
        self.upload_dir = upload_dir
        self.password_min_length = password_min_length

    def _page(self, sql: str, params, limit: int, offset: int) -> Dict[str, Any]:
        conn = self.db.get_connection()
        total = conn.execute(f"SELECT count(*) AS count FROM ({sql})", tuple(params)).fetchone()["count"]
        rows = conn.execute(f"{sql} LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return {"rows": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def overview(self) -> Dict[str, Any]:
        conn = self.db.get_connection()
        counts = {}
        for key, table in (("users", "users"), ("captures", "captures"), ("entities", "entities"), ("relationships", "relationships")):
            counts[key] = conn.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]
        statuses = [dict(row) for row in conn.execute("SELECT status, count(*) AS count FROM captures GROUP BY status ORDER BY status")]
        failures = [dict(row) for row in conn.execute("SELECT error_class, count(*) AS count FROM processing_jobs WHERE status = 'failed' GROUP BY error_class ORDER BY count DESC")]
        recent = [dict(row) for row in conn.execute("SELECT actor, action, resource_type, outcome, created_at FROM admin_audit_log ORDER BY created_at DESC LIMIT 8")]
        return {"counts": counts, "capture_statuses": statuses, "processing_failures": failures, "recent_activity": recent}

    def users(self, q: str, limit: int, offset: int) -> Dict[str, Any]:
        term = f"%{q.strip().lower()}%"
        sql = """SELECT u.id, u.email, u.email_verified_at, u.created_at,
            (SELECT count(*) FROM captures c WHERE c.user_id = u.id) AS capture_count,
            (SELECT count(*) FROM entities e WHERE e.user_id = u.id) AS entity_count,
            (SELECT count(*) FROM relationships r WHERE r.user_id = u.id) AS relationship_count
            FROM users u WHERE lower(u.email) LIKE ? ORDER BY u.created_at DESC"""
        return self._page(sql, [term], limit, offset)

    def create_user(self, email: str, password: str) -> Dict[str, Any]:
        normalized = normalize_email(email)
        error = validate_password(password, self.password_min_length)
        if error:
            raise ValidationError(error)
        if self.user_repo.get_by_email(normalized):
            raise ValidationError("A user with that email already exists.")
        user = UserEntity.create(normalized, hash_password(password))
        user.email_verified_at = user.created_at
        self.user_repo.save(user)
        return self._user(user.id)

    def _user(self, user_id: str) -> Dict[str, Any]:
        row = self.db.get_connection().execute("SELECT id, email, email_verified_at, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise KeyError(user_id)
        return dict(row)

    def update_user(self, user_id: str, email: str) -> Dict[str, Any]:
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise KeyError(user_id)
        normalized = normalize_email(email)
        other = self.user_repo.get_by_email(normalized)
        if other and other.id != user_id:
            raise ValidationError("A user with that email already exists.")
        user.email = normalized
        user.email_normalized = normalized
        self.user_repo.update(user)
        return self._user(user_id)

    def user_detail(self, user_id: str) -> Dict[str, Any]:
        data = self._user(user_id)
        conn = self.db.get_connection()
        data["captures"] = [dict(row) for row in conn.execute(
            "SELECT id, created_at, status, duration_ms FROM captures WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user_id,),
        )]
        data["entities"] = [dict(row) for row in conn.execute(
            "SELECT id, name, entity_type, capture_id FROM entities WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        )]
        data["relationships"] = [dict(row) for row in conn.execute(
            "SELECT id, from_id, to_id, relation_type, source_capture_id FROM relationships WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        )]
        return data

    def delete_user(self, user_id: str) -> Dict[str, Any]:
        if not self.user_repo.get_by_id(user_id):
            raise KeyError(user_id)
        return self.account_delete.execute(user_id)

    def captures(self, q: str, user_id: str, status: str, limit: int, offset: int) -> Dict[str, Any]:
        conn = self.db.get_connection()
        clauses, params = ["1=1"], []
        if q.strip():
            clauses.append("(lower(c.id) LIKE ? OR lower(u.email) LIKE ?)")
            term = f"%{q.strip().lower()}%"
            params.extend([term, term])
        if user_id:
            clauses.append("c.user_id = ?"); params.append(user_id)
        if status:
            clauses.append("coalesce(j.status, c.status) = ?"); params.append(status)
        sql = f"""SELECT c.id AS capture_id, c.user_id, u.email AS owner_email, c.created_at,
            c.duration_ms, c.status AS capture_status, coalesce(j.stage, c.status) AS stage,
            coalesce(j.status, c.status) AS status, j.error_class, j.error_message,
            CASE WHEN c.audio_path != '' THEN 1 ELSE 0 END AS has_audio
            FROM captures c JOIN users u ON u.id = c.user_id
            LEFT JOIN processing_jobs j ON j.capture_id = c.id AND j.user_id = c.user_id
            WHERE {' AND '.join(clauses)} ORDER BY c.created_at DESC"""
        return self._page(sql, params, limit, offset)

    def capture(self, capture_id: str) -> Optional[Dict[str, Any]]:
        conn = self.db.get_connection()
        row = conn.execute("""SELECT c.id AS capture_id, c.user_id, u.email AS owner_email, c.created_at,
            c.duration_ms, c.audio_path, c.status AS capture_status, coalesce(j.stage, c.status) AS stage,
            coalesce(j.status, c.status) AS status, j.error_class, j.error_message
            FROM captures c JOIN users u ON u.id = c.user_id LEFT JOIN processing_jobs j
            ON j.capture_id = c.id AND j.user_id = c.user_id WHERE c.id = ?""", (capture_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        item = conn.execute("SELECT id, transcript, title, core_idea, provenance FROM knowledge_items WHERE capture_id = ? AND user_id = ?", (capture_id, data["user_id"])).fetchone()
        data["knowledge_item"] = dict(item) if item else None
        data["entities"] = [dict(r) for r in conn.execute("SELECT id, name, entity_type, description, confidence, certainty, capture_id FROM entities WHERE user_id = ? AND capture_id = ? ORDER BY name", (data["user_id"], capture_id))]
        data["relationships"] = [dict(r) for r in conn.execute("SELECT id, from_id, to_id, relation_type, status, confidence, certainty, source_capture_id FROM relationships WHERE user_id = ? AND source_capture_id = ? ORDER BY relation_type", (data["user_id"], capture_id))]
        data["audio_path"] = bool(data.get("audio_path"))
        return data

    def update_transcript(self, capture_id: str, transcript: str) -> Dict[str, Any]:
        conn = self.db.get_connection()
        row = conn.execute("SELECT user_id FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if not row:
            raise KeyError(capture_id)
        item = conn.execute("SELECT id FROM knowledge_items WHERE capture_id = ? AND user_id = ?", (capture_id, row["user_id"])).fetchone()
        if not item:
            raise ValidationError("This capture has no transcript record yet.")
        conn.execute("UPDATE knowledge_items SET transcript = ?, updated_at = datetime('now') WHERE id = ? AND user_id = ?", (transcript.strip(), item["id"], row["user_id"]))
        conn.commit()
        return self.capture(capture_id) or {}

    def rerun_extraction(self, capture_id: str) -> Dict[str, Any]:
        """Run the existing extractor from the saved transcript, then queue the
        normal persistence path. The pipeline owns graph mutation; this method
        never accepts entity or relationship payloads from the admin client.
        """
        capture = self.capture(capture_id)
        if not capture or not capture.get("knowledge_item"):
            raise KeyError(capture_id)
        user_id = capture["user_id"]
        transcript = capture["knowledge_item"].get("transcript") or ""
        if not transcript.strip():
            raise ValidationError("A transcript is required before extraction.")
        counts = self.process_capture.rerun_extraction_from_transcript(capture_id, user_id, transcript)
        self.process_capture.job_repo.complete(capture_id, user_id=user_id)
        result = self.capture(capture_id) or {}
        result["replacement_counts"] = counts
        return result

    def delete_capture(self, capture_id: str) -> Dict[str, Any]:
        capture = self.capture(capture_id)
        if not capture:
            raise KeyError(capture_id)
        return self.capture_delete.execute(capture_id, capture["user_id"])

    def graph_entities(self, q: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if q.strip(): clauses.append("(lower(e.name) LIKE ? OR lower(e.description) LIKE ?)"); params.extend([f"%{q.strip().lower()}%"] * 2)
        if user_id: clauses.append("e.user_id = ?"); params.append(user_id)
        return self._page(f"SELECT e.id, e.user_id, e.name, e.entity_type, e.description, e.confidence, e.certainty, e.capture_id, e.created_at FROM entities e WHERE {' AND '.join(clauses)} ORDER BY e.created_at DESC", params, limit, offset)

    def graph_relationships(self, q: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if q.strip(): clauses.append("lower(r.relation_type) LIKE ?"); params.append(f"%{q.strip().lower()}%")
        if user_id: clauses.append("r.user_id = ?"); params.append(user_id)
        return self._page(f"SELECT r.id, r.user_id, r.from_id, r.to_id, r.relation_type, r.status, r.confidence, r.certainty, r.source_capture_id, r.created_at FROM relationships r WHERE {' AND '.join(clauses)} ORDER BY r.created_at DESC", params, limit, offset)

    def audit(self, action: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if action: clauses.append("action = ?"); params.append(action)
        if user_id: clauses.append("user_id = ?"); params.append(user_id)
        return self._page(f"SELECT id, actor, action, resource_type, resource_id, user_id, outcome, detail, created_at FROM admin_audit_log WHERE {' AND '.join(clauses)} ORDER BY created_at DESC", params, limit, offset)
