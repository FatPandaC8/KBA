import json
import sqlite3
import uuid
from typing import List, Optional, Tuple, Dict, Any

from server.app.application.ports import (
    KnowledgeRepositoryPort,
    RelationshipRepositoryPort,
    EmbeddingRepositoryPort,
    CaptureRepositoryPort,
    EvalRecordRepositoryPort,
    JobStatusRepositoryPort,
    UserRepositoryPort,
    SessionRepositoryPort,
    EmailTokenRepositoryPort,
    ConsentRepositoryPort,
    TombstoneRepositoryPort,
    RecordSupportRepositoryPort,
)
from server.app.domain.entities import (
    KnowledgeItemEntity,
    RelationshipEntity,
    CaptureEntity,
    EvalRecordEntity,
    UserEntity,
    ConsentEntity,
    current_utc_iso,
)
from server.app.application.dto import GraphDataDTO, GraphNodeDTO, GraphEdgeDTO, ProcessingJobDTO
from server.app.infrastructure.database import DatabaseManager


def _scoped(column: str, user_id: Optional[str]) -> Tuple[str, List[Any]]:
    if user_id is None:
        return "", []
    return f" AND {column} = ?", [user_id]


def _where_scoped(column: str, user_id: Optional[str]) -> Tuple[str, List[Any]]:
    if user_id is None:
        return "", []
    return f" WHERE {column} = ?", [user_id]


class SqliteUserRepository(UserRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, user: UserEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO users (id, email, email_normalized, password_hash, google_sub, email_verified_at, is_locked, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.email,
                user.email_normalized,
                user.password_hash,
                user.google_sub,
                user.email_verified_at,
                1 if user.is_locked else 0,
                user.created_at,
                user.updated_at,
            ),
        )
        conn.commit()

    def _row_to_entity(self, r: sqlite3.Row) -> UserEntity:
        return UserEntity(
            id=r["id"],
            email=r["email"],
            email_normalized=r["email_normalized"],
            password_hash=r["password_hash"],
            google_sub=r["google_sub"],
            email_verified_at=r["email_verified_at"],
            is_locked=bool(r["is_locked"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def get_by_id(self, user_id: str) -> Optional[UserEntity]:
        r = self.db.get_connection().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_entity(r) if r else None

    def get_by_email(self, email_normalized: str) -> Optional[UserEntity]:
        r = self.db.get_connection().execute(
            "SELECT * FROM users WHERE email_normalized = ?", (email_normalized,)
        ).fetchone()
        return self._row_to_entity(r) if r else None

    def get_by_google_sub(self, google_sub: str) -> Optional[UserEntity]:
        r = self.db.get_connection().execute(
            "SELECT * FROM users WHERE google_sub = ?", (google_sub,)
        ).fetchone()
        return self._row_to_entity(r) if r else None

    def update(self, user: UserEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            UPDATE users
            SET email = ?, email_normalized = ?, password_hash = ?, google_sub = ?,
                email_verified_at = ?, is_locked = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                user.email,
                user.email_normalized,
                user.password_hash,
                user.google_sub,
                user.email_verified_at,
                1 if user.is_locked else 0,
                current_utc_iso(),
                user.id,
            ),
        )
        conn.commit()

    def delete(self, user_id: str) -> None:
        conn = self.db.get_connection()
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

    def count(self) -> int:
        r = self.db.get_connection().execute("SELECT count(*) AS cnt FROM users").fetchone()
        return r["cnt"] if r else 0


class SqliteSessionRepository(SessionRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create(self, user_id: str, token_hash: str, expires_at: str) -> None:
        conn = self.db.get_connection()
        now = current_utc_iso()
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (str(uuid.uuid4()), user_id, token_hash, now, expires_at, now),
        )
        conn.commit()

    def get_user_by_token_hash(self, token_hash: str) -> Optional[UserEntity]:
        r = self.db.get_connection().execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.revoked_at IS NULL
              AND s.expires_at > ? AND u.is_locked = 0
            """,
            (token_hash, current_utc_iso()),
        ).fetchone()
        if not r:
            return None
        return SqliteUserRepository(self.db)._row_to_entity(r)

    def touch(self, token_hash: str) -> None:
        conn = self.db.get_connection()
        conn.execute("UPDATE sessions SET last_used_at = ? WHERE token_hash = ?", (current_utc_iso(), token_hash))
        conn.commit()

    def revoke(self, token_hash: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (current_utc_iso(), token_hash),
        )
        conn.commit()

    def revoke_all_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (current_utc_iso(), user_id),
        )
        conn.commit()
        return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount


class SqliteEmailTokenRepository(EmailTokenRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create(self, user_id: str, purpose: str, token_hash: str, expires_at: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO email_tokens (id, user_id, purpose, token_hash, created_at, expires_at, used_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (str(uuid.uuid4()), user_id, purpose, token_hash, current_utc_iso(), expires_at),
        )
        conn.commit()

    def consume(self, token_hash: str, purpose: str) -> Optional[str]:
        conn = self.db.get_connection()
        now = current_utc_iso()
        r = conn.execute(
            """
            SELECT id, user_id FROM email_tokens
            WHERE token_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ?
            """,
            (token_hash, purpose, now),
        ).fetchone()
        if not r:
            return None
        # Single-use: the conditional update is the atomic claim.
        cur = conn.execute(
            "UPDATE email_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
            (now, r["id"]),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        return r["user_id"]

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM email_tokens WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount


class SqliteConsentRepository(ConsentRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, consent: ConsentEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO consents (id, user_id, version, providers_hash, providers_json, granted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                consent.id,
                consent.user_id,
                consent.version,
                consent.providers_hash,
                json.dumps(consent.providers),
                1 if consent.granted else 0,
                consent.created_at,
            ),
        )
        conn.commit()

    def get_latest(self, user_id: str) -> Optional[ConsentEntity]:
        r = self.db.get_connection().execute(
            "SELECT * FROM consents WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not r:
            return None
        return ConsentEntity(
            id=r["id"],
            user_id=r["user_id"],
            version=r["version"],
            providers_hash=r["providers_hash"],
            providers=json.loads(r["providers_json"] or "[]"),
            granted=bool(r["granted"]),
            created_at=r["created_at"],
        )

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM consents WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount


class SqliteTombstoneRepository(TombstoneRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add(self, user_id: str, kind: str, normalized_key: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO tombstones (id, user_id, kind, normalized_key, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), user_id, kind, normalized_key, current_utc_iso()),
        )
        conn.commit()

    def is_tombstoned(self, user_id: str, kind: str, normalized_key: str) -> bool:
        r = self.db.get_connection().execute(
            "SELECT 1 FROM tombstones WHERE user_id = ? AND kind = ? AND normalized_key = ?",
            (user_id, kind, normalized_key),
        ).fetchone()
        return r is not None

    def list_for_user(self, user_id: str) -> List[Dict[str, str]]:
        rows = self.db.get_connection().execute(
            "SELECT kind, normalized_key, created_at FROM tombstones WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [{"kind": r["kind"], "normalized_key": r["normalized_key"], "created_at": r["created_at"]} for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM tombstones WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount


class SqliteRecordSupportRepository(RecordSupportRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add(self, user_id: str, record_id: str, target_kind: str, target_id: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO record_supports (id, user_id, record_id, target_kind, target_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), user_id, record_id, target_kind, target_id, current_utc_iso()),
        )
        conn.commit()

    def list_for_record(self, user_id: str, record_id: str) -> List[Dict[str, str]]:
        rows = self.db.get_connection().execute(
            "SELECT record_id, target_kind, target_id FROM record_supports WHERE user_id = ? AND record_id = ?",
            (user_id, record_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_for_target(self, user_id: str, target_kind: str, target_id: str) -> List[Dict[str, str]]:
        rows = self.db.get_connection().execute(
            "SELECT record_id, target_kind, target_id FROM record_supports WHERE user_id = ? AND target_kind = ? AND target_id = ?",
            (user_id, target_kind, target_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_for_record(self, user_id: str, record_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM record_supports WHERE user_id = ? AND record_id = ?", (user_id, record_id))
        conn.commit()
        return cur.rowcount

    def delete_for_target(self, user_id: str, target_kind: str, target_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute(
            "DELETE FROM record_supports WHERE user_id = ? AND target_kind = ? AND target_id = ?",
            (user_id, target_kind, target_id),
        )
        conn.commit()
        return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM record_supports WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount


class SqliteKnowledgeRepository(KnowledgeRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, item: KnowledgeItemEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO knowledge_items
            (id, user_id, capture_id, title, core_idea, details, transcript, concepts, tags,
             open_questions, candidate_relations, provenance, user_edited, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                capture_id = excluded.capture_id,
                title = excluded.title,
                core_idea = excluded.core_idea,
                details = excluded.details,
                transcript = excluded.transcript,
                concepts = excluded.concepts,
                tags = excluded.tags,
                open_questions = excluded.open_questions,
                candidate_relations = excluded.candidate_relations,
                provenance = excluded.provenance,
                updated_at = excluded.updated_at
            WHERE knowledge_items.user_id = excluded.user_id
            """,
            (
                item.id,
                item.user_id,
                item.capture_id,
                item.title,
                item.core_idea,
                item.details,
                item.transcript,
                json.dumps(item.concepts),
                json.dumps(item.tags),
                json.dumps(item.open_questions),
                json.dumps(item.candidate_relations),
                item.provenance,
                1 if item.user_edited else 0,
                item.created_at,
                item.updated_at,
            ),
        )
        conn.commit()

    def get_by_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[KnowledgeItemEntity]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT * FROM knowledge_items WHERE id = ?{clause}", (item_id, *params)
        ).fetchone()
        return self._row_to_entity(r) if r else None

    def get_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[KnowledgeItemEntity]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT * FROM knowledge_items WHERE capture_id = ?{clause}", (capture_id, *params)
        ).fetchone()
        return self._row_to_entity(r) if r else None

    def get_all(self, query: str = "", limit: Optional[int] = None, offset: int = 0, user_id: Optional[str] = None) -> List[KnowledgeItemEntity]:
        sql = "SELECT * FROM knowledge_items"
        params: List[Any] = []
        conditions: List[str] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if query:
            pattern = f"%{query}%"
            conditions.append("(title LIKE ? OR core_idea LIKE ? OR transcript LIKE ? OR concepts LIKE ? OR tags LIKE ?)")
            params.extend([pattern, pattern, pattern, pattern, pattern])
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = self.db.get_connection().execute(sql, tuple(params)).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def count(self, query: str = "", user_id: Optional[str] = None) -> int:
        sql = "SELECT count(*) AS cnt FROM knowledge_items"
        params: List[Any] = []
        conditions: List[str] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if query:
            pattern = f"%{query}%"
            conditions.append("(title LIKE ? OR core_idea LIKE ? OR transcript LIKE ? OR concepts LIKE ? OR tags LIKE ?)")
            params.extend([pattern, pattern, pattern, pattern, pattern])
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        r = self.db.get_connection().execute(sql, tuple(params)).fetchone()
        return r["cnt"] if r else 0

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        rows = conn.execute(
            f"SELECT id FROM knowledge_items WHERE (id = ? OR capture_id = ?){clause}",
            (item_id, item_id, *params),
        ).fetchall()
        target_ids = [r["id"] for r in rows]
        if not target_ids:
            return
        for tid in target_ids:
            conn.execute(f"DELETE FROM knowledge_items WHERE id = ?{clause}", (tid, *params))
            conn.execute(f"DELETE FROM relationships WHERE (from_id = ? OR to_id = ?){clause}", (tid, tid, *params))
            conn.execute(f"DELETE FROM knowledge_embeddings WHERE item_id = ?{clause}", (tid, *params))
        conn.commit()

    def _row_to_entity(self, r: sqlite3.Row) -> KnowledgeItemEntity:
        return KnowledgeItemEntity(
            id=r["id"],
            capture_id=r["capture_id"],
            title=r["title"],
            core_idea=r["core_idea"],
            user_id=r["user_id"] or "",
            details=r["details"] if "details" in r.keys() and r["details"] else "",
            transcript=r["transcript"] or "",
            concepts=json.loads(r["concepts"] or "[]"),
            tags=json.loads(r["tags"] or "[]"),
            open_questions=json.loads(r["open_questions"] or "[]"),
            candidate_relations=json.loads(r["candidate_relations"] or "[]") if "candidate_relations" in r.keys() and r["candidate_relations"] else [],
            provenance=r["provenance"] or "voice-capture",
            user_edited=bool(r["user_edited"]) if "user_edited" in r.keys() else False,
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


class SqliteRelationshipRepository(RelationshipRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, rel: RelationshipEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO relationships
            (id, user_id, from_id, to_id, relation_type, status, user_edited, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rel.id, rel.user_id, rel.from_id, rel.to_id, rel.relation_type, rel.status, 1 if rel.user_edited else 0, rel.created_at),
        )
        conn.commit()

    def get_by_id(self, rel_id: str, user_id: Optional[str] = None) -> Optional[RelationshipEntity]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT * FROM relationships WHERE id = ?{clause}", (rel_id, *params)
        ).fetchone()
        if not r:
            return None
        return self._row_to_entity(r)

    def get_all(self, user_id: Optional[str] = None) -> List[RelationshipEntity]:
        where, params = _where_scoped("user_id", user_id)
        rows = self.db.get_connection().execute(f"SELECT * FROM relationships{where}", tuple(params)).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def update_status(self, rel_id: str, status: str, relation_type: Optional[str] = None, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        if relation_type:
            conn.execute(
                f"UPDATE relationships SET status = ?, relation_type = ?, user_edited = 1 WHERE id = ?{clause}",
                (status, relation_type, rel_id, *params),
            )
        else:
            conn.execute(
                f"UPDATE relationships SET status = ?, user_edited = 1 WHERE id = ?{clause}",
                (status, rel_id, *params),
            )
        conn.commit()

    def delete(self, rel_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(f"DELETE FROM relationships WHERE id = ?{clause}", (rel_id, *params))
        conn.commit()

    def get_graph(self, user_id: Optional[str] = None) -> GraphDataDTO:
        conn = self.db.get_connection()
        item_where, item_params = _where_scoped("user_id", user_id)
        rel_where, rel_params = _where_scoped("user_id", user_id)
        item_rows = conn.execute(
            f"SELECT id, title FROM knowledge_items{item_where} ORDER BY created_at DESC", tuple(item_params)
        ).fetchall()
        rel_rows = conn.execute(f"SELECT * FROM relationships{rel_where}", tuple(rel_params)).fetchall()

        nodes: List[GraphNodeDTO] = []
        coord_presets = [
            (155.0, 128.0), (45.0, 50.0), (242.0, 48.0), (250.0, 212.0),
            (35.0, 220.0), (145.0, 278.0), (80.0, 150.0), (210.0, 160.0),
        ]
        for idx, item in enumerate(item_rows):
            coord = coord_presets[idx % len(coord_presets)]
            nodes.append(GraphNodeDTO(
                id=item["id"],
                title=item["title"],
                kind="capture" if idx % 2 == 0 else "idea",
                x=coord[0],
                y=coord[1],
            ))

        node_ids = {n.id for n in nodes}
        edges: List[GraphEdgeDTO] = []
        for r in rel_rows:
            if r["from_id"] in node_ids and r["to_id"] in node_ids:
                edges.append(GraphEdgeDTO(
                    id=r["id"],
                    from_node=r["from_id"],
                    to_node=r["to_id"],
                    type=r["relation_type"],
                    status=r["status"],
                ))
        return GraphDataDTO(nodes=nodes, edges=edges)

    def count(self, user_id: Optional[str] = None) -> int:
        where, params = _where_scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT count(*) AS cnt FROM relationships{where}", tuple(params)
        ).fetchone()
        return r["cnt"] if r else 0

    def count_orphans(self, user_id: Optional[str] = None) -> int:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        r = conn.execute(
            f"""
            SELECT count(*) AS cnt FROM relationships
            WHERE (from_id NOT IN (SELECT id FROM knowledge_items)
               OR to_id NOT IN (SELECT id FROM knowledge_items)){clause}
            """,
            tuple(params),
        ).fetchone()
        return r["cnt"] if r else 0

    def _row_to_entity(self, r: sqlite3.Row) -> RelationshipEntity:
        return RelationshipEntity(
            id=r["id"],
            from_id=r["from_id"],
            to_id=r["to_id"],
            user_id=r["user_id"] or "",
            relation_type=r["relation_type"],
            status=r["status"],
            user_edited=bool(r["user_edited"]) if "user_edited" in r.keys() else False,
            created_at=r["created_at"],
        )


class SqliteEmbeddingRepository(EmbeddingRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, item_id: str, vector_bytes: bytes, user_id: str = "", model_name: str = "", dimension: int = 0) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO knowledge_embeddings (item_id, user_id, embedding, model_name, dimension, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(item_id) DO UPDATE SET
                embedding = excluded.embedding,
                model_name = excluded.model_name,
                dimension = excluded.dimension,
                updated_at = excluded.updated_at
            WHERE knowledge_embeddings.user_id = excluded.user_id
            """,
            (item_id, user_id, vector_bytes, model_name, dimension),
        )
        conn.commit()

    def get_by_item_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[bytes]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT embedding FROM knowledge_embeddings WHERE item_id = ?{clause}", (item_id, *params)
        ).fetchone()
        return r["embedding"] if r else None

    def get_all(self, user_id: Optional[str] = None) -> List[Tuple[str, bytes]]:
        where, params = _where_scoped("user_id", user_id)
        rows = self.db.get_connection().execute(
            f"SELECT item_id, embedding FROM knowledge_embeddings{where}", tuple(params)
        ).fetchall()
        return [(r["item_id"], r["embedding"]) for r in rows]

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(f"DELETE FROM knowledge_embeddings WHERE item_id = ?{clause}", (item_id, *params))
        conn.commit()

    def count(self, user_id: Optional[str] = None) -> int:
        where, params = _where_scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT count(*) AS cnt FROM knowledge_embeddings{where}", tuple(params)
        ).fetchone()
        return r["cnt"] if r else 0


class SqliteCaptureRepository(CaptureRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, capture: CaptureEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO captures (id, user_id, idempotency_key, audio_path, duration_ms, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                idempotency_key = excluded.idempotency_key,
                audio_path = excluded.audio_path,
                duration_ms = excluded.duration_ms,
                status = excluded.status
            WHERE captures.user_id = excluded.user_id
            """,
            (
                capture.id,
                capture.user_id,
                capture.idempotency_key,
                capture.audio_path,
                capture.duration_ms,
                capture.status,
                capture.created_at,
            ),
        )
        conn.commit()

    def _row_to_entity(self, r: sqlite3.Row) -> CaptureEntity:
        return CaptureEntity(
            id=r["id"],
            idempotency_key=r["idempotency_key"],
            audio_path=r["audio_path"] or "",
            user_id=r["user_id"] or "",
            duration_ms=r["duration_ms"] or 0,
            status=r["status"] or "received",
            created_at=r["created_at"],
        )

    def get_by_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[CaptureEntity]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT * FROM captures WHERE id = ?{clause}", (capture_id, *params)
        ).fetchone()
        return self._row_to_entity(r) if r else None

    def get_by_idempotency_key(self, key: str, user_id: Optional[str] = None) -> Optional[CaptureEntity]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT * FROM captures WHERE idempotency_key = ?{clause}", (key, *params)
        ).fetchone()
        return self._row_to_entity(r) if r else None

    def list_recent(self, limit: int = 50, user_id: Optional[str] = None) -> List[CaptureEntity]:
        where, params = _where_scoped("user_id", user_id)
        rows = self.db.get_connection().execute(
            f"SELECT * FROM captures{where} ORDER BY created_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_all(self, user_id: Optional[str] = None) -> List[CaptureEntity]:
        where, params = _where_scoped("user_id", user_id)
        rows = self.db.get_connection().execute(
            f"SELECT * FROM captures{where} ORDER BY created_at DESC", tuple(params)
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def delete(self, capture_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(f"DELETE FROM captures WHERE id = ?{clause}", (capture_id, *params))
        conn.commit()

    def clear_audio_path(self, capture_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(f"UPDATE captures SET audio_path = '' WHERE id = ?{clause}", (capture_id, *params))
        conn.commit()

    def count(self, user_id: Optional[str] = None) -> int:
        where, params = _where_scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT count(*) AS cnt FROM captures{where}", tuple(params)
        ).fetchone()
        return r["cnt"] if r else 0


class SqliteEvalRecordRepository(EvalRecordRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, record: EvalRecordEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO model_eval_records (id, user_id, capture_id, transcript, structured_json, user_corrected, consent_given, pipeline_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.user_id,
                record.capture_id,
                record.transcript,
                record.structured_json,
                1 if record.user_corrected else 0,
                1 if record.consent_given else 0,
                record.pipeline_version,
                record.created_at,
            ),
        )
        conn.commit()

    def get_all_consented(self, user_id: Optional[str] = None) -> List[EvalRecordEntity]:
        clause, params = _scoped("user_id", user_id)
        rows = self.db.get_connection().execute(
            f"SELECT * FROM model_eval_records WHERE consent_given = 1{clause} ORDER BY created_at DESC",
            tuple(params),
        ).fetchall()
        return [
            EvalRecordEntity(
                id=r["id"],
                capture_id=r["capture_id"],
                transcript=r["transcript"],
                structured_json=r["structured_json"],
                user_id=r["user_id"] or "",
                user_corrected=bool(r["user_corrected"]),
                consent_given=bool(r["consent_given"]),
                pipeline_version=r["pipeline_version"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def purge_unconsented(self, user_id: Optional[str] = None) -> int:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(f"DELETE FROM model_eval_records WHERE consent_given = 0{clause}", tuple(params))
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"DELETE FROM model_eval_records WHERE capture_id = ?{clause}", (capture_id, *params)
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def purge_all(self) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM model_eval_records")
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM model_eval_records WHERE user_id = ?", (user_id,))
        deleted = cur.rowcount
        conn.commit()
        return deleted


class SqliteJobStatusRepository(JobStatusRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def record_job(self, job: ProcessingJobDTO) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, user_id, capture_id, stage, status, attempt, error_class, lease_owner,
             lease_expires_at, stage_outputs, duration_ms, error_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                stage = excluded.stage,
                status = excluded.status,
                attempt = excluded.attempt,
                error_class = excluded.error_class,
                lease_owner = excluded.lease_owner,
                lease_expires_at = excluded.lease_expires_at,
                stage_outputs = excluded.stage_outputs,
                duration_ms = excluded.duration_ms,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            WHERE processing_jobs.user_id = excluded.user_id
            """,
            (
                job.id,
                job.user_id,
                job.capture_id,
                job.stage,
                job.status,
                job.attempt,
                job.error_class,
                job.lease_owner,
                job.lease_expires_at,
                job.stage_outputs,
                job.duration_ms,
                job.error_message,
                job.created_at,
                job.updated_at,
            ),
        )
        conn.commit()

    def update_job_status(self, capture_id: str, stage: str, status: str, error_message: Optional[str] = None, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(
            f"""
            UPDATE processing_jobs
            SET stage = ?, status = ?, error_message = ?, updated_at = ?
            WHERE capture_id = ?{clause}
            """,
            (stage, status, error_message, current_utc_iso(), capture_id, *params),
        )
        conn.commit()

    def get_recent_jobs(self, limit: int = 50, user_id: Optional[str] = None) -> List[ProcessingJobDTO]:
        where, params = _where_scoped("user_id", user_id)
        rows = self.db.get_connection().execute(
            f"SELECT * FROM processing_jobs{where} ORDER BY created_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
        return [self._row_to_dto(r) for r in rows]

    def get_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[ProcessingJobDTO]:
        clause, params = _scoped("user_id", user_id)
        r = self.db.get_connection().execute(
            f"SELECT * FROM processing_jobs WHERE capture_id = ?{clause} ORDER BY created_at DESC LIMIT 1",
            (capture_id, *params),
        ).fetchone()
        return self._row_to_dto(r) if r else None

    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"DELETE FROM processing_jobs WHERE capture_id = ?{clause}", (capture_id, *params)
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def _row_to_dto(self, r: sqlite3.Row) -> ProcessingJobDTO:
        return ProcessingJobDTO(
            id=r["id"],
            capture_id=r["capture_id"],
            stage=r["stage"],
            status=r["status"],
            duration_ms=r["duration_ms"] or 0,
            error_message=r["error_message"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            user_id=r["user_id"] or "",
            attempt=r["attempt"] or 0,
            error_class=r["error_class"] or "",
            lease_owner=r["lease_owner"] or "",
            lease_expires_at=r["lease_expires_at"] or "",
            stage_outputs=r["stage_outputs"] or "{}",
        )
