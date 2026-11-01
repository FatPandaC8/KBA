"""Graph bookkeeping: duplicate candidates, tombstones, record supports."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from server.app.domain.entities import normalize_key

from .conn import Database, scoped_clause, transaction


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresDuplicateRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        user_id: str,
        source_entity_id: str,
        target_entity_id: str,
        score: float,
        decision: str = "pending",
    ) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO duplicate_candidates (id, user_id, source_entity_id,
                    target_entity_id, score, decision, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, source_entity_id, target_entity_id) DO UPDATE SET
                    score = GREATEST(duplicate_candidates.score, EXCLUDED.score),
                    decision = CASE
                        WHEN duplicate_candidates.decision = 'auto_linked'
                             AND EXCLUDED.decision = 'flagged' THEN 'flagged'
                        ELSE duplicate_candidates.decision END
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    uuid.UUID(source_entity_id),
                    uuid.UUID(target_entity_id),
                    score,
                    decision,
                    _utcnow_iso(),
                ),
            )

    def list_flagged(self, user_id: str) -> List[Dict[str, Any]]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                """
                SELECT dc.*, e1.name AS source_name, e2.name AS target_name
                FROM duplicate_candidates dc
                JOIN entities e1 ON dc.source_entity_id = e1.id
                JOIN entities e2 ON dc.target_entity_id = e2.id
                WHERE dc.user_id = %s AND dc.decision = 'flagged'
                ORDER BY dc.created_at DESC
                """,
                (uuid.UUID(user_id),),
            ).fetchall()
            return [
                {
                    "source_entity_id": str(r["source_entity_id"]),
                    "target_entity_id": str(r["target_entity_id"]),
                    "source_name": r["source_name"],
                    "target_name": r["target_name"],
                    "score": r["score"],
                    "decision": r["decision"],
                    "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]

    def decide(
        self,
        user_id: str,
        source_entity_id: str,
        target_entity_id: str,
        decision: str,
    ) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                UPDATE duplicate_candidates
                SET decision = %s, decided_at = NOW()
                WHERE user_id = %s AND source_entity_id = %s AND target_entity_id = %s
                """,
                (
                    decision,
                    uuid.UUID(user_id),
                    uuid.UUID(source_entity_id),
                    uuid.UUID(target_entity_id),
                ),
            )

    def delete_for_entity(
        self, entity_id: str, user_id: Optional[str] = None
    ) -> int:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM duplicate_candidates "
                f"WHERE source_entity_id = %s OR target_entity_id = %s{clause}",
                (uuid.UUID(entity_id), uuid.UUID(entity_id), *params),
            )
            return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM duplicate_candidates WHERE user_id = %s",
                (uuid.UUID(user_id),),
            )
            return cur.rowcount


class PostgresTombstoneRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, user_id: str, kind: str, normalized_key: str) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO tombstones (id, user_id, target_kind, target_name, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, target_kind, target_name) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    kind,
                    normalized_key,
                    _utcnow_iso(),
                ),
            )

    def is_tombstoned(self, user_id: str, kind: str, normalized_key: str) -> bool:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT 1 FROM tombstones WHERE user_id = %s AND target_kind = %s "
                "AND target_name = %s",
                (uuid.UUID(user_id), kind, normalized_key),
            ).fetchone()
            return row is not None

    def list_for_user(self, user_id: str) -> List[Dict[str, str]]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT target_kind, target_name FROM tombstones WHERE user_id = %s "
                "ORDER BY created_at DESC",
                (uuid.UUID(user_id),),
            ).fetchall()
            return [
                {"kind": r["target_kind"], "normalized_key": r["target_name"]}
                for r in rows
            ]

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM tombstones WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            return cur.rowcount


class PostgresSupportRepository:
    """Capture ↔ graph-record support index (otherwise-orphans share nodes)."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, user_id: str, record_id: str, target_kind: str, target_id: str) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO record_supports (id, record_id, target_kind, target_id, user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (record_id, target_kind, target_id) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(record_id),
                    target_kind,
                    uuid.UUID(target_id),
                    uuid.UUID(user_id),
                    _utcnow_iso(),
                ),
            )

    def list_for_record(self, user_id: str, record_id: str) -> List[Dict[str, str]]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT target_kind, target_id FROM record_supports "
                "WHERE user_id = %s AND record_id = %s",
                (uuid.UUID(user_id), uuid.UUID(record_id)),
            ).fetchall()
            return [
                {"target_kind": r["target_kind"], "target_id": str(r["target_id"])}
                for r in rows
            ]

    def list_for_target(
        self, user_id: str, target_kind: str, target_id: str
    ) -> List[str]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT record_id FROM record_supports WHERE user_id = %s "
                "AND target_kind = %s AND target_id = %s",
                (uuid.UUID(user_id), target_kind, uuid.UUID(target_id)),
            ).fetchall()
            return [str(r["record_id"]) for r in rows]

    def delete_for_record(self, user_id: str, record_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM record_supports WHERE user_id = %s AND record_id = %s",
                (uuid.UUID(user_id), uuid.UUID(record_id)),
            )
            return cur.rowcount

    def delete_for_target(
        self, user_id: str, target_kind: str, target_id: str
    ) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM record_supports WHERE user_id = %s AND target_kind = %s "
                "AND target_id = %s",
                (uuid.UUID(user_id), target_kind, uuid.UUID(target_id)),
            )
            return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM record_supports WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            return cur.rowcount
