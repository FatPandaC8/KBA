"""Knowledge items and their embeddings.

Embeddings target knowledge items ONLY; the FK
``knowledge_embeddings.item_id -> knowledge_items.id`` is the DB-level rule
that the pipeline embeds rows that exist inside the same transaction.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from server.app.domain.entities import KnowledgeItemEntity

from .conn import (
    Database,
    safe_uuid,
    scoped_clause,
    scoped_where,
    transaction,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresKnowledgeRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, item: KnowledgeItemEntity) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO knowledge_items (id, user_id, capture_id, title,
                    core_idea, transcript, details, concepts, tags, open_questions,
                    candidate_relations, provenance, provider_id, model_version,
                    user_edited, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    core_idea = EXCLUDED.core_idea,
                    transcript = EXCLUDED.transcript,
                    details = EXCLUDED.details,
                    concepts = EXCLUDED.concepts,
                    tags = EXCLUDED.tags,
                    open_questions = EXCLUDED.open_questions,
                    candidate_relations = EXCLUDED.candidate_relations,
                    provenance = EXCLUDED.provenance,
                    provider_id = EXCLUDED.provider_id,
                    model_version = EXCLUDED.model_version,
                    updated_at = NOW()
                WHERE knowledge_items.user_edited = FALSE
                """,
                (
                    uuid.UUID(item.id),
                    uuid.UUID(item.user_id),
                    uuid.UUID(item.capture_id) if item.capture_id else None,
                    item.title,
                    item.core_idea,
                    item.transcript,
                    item.details,
                    list(item.concepts or []),
                    list(item.tags or []),
                    list(item.open_questions or []),
                    list(item.candidate_relations or []),
                    item.provenance,
                    item.provider_id,
                    item.model_version,
                    bool(item.user_edited),
                    item.created_at,
                    item.updated_at,
                ),
            )

    def get_by_id(
        self, item_id: str, user_id: Optional[str] = None
    ) -> Optional[KnowledgeItemEntity]:
        parsed = safe_uuid(item_id)
        if parsed is None:
            return None
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM knowledge_items WHERE id = %s{clause}",
                (parsed, *params),
            ).fetchone()
            return _row_to_knowledge_item(row) if row else None

    def get_by_capture_id(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> Optional[KnowledgeItemEntity]:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM knowledge_items WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            ).fetchone()
            return _row_to_knowledge_item(row) if row else None

    def get_all(
        self,
        query: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
        user_id: Optional[str] = None,
    ) -> List[KnowledgeItemEntity]:
        where, params = scoped_where("user_id", user_id)
        if query:
            where += " AND (title ILIKE %s OR core_idea ILIKE %s OR transcript ILIKE %s)"
            params.extend([f"%{query}%"] * 3)
        sql = f"SELECT * FROM knowledge_items{where} ORDER BY created_at DESC, id"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        if offset:
            sql += " OFFSET %s"
            params.append(offset)
        with transaction(self.db) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_knowledge_item(r) for r in rows]

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        parsed = safe_uuid(item_id)
        if parsed is None:
            return
        with transaction(self.db) as conn:
            if user_id is not None:
                conn.execute(
                    "DELETE FROM knowledge_items WHERE id = %s AND user_id = %s",
                    (uuid.UUID(item_id), uuid.UUID(user_id)),
                )
            else:
                conn.execute(
                    "DELETE FROM knowledge_items WHERE id = %s", (parsed,)
                )

    def delete_by_capture_id(
        self, capture_id: str, user_id: Optional[str] = None
    ) -> int:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM knowledge_items WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            return cur.rowcount

    def count(self, query: str = "", user_id: Optional[str] = None) -> int:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            if query:
                where += " AND (title ILIKE %s OR core_idea ILIKE %s OR transcript ILIKE %s)"
                params.extend([f"%{query}%"] * 3)
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM knowledge_items{where}",
                tuple(params),
            ).fetchone()
            return row["count"] if row else 0


class PostgresEmbeddingRepository:
    """Embedding vectors (BYTEA) keyed by knowledge item."""

    def __init__(self, db: Database):
        self.db = db

    def save(
        self,
        item_id: str,
        embedding: bytes,
        user_id: str = "",
        model_name: str = "",
        dimension: int = 0,
    ) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO knowledge_embeddings (item_id, user_id, embedding,
                    model_name, dimension, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (item_id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    model_name = EXCLUDED.model_name,
                    dimension = EXCLUDED.dimension,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(item_id),
                    uuid.UUID(user_id),
                    embedding,
                    model_name,
                    dimension,
                    _utcnow_iso(),
                ),
            )

    def get(self, item_id: str, user_id: Optional[str] = None) -> Optional[bytes]:
        return self.get_by_item_id(item_id, user_id)

    def get_by_item_id(
        self, item_id: str, user_id: Optional[str] = None
    ) -> Optional[bytes]:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            row = conn.execute(
                f"SELECT embedding FROM knowledge_embeddings WHERE item_id = %s{clause}",
                (uuid.UUID(item_id), *params),
            ).fetchone()
            return row["embedding"] if row else None

    def get_all(self, user_id: Optional[str] = None) -> List[Tuple[str, bytes]]:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            rows = conn.execute(
                f"SELECT item_id, embedding FROM knowledge_embeddings{where}",
                tuple(params),
            ).fetchall()
            return [(str(r["item_id"]), r["embedding"]) for r in rows]

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        with transaction(self.db) as conn:
            clause, params = scoped_clause("user_id", user_id)
            conn.execute(
                f"DELETE FROM knowledge_embeddings WHERE item_id = %s{clause}",
                (uuid.UUID(item_id), *params),
            )

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction(self.db) as conn:
            where, params = scoped_where("user_id", user_id)
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM knowledge_embeddings{where}",
                tuple(params),
            ).fetchone()
            return row["count"] if row else 0


def _row_to_knowledge_item(r) -> KnowledgeItemEntity:
    return KnowledgeItemEntity(
        id=str(r["id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else None,
        title=r["title"],
        core_idea=r["core_idea"],
        transcript=r["transcript"],
        user_id=str(r["user_id"]),
        details=r["details"] or "",
        concepts=list(r["concepts"] or []),
        tags=list(r["tags"] or []),
        open_questions=list(r["open_questions"] or []),
        candidate_relations=list(r["candidate_relations"] or []),
        provenance=r["provenance"],
        provider_id=r["provider_id"],
        model_version=r["model_version"],
        user_edited=r["user_edited"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )
