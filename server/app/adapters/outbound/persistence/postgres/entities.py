"""Entities (graph nodes), including the atomic self-entity rule (R3)."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import psycopg.errors

from server.app.domain.entities import ExtractedEntity, normalize_key

from .conn import safe_uuid, Database, scoped_clause, scoped_where, transaction


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresEntityRepository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ self

    def get_or_create_self(
        self, user_id: str, provider_id: str = "", model_version: str = ""
    ) -> ExtractedEntity:
        """Atomic one-user-one-self upsert (ADR R3).

        ``INSERT ... ON CONFLICT (user_id) WHERE is_self DO NOTHING`` resolves
        the partial unique index race; the SELECT then returns the one winning
        row. The partial unique index stays in the schema as a safety net.
        """
        conflict = psycopg.errors.UniqueViolation
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO entities (id, user_id, capture_id, name, normalized_name,
                    entity_type, description, confidence, certainty, provenance,
                    provider_id, model_version, user_edited, is_self, created_at, updated_at)
                VALUES (%s, %s, NULL, 'Me', 'me', 'self', '', 1.0, 'confirmed',
                        'system', %s, %s, FALSE, TRUE, NOW(), NOW())
                ON CONFLICT (user_id) WHERE is_self DO NOTHING
                """,
                (uuid.uuid4(), uuid.UUID(user_id), provider_id, model_version),
            )
            row = conn.execute(
                "SELECT * FROM entities WHERE user_id = %s AND is_self LIMIT 1",
                (uuid.UUID(user_id),),
            ).fetchone()
            return _row_to_entity(row)

    def get_self_entity(self, user_id: str) -> Optional[ExtractedEntity]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE user_id = %s AND is_self LIMIT 1",
                (uuid.UUID(user_id),),
            ).fetchone()
            return _row_to_entity(row) if row else None

    # ---------------------------------------------------------- normal rows

    def save(self, entity: ExtractedEntity) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO entities (id, user_id, capture_id, name, normalized_name,
                    entity_type, description, confidence, certainty, provenance,
                    provider_id, model_version, user_edited, is_self, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = CASE WHEN entities.user_edited THEN entities.name
                                ELSE EXCLUDED.name END,
                    normalized_name = CASE WHEN entities.user_edited THEN entities.normalized_name
                                ELSE EXCLUDED.normalized_name END,
                    description = CASE WHEN entities.user_edited THEN entities.description
                                ELSE EXCLUDED.description END,
                    entity_type = EXCLUDED.entity_type,
                    confidence = EXCLUDED.confidence,
                    certainty = EXCLUDED.certainty,
                    provenance = EXCLUDED.provenance,
                    provider_id = EXCLUDED.provider_id,
                    model_version = EXCLUDED.model_version,
                    user_edited = entities.user_edited OR EXCLUDED.user_edited,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(entity.id),
                    uuid.UUID(entity.user_id),
                    uuid.UUID(entity.capture_id) if entity.capture_id else None,
                    entity.name,
                    normalize_key(entity.name),
                    entity.entity_type,
                    entity.description or "",
                    entity.confidence,
                    entity.certainty,
                    entity.provenance,
                    entity.provider_id or "",
                    entity.model_version or "",
                    bool(entity.user_edited),
                    bool(entity.is_self),
                    entity.created_at or _utcnow_iso(),
                    entity.updated_at or _utcnow_iso(),
                ),
            )

    def get_by_id(
        self, entity_id: str, user_id: Optional[str] = None
    ) -> Optional[ExtractedEntity]:
        parsed = safe_uuid(entity_id)
        if parsed is None:
            return None
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM entities WHERE id = %s{clause}",
                (parsed, *params),
            ).fetchone()
            return _row_to_entity(row) if row else None

    def get_all(
        self, user_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[ExtractedEntity]:
        where, params = scoped_where("user_id", user_id)
        sql = f"SELECT * FROM entities{where} ORDER BY created_at DESC, id"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        with transaction(self.db) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_entity(r) for r in rows]

    def list_by_capture(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> List[ExtractedEntity]:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            rows = conn.execute(
                f"SELECT * FROM entities WHERE capture_id = %s{clause} ORDER BY id",
                (uuid.UUID(capture_id), *params),
            ).fetchall()
            return [_row_to_entity(r) for r in rows]

    def find_by_normalized(
        self, user_id: str, normalized_name: str
    ) -> List[ExtractedEntity]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE user_id = %s AND normalized_name = %s "
                "ORDER BY id",
                (uuid.UUID(user_id), normalized_name),
            ).fetchall()
            return [_row_to_entity(r) for r in rows]

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM entities{where}", tuple(params)
            ).fetchone()
            return row["count"] if row else 0

    def delete(self, entity_id: str, user_id: Optional[str] = None) -> None:
        parsed = safe_uuid(entity_id)
        if parsed is None:
            return
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            conn.execute(
                f"DELETE FROM entities WHERE id = %s{clause}",
                (parsed, *params),
            )

    def update_fields(
        self,
        entity_id: str,
        user_id: str,
        name: Optional[str],
        description: Optional[str],
    ) -> bool:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM entities WHERE id = %s{clause}",
                (uuid.UUID(entity_id), *params),
            ).fetchone()
            if not row:
                return False
            new_name = row["name"] if name is None else name.strip()
            new_description = row["description"] if description is None else description.strip()
            conn.execute(
                """
                UPDATE entities
                SET name = %s, normalized_name = %s, description = %s,
                    user_edited = TRUE, updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (
                    new_name,
                    normalize_key(new_name),
                    new_description,
                    uuid.UUID(entity_id),
                    uuid.UUID(user_id),
                ),
            )
            return True

    def cleanup_orphans(self, user_id: str) -> int:
        """Delete non-self entities with no relationship endpoints (R4).

        Runs at the end of the ingest stage order inside the same transaction.
        The self entity is explicitly excluded (``is_self = FALSE``): a user's
        self node survives dedup and orphan pruning by rule, not by accident.
        """
        with transaction(self.db) as conn:
            cur = conn.execute(
                """
                DELETE FROM entities
                WHERE user_id = %s AND is_self = FALSE AND NOT EXISTS
                      (SELECT 1 FROM relationships r
                       WHERE r.user_id = entities.user_id
                         AND (r.from_id = entities.id OR r.to_id = entities.id))
                  AND NOT EXISTS
                      (SELECT 1 FROM duplicate_candidates dc
                       WHERE dc.user_id = entities.user_id
                         AND (dc.source_entity_id = entities.id
                              OR dc.target_entity_id = entities.id))
                """,
                (uuid.UUID(user_id),),
            )
            return cur.rowcount


def _row_to_entity(r) -> ExtractedEntity:
    return ExtractedEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else None,
        name=r["name"],
        entity_type=r["entity_type"],
        description=r["description"],
        confidence=r["confidence"],
        certainty=r["certainty"],
        provenance=r["provenance"],
        provider_id=r["provider_id"],
        model_version=r["model_version"],
        user_edited=r["user_edited"],
        is_self=r["is_self"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )
