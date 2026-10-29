import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Any

from server.app.application.ports import (
    KnowledgeRepositoryPort,
    EntityRepositoryPort,
    RelationshipRepositoryPort,
    DuplicateCandidateRepositoryPort,
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
    ConversationRepositoryPort,
    MessageRepositoryPort,
    CitationRepositoryPort,
)
from server.app.application.dto import (
    GraphDataDTO,
    GraphNodeDTO,
    GraphEdgeDTO,
    GraphClusterDTO,
    ProcessingJobDTO,
)
from server.app.domain.entities import (
    KnowledgeItemEntity,
    ExtractedEntity,
    RelationshipEntity,
    CaptureEntity,
    EvalRecordEntity,
    UserEntity,
    ConsentEntity,
    ConversationEntity,
    MessageEntity,
    CitationEntity,
    current_utc_iso,
)
from server.app.domain.value_objects import ErrorClass
from server.app.infrastructure.database import DatabaseManager


def _scoped(column: str, user_id: Optional[str]) -> Tuple[str, List[Any]]:
    if user_id is None:
        return "", []
    return f" AND {column} = ?", [user_id]


def _where_scoped(column: str, user_id: Optional[str]) -> Tuple[str, List[Any]]:
    if user_id is None:
        return "", []
    return f" WHERE {column} = ?", [user_id]


_TYPE_PLURALS = {
    "person": "People",
    "project": "Projects",
    "organization": "Organizations",
    "place": "Places",
    "concept": "Concepts",
    "tool": "Tools",
    "idea": "Ideas",
}


def _plural_label(entity_type: str) -> str:
    return _TYPE_PLURALS.get((entity_type or "concept").lower(), "Concepts")


def _layout_graph(entity_rows, rel_rows) -> Tuple[List[GraphNodeDTO], List[GraphEdgeDTO], List[GraphClusterDTO]]:
    """Deterministic community detection and layout for the graph canvas.

    Label propagation runs over the entity graph. Unconnected nodes are grouped
    by entity type so a sparse graph still renders as readable clusters. Output
    is stable for the same data set, which keeps client-side caches valid.
    """
    entity_ids = [row["id"] for row in entity_rows]
    entity_by_id = {row["id"]: row for row in entity_rows}

    adjacency: Dict[str, set] = {eid: set() for eid in entity_ids}
    valid_edges: List[Any] = []
    for rel in rel_rows:
        source, target = rel["from_id"], rel["to_id"]
        if source in entity_by_id and target in entity_by_id and source != target:
            adjacency[source].add(target)
            adjacency[target].add(source)
            valid_edges.append(rel)

    labels: Dict[str, str] = {eid: eid for eid in entity_ids}
    # At most 8 passes keeps this linear-ish for the 2,000-node budget.
    for _ in range(8):
        changed = False
        for eid in entity_ids:
            neighbours = adjacency[eid]
            if not neighbours:
                continue
            counts: Dict[str, int] = {}
            for neighbour in neighbours:
                label = labels[neighbour]
                counts[label] = counts.get(label, 0) + 1
            best_label = min(counts.items(), key=lambda item: (-item[1], item[0]))[0]
            if counts[best_label] > counts.get(labels[eid], 0):
                labels[eid] = best_label
                changed = True
        if not changed:
            break

    members: Dict[str, List[str]] = {}
    for eid in entity_ids:
        if adjacency[eid]:
            members.setdefault(f"community:{labels[eid]}", []).append(eid)
        else:
            row = entity_by_id[eid]
            members.setdefault(f"type:{(row['entity_type'] or 'concept').lower()}", []).append(eid)

    ordered = sorted(members.items(), key=lambda item: (-len(item[1]), item[0]))
    total = max(1, len(ordered))
    clusters: List[GraphClusterDTO] = []
    positions: Dict[str, Tuple[float, float]] = {}

    for index, (key, ids) in enumerate(ordered):
        angle = (2 * 3.141592653589793 * index) / total
        ring = 0.0 if total == 1 else 330.0
        cx = 500.0 + ring * _cos(angle)
        cy = 500.0 + ring * _sin(angle)
        if key.startswith("type:"):
            label = _plural_label(key.split(":", 1)[1])
        else:
            type_counts: Dict[str, int] = {}
            for eid in ids:
                etype = (entity_by_id[eid]["entity_type"] or "concept").lower()
                type_counts[etype] = type_counts.get(etype, 0) + 1
            dominant = max(sorted(type_counts.items()), key=lambda item: item[1])[0]
            label = _plural_label(dominant)
        clusters.append(GraphClusterDTO(id=key, label=label, x=cx, y=cy, size=len(ids)))
        for member_index, eid in enumerate(sorted(ids)):
            if len(ids) == 1:
                px, py = cx, cy
            else:
                # Golden-angle spiral keeps dense communities separated.
                radius = min(215.0, 14.0 * (member_index + 1) ** 0.5)
                theta = member_index * 2.399963229728653
                px = cx + radius * _cos(theta)
                py = cy + radius * _sin(theta)
            positions[eid] = (round(px, 2), round(py, 2))

    degree: Dict[str, int] = {eid: len(adjacency[eid]) for eid in entity_ids}
    cluster_for: Dict[str, str] = {}
    for key, ids in members.items():
        for eid in ids:
            cluster_for[eid] = key

    nodes: List[GraphNodeDTO] = []
    for eid in entity_ids:
        row = entity_by_id[eid]
        x, y = positions.get(eid, (500.0, 500.0))
        nodes.append(GraphNodeDTO(
            id=eid,
            title=row["name"],
            kind=row["entity_type"] or "concept",
            x=x,
            y=y,
            cluster_id=cluster_for.get(eid, ""),
            certainty=row["certainty"] if "certainty" in row.keys() and row["certainty"] else "confirmed",
            confidence=float(row["confidence"]) if "confidence" in row.keys() and row["confidence"] is not None else 0.5,
            degree=degree.get(eid, 0),
        ))

    edges: List[GraphEdgeDTO] = []
    for rel in valid_edges:
        edges.append(GraphEdgeDTO(
            id=rel["id"],
            from_node=rel["from_id"],
            to_node=rel["to_id"],
            type=rel["relation_type"],
            status=rel["status"],
            certainty=rel["certainty"] if "certainty" in rel.keys() and rel["certainty"] else "confirmed",
            confidence=float(rel["confidence"]) if "confidence" in rel.keys() and rel["confidence"] is not None else 0.6,
        ))
    return nodes, edges, clusters


def _cos(value: float) -> float:
    import math

    return math.cos(value)


def _sin(value: float) -> float:
    import math

    return math.sin(value)


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
             open_questions, candidate_relations, provenance, user_edited, provider_id,
             model_version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                provider_id = excluded.provider_id,
                model_version = excluded.model_version,
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
                item.provider_id,
                item.model_version,
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
            provider_id=r["provider_id"] if "provider_id" in r.keys() and r["provider_id"] else "",
            model_version=r["model_version"] if "model_version" in r.keys() and r["model_version"] else "",
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
            INSERT INTO relationships
            (id, user_id, from_id, to_id, relation_type, status, confidence,
             certainty, source_capture_id, provenance, user_edited, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, from_id, to_id, relation_type) DO UPDATE SET
                confidence = MAX(relationships.confidence, excluded.confidence),
                certainty = CASE
                    WHEN relationships.certainty = 'conflicting'
                      OR excluded.certainty = 'conflicting' THEN 'conflicting'
                    ELSE relationships.certainty END,
                source_capture_id = CASE
                    WHEN relationships.source_capture_id = ''
                    THEN excluded.source_capture_id
                    ELSE relationships.source_capture_id END,
                status = CASE
                    WHEN relationships.user_edited = 1 THEN relationships.status
                    ELSE excluded.status END
            """,
            (
                rel.id,
                rel.user_id,
                rel.from_id,
                rel.to_id,
                rel.relation_type,
                rel.status,
                rel.confidence,
                rel.certainty,
                rel.source_capture_id,
                rel.provenance,
                1 if rel.user_edited else 0,
                rel.created_at,
            ),
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

    def get_between(self, user_id: str, from_id: str, to_id: str) -> List[RelationshipEntity]:
        rows = self.db.get_connection().execute(
            """
            SELECT * FROM relationships
            WHERE user_id = ?
              AND ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
            """,
            (user_id, from_id, to_id, to_id, from_id),
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_for_entity(self, user_id: str, entity_id: str) -> List[RelationshipEntity]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM relationships WHERE user_id = ? AND (from_id = ? OR to_id = ?)",
            (user_id, entity_id, entity_id),
        ).fetchall()
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

    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> int:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"DELETE FROM relationships WHERE (from_id = ? OR to_id = ?){clause}",
            (entity_id, entity_id, *params),
        )
        conn.commit()
        return cur.rowcount or 0

    def get_graph(self, user_id: Optional[str] = None) -> GraphDataDTO:
        """Build a clustered graph payload (KG-04).

        Communities are detected server-side with deterministic label
        propagation. Coordinates are assigned here so the client only renders
        and applies level-of-detail; it never re-derives the layout.
        """
        conn = self.db.get_connection()
        entity_where, entity_params = _where_scoped("user_id", user_id)
        rel_where, rel_params = _where_scoped("user_id", user_id)
        entity_rows = conn.execute(
            f"""
            SELECT id, name, entity_type, certainty, confidence
            FROM entities{entity_where}
            ORDER BY id
            """,
            tuple(entity_params),
        ).fetchall()
        rel_rows = conn.execute(f"SELECT * FROM relationships{rel_where}", tuple(rel_params)).fetchall()

        nodes, edges, clusters = _layout_graph(entity_rows, rel_rows)
        return GraphDataDTO(nodes=nodes, edges=edges, clusters=clusters)

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
            WHERE (from_id NOT IN (SELECT id FROM entities)
               OR to_id NOT IN (SELECT id FROM entities)){clause}
            """,
            tuple(params),
        ).fetchone()
        return r["cnt"] if r else 0

    def _row_to_entity(self, r: sqlite3.Row) -> RelationshipEntity:
        keys = r.keys()
        return RelationshipEntity(
            id=r["id"],
            from_id=r["from_id"],
            to_id=r["to_id"],
            user_id=r["user_id"] or "",
            relation_type=r["relation_type"],
            status=r["status"],
            certainty=r["certainty"] if "certainty" in keys and r["certainty"] else "confirmed",
            confidence=float(r["confidence"]) if "confidence" in keys and r["confidence"] is not None else 0.6,
            source_capture_id=r["source_capture_id"] if "source_capture_id" in keys and r["source_capture_id"] else "",
            provenance=r["provenance"] if "provenance" in keys and r["provenance"] else "voice-capture",
            user_edited=bool(r["user_edited"]) if "user_edited" in keys else False,
            created_at=r["created_at"],
        )


class SqliteEntityRepository(EntityRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, entity: ExtractedEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO entities
            (id, user_id, capture_id, name, normalized_name, entity_type, description,
             confidence, certainty, provenance, provider_id, model_version,
             user_edited, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = CASE WHEN entities.user_edited = 1 THEN entities.name ELSE excluded.name END,
                normalized_name = CASE WHEN entities.user_edited = 1 THEN entities.normalized_name ELSE excluded.normalized_name END,
                description = CASE WHEN entities.user_edited = 1 THEN entities.description ELSE excluded.description END,
                entity_type = excluded.entity_type,
                confidence = MAX(entities.confidence, excluded.confidence),
                certainty = CASE
                    WHEN entities.certainty = 'conflicting'
                      OR excluded.certainty = 'conflicting' THEN 'conflicting'
                    ELSE excluded.certainty END,
                provider_id = excluded.provider_id,
                model_version = excluded.model_version,
                updated_at = excluded.updated_at
            WHERE entities.user_id = excluded.user_id
            """,
            (
                entity.id,
                entity.user_id,
                entity.capture_id,
                entity.name,
                entity.normalized_name,
                entity.entity_type,
                entity.description,
                entity.confidence,
                entity.certainty,
                entity.provenance,
                entity.provider_id,
                entity.model_version,
                1 if entity.user_edited else 0,
                entity.created_at,
                entity.updated_at,
            ),
        )
        conn.commit()

    def get_by_id(self, entity_id: str, user_id: Optional[str] = None) -> Optional[ExtractedEntity]:
        clause, params = _scoped("user_id", user_id)
        row = self.db.get_connection().execute(
            f"SELECT * FROM entities WHERE id = ?{clause}", (entity_id, *params)
        ).fetchone()
        return self._row_to_entity(row) if row else None

    def get_all(self, user_id: Optional[str] = None, limit: Optional[int] = None) -> List[ExtractedEntity]:
        where, params = _where_scoped("user_id", user_id)
        sql = f"SELECT * FROM entities{where} ORDER BY created_at DESC, id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.db.get_connection().execute(sql, tuple(params)).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_by_capture(self, capture_id: str, user_id: Optional[str] = None) -> List[ExtractedEntity]:
        clause, params = _scoped("user_id", user_id)
        rows = self.db.get_connection().execute(
            f"SELECT * FROM entities WHERE capture_id = ?{clause} ORDER BY id", (capture_id, *params)
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def find_by_normalized(self, user_id: str, normalized_name: str) -> List[ExtractedEntity]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM entities WHERE user_id = ? AND normalized_name = ? ORDER BY id",
            (user_id, normalized_name),
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def count(self, user_id: Optional[str] = None) -> int:
        where, params = _where_scoped("user_id", user_id)
        row = self.db.get_connection().execute(
            f"SELECT count(*) AS cnt FROM entities{where}", tuple(params)
        ).fetchone()
        return row["cnt"] if row else 0

    def delete(self, entity_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(f"DELETE FROM entities WHERE id = ?{clause}", (entity_id, *params))
        conn.commit()

    def update_fields(self, entity_id: str, user_id: str, name: Optional[str], description: Optional[str]) -> bool:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM entities WHERE id = ? AND user_id = ?", (entity_id, user_id)
        ).fetchone()
        if not row:
            return False
        new_name = row["name"] if name is None else name.strip()
        new_description = row["description"] if description is None else description.strip()
        from server.app.domain.entities import normalize_key

        conn.execute(
            """
            UPDATE entities
            SET name = ?, normalized_name = ?, description = ?, user_edited = 1, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (new_name, normalize_key(new_name), new_description, current_utc_iso(), entity_id, user_id),
        )
        conn.commit()
        return True

    def _row_to_entity(self, r: sqlite3.Row) -> ExtractedEntity:
        return ExtractedEntity(
            id=r["id"],
            user_id=r["user_id"] or "",
            capture_id=r["capture_id"] or "",
            name=r["name"],
            entity_type=r["entity_type"] or "concept",
            description=r["description"] or "",
            confidence=float(r["confidence"]) if r["confidence"] is not None else 0.5,
            certainty=r["certainty"] or "confirmed",
            provenance=r["provenance"] or "voice-capture",
            provider_id=r["provider_id"] or "",
            model_version=r["model_version"] or "",
            user_edited=bool(r["user_edited"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


class SqliteDuplicateCandidateRepository(DuplicateCandidateRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def record(self, user_id: str, entity_id: str, candidate_id: str, score: float, decision: str) -> None:
        conn = self.db.get_connection()
        if entity_id > candidate_id:
            entity_id, candidate_id = candidate_id, entity_id
        conn.execute(
            """
            INSERT INTO duplicate_candidates
            (id, user_id, entity_id, candidate_id, score, decision, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, entity_id, candidate_id) DO UPDATE SET
                score = MAX(duplicate_candidates.score, excluded.score),
                decision = excluded.decision
            """,
            (str(uuid.uuid4()), user_id, entity_id, candidate_id, float(score), decision, current_utc_iso()),
        )
        conn.commit()

    def list_flagged(self, user_id: str) -> List[Dict[str, Any]]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM duplicate_candidates WHERE user_id = ? AND decision = 'flagged' ORDER BY score DESC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> int:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"DELETE FROM duplicate_candidates WHERE (entity_id = ? OR candidate_id = ?){clause}",
            (entity_id, entity_id, *params),
        )
        conn.commit()
        return cur.rowcount or 0

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM duplicate_candidates WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount or 0


class SqliteConversationRepository(ConversationRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, conversation: ConversationEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO conversations (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at
            WHERE conversations.user_id = excluded.user_id
            """,
            (conversation.id, conversation.user_id, conversation.title,
             conversation.created_at, conversation.updated_at),
        )
        conn.commit()

    def get_by_id(self, conversation_id: str, user_id: str) -> Optional[ConversationEntity]:
        row = self.db.get_connection().execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
        ).fetchone()
        if not row:
            return None
        return ConversationEntity(
            id=row["id"], user_id=row["user_id"], title=row["title"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_for_user(self, user_id: str) -> List[ConversationEntity]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
        ).fetchall()
        return [ConversationEntity(
            id=r["id"], user_id=r["user_id"], title=r["title"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        ) for r in rows]

    def touch(self, conversation_id: str, user_id: str, title: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        if title is None:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (current_utc_iso(), conversation_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ?, title = ? WHERE id = ? AND user_id = ?",
                (current_utc_iso(), title, conversation_id, user_id),
            )
        conn.commit()

    def delete(self, conversation_id: str, user_id: str) -> None:
        conn = self.db.get_connection()
        conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id))
        conn.commit()

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount or 0


class SqliteMessageRepository(MessageRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, message: MessageEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO messages
            (id, conversation_id, user_id, role, content, status, error_class,
             error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content = excluded.content,
                status = excluded.status,
                error_class = excluded.error_class,
                error_message = excluded.error_message
            WHERE messages.user_id = excluded.user_id
            """,
            (message.id, message.conversation_id, message.user_id, message.role,
             message.content, message.status, message.error_class,
             message.error_message, message.created_at),
        )
        conn.commit()

    def list_for_conversation(self, conversation_id: str, user_id: str) -> List[MessageEntity]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM messages WHERE conversation_id = ? AND user_id = ? ORDER BY created_at, id",
            (conversation_id, user_id),
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def get_by_id(self, message_id: str, user_id: str) -> Optional[MessageEntity]:
        row = self.db.get_connection().execute(
            "SELECT * FROM messages WHERE id = ? AND user_id = ?", (message_id, user_id)
        ).fetchone()
        return self._row_to_entity(row) if row else None

    def delete(self, message_id: str, user_id: str) -> None:
        conn = self.db.get_connection()
        conn.execute("DELETE FROM messages WHERE id = ? AND user_id = ?", (message_id, user_id))
        conn.commit()

    def delete_for_conversation(self, conversation_id: str, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute(
            "DELETE FROM messages WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.commit()
        return cur.rowcount or 0

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount or 0

    def _row_to_entity(self, r: sqlite3.Row) -> MessageEntity:
        return MessageEntity(
            id=r["id"], conversation_id=r["conversation_id"], user_id=r["user_id"],
            role=r["role"], content=r["content"], status=r["status"],
            error_class=r["error_class"] or "", error_message=r["error_message"] or "",
            created_at=r["created_at"],
        )


class SqliteCitationRepository(CitationRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, citation: CitationEntity) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO answer_citations
            (id, message_id, user_id, kind, target_id, name_snapshot, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (citation.id, citation.message_id, citation.user_id, citation.kind,
             citation.target_id, citation.name_snapshot, citation.created_at),
        )
        conn.commit()

    def list_for_message(self, message_id: str, user_id: str) -> List[CitationEntity]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM answer_citations WHERE message_id = ? AND user_id = ? ORDER BY created_at, id",
            (message_id, user_id),
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_for_target(self, user_id: str, kind: str, target_id: str) -> List[CitationEntity]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM answer_citations WHERE user_id = ? AND kind = ? AND target_id = ?",
            (user_id, kind, target_id),
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def delete_for_message(self, message_id: str, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute(
            "DELETE FROM answer_citations WHERE message_id = ? AND user_id = ?",
            (message_id, user_id),
        )
        conn.commit()
        return cur.rowcount or 0

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute("DELETE FROM answer_citations WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount or 0

    def _row_to_entity(self, r: sqlite3.Row) -> CitationEntity:
        return CitationEntity(
            id=r["id"], message_id=r["message_id"], user_id=r["user_id"],
            kind=r["kind"], target_id=r["target_id"],
            name_snapshot=r["name_snapshot"] or "", created_at=r["created_at"],
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

    def claim(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None) -> Optional[ProcessingJobDTO]:
        """Atomically take the lease for one job.

        A job is claimable when it is queued, or when a running worker's lease
        has expired. Expired leases are how a restarted backend resumes work
        without the client triggering anything (PRC-03).
        """
        conn = self.db.get_connection()
        now = current_utc_iso()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"""
            UPDATE processing_jobs
            SET lease_owner = ?, lease_expires_at = ?, status = 'running', updated_at = ?
            WHERE capture_id = ?
              AND attempt < 3
              AND (
                    status = 'queued'
                 OR (status = 'running' AND (lease_owner = '' OR lease_expires_at < ?))
              ){clause}
            """,
            (lease_owner, expires, now, capture_id, now, *params),
        )
        conn.commit()
        if not cur.rowcount:
            return None
        return self.get_by_capture_id(capture_id, user_id=user_id)

    def release(self, capture_id: str, lease_owner: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(
            f"""
            UPDATE processing_jobs
            SET lease_owner = '', lease_expires_at = '', updated_at = ?
            WHERE capture_id = ? AND lease_owner = ?{clause}
            """,
            (current_utc_iso(), capture_id, lease_owner, *params),
        )
        conn.commit()

    def save_stage_output(self, capture_id: str, stage: str, outputs: Dict[str, Any], user_id: Optional[str] = None) -> None:
        """Merge a stage result and advance the stage in one transaction.

        Completed stage outputs are the idempotency cache: a resumed job reuses
        them instead of re-running the provider (PRC-04).
        """
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        row = conn.execute(
            f"SELECT stage_outputs FROM processing_jobs WHERE capture_id = ?{clause} ORDER BY created_at DESC LIMIT 1",
            (capture_id, *params),
        ).fetchone()
        if not row:
            return
        try:
            existing = json.loads(row["stage_outputs"] or "{}")
        except (TypeError, ValueError):
            existing = {}
        existing.update(outputs or {})
        status = "ready" if stage == "completed" else "processing"
        conn.execute(
            f"""
            UPDATE processing_jobs
            SET stage = ?, status = ?, stage_outputs = ?, error_message = NULL,
                error_class = '', lease_owner = '', lease_expires_at = '', updated_at = ?
            WHERE capture_id = ?{clause}
            """,
            (stage, status, json.dumps(existing), current_utc_iso(), capture_id, *params),
        )
        conn.commit()

    def record_attempt(self, capture_id: str, attempt: int, error_class: str, error_message: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        status = "failed" if attempt >= 3 or not ErrorClass.is_recoverable(error_class) else "queued"
        conn.execute(
            f"""
            UPDATE processing_jobs
            SET attempt = ?, error_class = ?, error_message = ?, status = ?,
                lease_owner = '', lease_expires_at = '', updated_at = ?
            WHERE capture_id = ?{clause}
            """,
            (attempt, error_class, error_message, status, current_utc_iso(), capture_id, *params),
        )
        conn.commit()

    def reset_for_retry(self, capture_id: str, user_id: Optional[str] = None) -> bool:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"""
            UPDATE processing_jobs
            SET status = 'queued', attempt = 0, error_class = '', error_message = NULL,
                lease_owner = '', lease_expires_at = '', updated_at = ?
            WHERE capture_id = ? AND status = 'failed'{clause}
            """,
            (current_utc_iso(), capture_id, *params),
        )
        conn.commit()
        return bool(cur.rowcount)

    def list_resumable(self, now_iso: str, limit: int = 20) -> List[ProcessingJobDTO]:
        rows = self.db.get_connection().execute(
            """
            SELECT * FROM processing_jobs
            WHERE attempt < 3
              AND (
                    status = 'queued'
                 OR (status = 'running' AND (lease_owner = '' OR lease_expires_at < ?))
              )
            ORDER BY created_at
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [self._row_to_dto(r) for r in rows]

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
