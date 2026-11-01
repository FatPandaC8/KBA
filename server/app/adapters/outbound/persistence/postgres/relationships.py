"""Relationships (graph edges) and the relationship-type registry."""

import uuid
from typing import Any, Dict, List, Optional

from server.app.domain.entities import (
    DEFAULT_RELATIONSHIP_TYPES,
    RelationshipEntity,
    RelationshipTypeRegistryEntry,
    normalize_key,
)

from .conn import safe_uuid, Database, scoped_clause, scoped_where, transaction


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


class PostgresRelationshipRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, rel: RelationshipEntity) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO relationships (id, user_id, from_id, to_id, relation_type,
                    status, confidence, certainty, source_capture_id, provenance,
                    user_edited, evidence_utterance, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, from_id, to_id, relation_type) DO UPDATE SET
                    confidence = GREATEST(relationships.confidence, EXCLUDED.confidence),
                    certainty = CASE
                        WHEN relationships.certainty = 'conflicting'
                          OR EXCLUDED.certainty = 'conflicting'
                        THEN 'conflicting' ELSE relationships.certainty END,
                    source_capture_id = CASE
                        WHEN relationships.source_capture_id IS NULL
                        THEN EXCLUDED.source_capture_id
                        ELSE relationships.source_capture_id END,
                    evidence_utterance = CASE
                        WHEN relationships.evidence_utterance = ''
                        THEN EXCLUDED.evidence_utterance
                        ELSE relationships.evidence_utterance END,
                    status = CASE
                        WHEN relationships.user_edited THEN relationships.status
                        ELSE EXCLUDED.status END,
                    user_edited = relationships.user_edited OR EXCLUDED.user_edited
                """,
                (
                    uuid.UUID(rel.id),
                    uuid.UUID(rel.user_id),
                    uuid.UUID(rel.from_id),
                    uuid.UUID(rel.to_id),
                    rel.relation_type,
                    rel.status,
                    rel.confidence,
                    rel.certainty,
                    uuid.UUID(rel.source_capture_id) if rel.source_capture_id else None,
                    rel.provenance or "voice-capture",
                    bool(rel.user_edited),
                    (rel.evidence_utterance or "")[:280],
                    rel.created_at,
                ),
            )

    def get_by_id(
        self, rel_id: str, user_id: Optional[str] = None
    ) -> Optional[RelationshipEntity]:
        parsed = safe_uuid(rel_id)
        if parsed is None:
            return None
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM relationships WHERE id = %s{clause}",
                (parsed, *params),
            ).fetchone()
            return _row_to_relationship(row) if row else None

    def get_all(self, user_id: Optional[str] = None) -> List[RelationshipEntity]:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            rows = conn.execute(
                f"SELECT * FROM relationships{where} ORDER BY created_at DESC, id",
                tuple(params),
            ).fetchall()
            return [_row_to_relationship(r) for r in rows]

    def get_between(
        self, user_id: str, from_id: str, to_id: str
    ) -> List[RelationshipEntity]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE user_id = %s AND from_id = %s "
                "AND to_id = %s ORDER BY id",
                (uuid.UUID(user_id), uuid.UUID(from_id), uuid.UUID(to_id)),
            ).fetchall()
            return [_row_to_relationship(r) for r in rows]

    def list_for_entity(
        self, user_id: str, entity_id: str
    ) -> List[RelationshipEntity]:
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE user_id = %s "
                "AND (from_id = %s OR to_id = %s) ORDER BY id",
                (uuid.UUID(user_id), uuid.UUID(entity_id), uuid.UUID(entity_id)),
            ).fetchall()
            return [_row_to_relationship(r) for r in rows]

    def update_status(
        self,
        rel_id: str,
        status: str,
        relation_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            if relation_type:
                conn.execute(
                    f"UPDATE relationships SET status = %s, user_edited = TRUE "
                    f"WHERE id = %s AND relation_type = %s{clause}",
                    (status, uuid.UUID(rel_id), relation_type, *params),
                )
            else:
                conn.execute(
                    f"UPDATE relationships SET status = %s, user_edited = TRUE "
                    f"WHERE id = %s{clause}",
                    (status, uuid.UUID(rel_id), *params),
                )

    def delete(self, rel_id: str, user_id: Optional[str] = None) -> bool:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM relationships WHERE id = %s{clause}",
                (uuid.UUID(rel_id), *params),
            )
            return cur.rowcount > 0

    def delete_for_entity(
        self, entity_id: str, user_id: Optional[str] = None
    ) -> int:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM relationships WHERE (from_id = %s OR to_id = %s){clause}",
                (uuid.UUID(entity_id), uuid.UUID(entity_id), *params),
            )
            return cur.rowcount

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM relationships{where}", tuple(params)
            ).fetchone()
            return row["count"] if row else 0

    def count_orphans(self, user_id: Optional[str] = None) -> int:
        """Non-self entities that no longer sit on any edge."""
        with transaction(self.db) as conn:
            where, params = scoped_where("e.user_id", user_id)
            row = conn.execute(
                f"""SELECT COUNT(*) AS count FROM entities e{where}
                    WHERE e.is_self = FALSE AND NOT EXISTS
                    (SELECT 1 FROM relationships r WHERE r.user_id = e.user_id
                     AND (r.from_id = e.id OR r.to_id = e.id))""",
                tuple(params),
            ).fetchone()
            return row["count"] if row else 0

    # -------------------------------------------------------------- read side

    def read_graph_rows(self, user_id: Optional[str] = None):
        """Plain rows for the read service; layout happens in domain code.

        Returns (entity_rows, relationship_rows) as plain dicts; the
        GraphQueryService owns DTO mapping (R6: one layout implementation).
        """
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            entity_rows = [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT id, name, entity_type, certainty, confidence, is_self
                    FROM entities{where} ORDER BY created_at, id
                    """,
                    tuple(params),
                ).fetchall()
            ]
            rel_rows = [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT id, from_id, to_id, relation_type, status, certainty,
                           confidence, evidence_utterance
                    FROM relationships{where} ORDER BY created_at, id
                    """,
                    tuple(params),
                ).fetchall()
            ]
        # uuid objects -> strings for the pure domain + DTO layer
        for row in entity_rows:
            row["id"] = str(row["id"])
        for row in rel_rows:
            row["id"] = str(row["id"])
            row["from_id"] = str(row["from_id"])
            row["to_id"] = str(row["to_id"])
        return entity_rows, rel_rows


class PostgresRelationshipTypeRegistry:
    """Open-ended relationship registry (U1).

    Seed meanings live in code (``DEFAULT_RELATIONSHIP_TYPES``); the table
    holds proposals added after extraction. Matching is deterministic over
    normalized canonical names and aliases.
    """

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _seeds() -> List[RelationshipTypeRegistryEntry]:
        return list(DEFAULT_RELATIONSHIP_TYPES)

    def _user_entries(self, user_id: Optional[str]) -> List[RelationshipTypeRegistryEntry]:
        if not user_id:
            return []
        with transaction(self.db) as conn:
            rows = conn.execute(
                "SELECT * FROM relationship_types WHERE user_id = %s OR user_id IS NULL "
                "ORDER BY created_at",
                (uuid.UUID(user_id),),
            ).fetchall()
        return [_entry_from_row(r) for r in rows]

    def list_for_user(self, user_id: Optional[str] = None) -> List[RelationshipTypeRegistryEntry]:
        """Seeds first, then user entries overriding with the same key."""
        entries: Dict[str, RelationshipTypeRegistryEntry] = {}
        for entry in self._seeds():
            entries[entry.normalized_key] = entry
        for entry in self._user_entries(user_id):
            entries[entry.normalized_key] = entry
        return sorted(entries.values(), key=lambda e: e.normalized_key)

    def find_equivalent(
        self, user_id: Optional[str], names: List[str]
    ) -> Optional[RelationshipTypeRegistryEntry]:
        lookup: Dict[str, RelationshipTypeRegistryEntry] = {}
        for entry in self.list_for_user(user_id):
            keys = [entry.normalized_key, *entry.normalized_aliases]
            for key in keys:
                lookup.setdefault(key, entry)
        for name in names:
            key = self._match_key(name)
            if not key:
                continue
            hit = lookup.get(key)
            if hit is not None:
                return hit
        return None

    @staticmethod
    def _match_key(name: str) -> str:
        return normalize_key(str(name or "").replace("_", " "))

    def ensure(
        self,
        user_id: Optional[str],
        canonical_name: str,
        semantic_description: str = "",
        aliases: Optional[List[str]] = None,
        provenance: str = "extraction",
        user_edited: bool = False,
    ) -> RelationshipTypeRegistryEntry:
        existing = self.find_equivalent(user_id, [canonical_name, *(aliases or [])])
        if existing is not None:
            return existing
        entry = RelationshipTypeRegistryEntry.create(
            canonical_name=canonical_name,
            user_id=user_id or "",
            semantic_description=semantic_description,
            aliases=aliases,
            provenance=provenance,
            user_edited=user_edited,
        )
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO relationship_types
                (id, user_id, canonical_name, normalized_key, semantic_description,
                 aliases, provenance, user_edited, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, normalized_key) DO UPDATE SET
                    semantic_description = CASE
                        WHEN relationship_types.semantic_description = ''
                        THEN EXCLUDED.semantic_description
                        ELSE relationship_types.semantic_description END,
                    aliases = CASE
                        WHEN relationship_types.aliases = '{}'
                        THEN EXCLUDED.aliases
                        ELSE relationship_types.aliases END
                """,
                (
                    uuid.UUID(entry.id) if _is_uuid(entry.id) else uuid.uuid4(),
                    uuid.UUID(user_id) if user_id else None,
                    entry.canonical_name,
                    entry.normalized_key,
                    entry.semantic_description,
                    list(entry.aliases),
                    entry.provenance,
                    bool(entry.user_edited),
                ),
            )
        return entry

    def update(
        self,
        entry_id: str,
        *,
        semantic_description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> bool:
        updates: List[str] = []
        params: List[Any] = []
        if semantic_description is not None:
            updates.append("semantic_description = %s")
            params.append(" ".join(semantic_description.split()))
        if aliases is not None:
            updates.append("aliases = %s")
            params.append(list(aliases))
        if not updates:
            return False
        params.append(uuid.UUID(entry_id))
        with transaction(self.db) as conn:
            conn.execute(
                f"UPDATE relationship_types SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
        return True

    def get_or_create(
        self, user_id: str, canonical_name: str, semantic_description: str = "", aliases: List[str] = None
    ) -> Dict[str, Any]:
        entry = self.ensure(user_id, canonical_name, semantic_description, aliases)
        return {
            "canonical_name": entry.canonical_name,
            "normalized_key": entry.normalized_key,
            "semantic_description": entry.semantic_description,
            "aliases": entry.aliases,
        }


def _entry_from_row(row) -> RelationshipTypeRegistryEntry:
    return RelationshipTypeRegistryEntry(
        id=str(row["id"]),
        user_id=str(row["user_id"]) if row["user_id"] else "",
        canonical_name=row["canonical_name"],
        semantic_description=row["semantic_description"] or "",
        aliases=list(row["aliases"] or []),
        provenance=row["provenance"] if row["provenance"] else "registry-seed",
        user_edited=row["user_edited"],
        created_at=row["created_at"].isoformat() if row["created_at"] else None,
    )


def _row_to_relationship(r) -> RelationshipEntity:
    return RelationshipEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        from_id=str(r["from_id"]),
        to_id=str(r["to_id"]),
        relation_type=r["relation_type"],
        status=r["status"],
        confidence=r["confidence"],
        certainty=r["certainty"],
        # Domain + HTTP contract are non-null str (""); SQL NULL (e.g. from
        # ON DELETE SET NULL or seeded provenance-less rows) maps back to "".
        source_capture_id=str(r["source_capture_id"]) if r["source_capture_id"] else "",
        provenance=r["provenance"],
        user_edited=r["user_edited"],
        evidence_utterance=r["evidence_utterance"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
    )
