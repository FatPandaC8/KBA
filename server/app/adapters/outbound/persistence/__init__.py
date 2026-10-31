import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Any

from server.app.application.ports import (
    KnowledgeRepositoryPort,
    EntityRepositoryPort,
    RelationshipRepositoryPort,
    RelationshipTypeRegistryPort,
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
    LLMUsageRepositoryPort,
    AppSettingsRepositoryPort,
    AdminAuditLogPort,
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
    RelationshipTypeRegistryEntry,
    DEFAULT_RELATIONSHIP_TYPES,
    CaptureEntity,
    EvalRecordEntity,
    UserEntity,
    ConsentEntity,
    current_utc_iso,
    normalize_key,
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
        rel_keys = rel.keys()
        edges.append(GraphEdgeDTO(
            id=rel["id"],
            from_node=rel["from_id"],
            to_node=rel["to_id"],
            type=rel["relation_type"],
            status=rel["status"],
            certainty=rel["certainty"] if "certainty" in rel_keys and rel["certainty"] else "confirmed",
            confidence=float(rel["confidence"]) if "confidence" in rel_keys and rel["confidence"] is not None else 0.6,
            evidence=(rel["evidence_utterance"] or "") if "evidence_utterance" in rel_keys else "",
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
              AND knowledge_items.user_edited = 0
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
             certainty, source_capture_id, provenance, user_edited,
             evidence_utterance, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                evidence_utterance = CASE
                    WHEN relationships.evidence_utterance = ''
                    THEN excluded.evidence_utterance
                    ELSE relationships.evidence_utterance END,
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
                (rel.evidence_utterance or "")[:280],
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
            evidence_utterance=(r["evidence_utterance"] or "") if "evidence_utterance" in keys else "",
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

    def claim(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None, retry_limit: int = 3) -> Optional[ProcessingJobDTO]:
        """Atomically take the lease for one job.

        A job is claimable when it is queued, or when a running/processing
        worker's lease has expired. Expired leases are how a restarted backend
        resumes work without the client triggering anything (PRC-03).
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
              AND attempt < ?
              AND (
                    status = 'queued'
                 OR (status IN ('running', 'processing')
                     AND (lease_owner = '' OR lease_expires_at < ?))
              ){clause}
            """,
            (lease_owner, expires, now, capture_id, int(retry_limit), now, *params),
        )
        conn.commit()
        if not cur.rowcount:
            return None
        return self.get_by_capture_id(capture_id, user_id=user_id)

    def renew_lease(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None) -> bool:
        """Extend a lease held by this worker; never steal another worker's job."""
        conn = self.db.get_connection()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        clause, params = _scoped("user_id", user_id)
        cur = conn.execute(
            f"""
            UPDATE processing_jobs
            SET lease_expires_at = ?, updated_at = ?
            WHERE capture_id = ? AND lease_owner = ?{clause}
            """,
            (expires, current_utc_iso(), capture_id, lease_owner, *params),
        )
        conn.commit()
        return bool(cur.rowcount)

    def complete(self, capture_id: str, user_id: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        conn.execute(
            f"""
            UPDATE processing_jobs
            SET stage = 'completed', status = 'ready', error_class = '', error_message = NULL,
                lease_owner = '', lease_expires_at = '', updated_at = ?
            WHERE capture_id = ?{clause}
            """,
            (current_utc_iso(), capture_id, *params),
        )
        conn.commit()

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
        # Keep the lease: the worker is still alive and may be in a long
        # provider call. The heartbeat renews it; only failure/completion
        # releases it. Status "processing" is still resumable when its lease
        # expires, so a crash cannot strand a job forever.
        status = "ready" if stage == "completed" else "processing"
        conn.execute(
            f"""
            UPDATE processing_jobs
            SET stage = ?, status = ?, stage_outputs = ?, error_message = NULL,
                error_class = '', updated_at = ?
            WHERE capture_id = ?{clause}
            """,
            (stage, status, json.dumps(existing), current_utc_iso(), capture_id, *params),
        )
        conn.commit()

    def record_attempt(self, capture_id: str, attempt: int, error_class: str, error_message: str, user_id: Optional[str] = None, retry_limit: int = 3) -> None:
        conn = self.db.get_connection()
        clause, params = _scoped("user_id", user_id)
        status = "failed" if attempt >= retry_limit or not ErrorClass.is_recoverable(error_class) else "queued"
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

    def list_resumable(self, now_iso: str, limit: int = 20, retry_limit: int = 3) -> List[ProcessingJobDTO]:
        rows = self.db.get_connection().execute(
            """
            SELECT * FROM processing_jobs
            WHERE attempt < ?
              AND (
                    status = 'queued'
                 OR (status IN ('running', 'processing')
                     AND (lease_owner = '' OR lease_expires_at < ?))
              )
            ORDER BY created_at
            LIMIT ?
            """,
            (int(retry_limit), now_iso, limit),
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


class SqliteLLMUsageRepository(LLMUsageRepositoryPort):
    """Token accounting for provider calls (TPM/TPD budgets and admin views)."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

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
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO llm_usage
            (id, user_id, provider, model, operation, prompt_tokens,
             completion_tokens, total_tokens, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                user_id or "",
                provider,
                model,
                operation,
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int(total_tokens or 0),
                status,
                current_utc_iso(),
            ),
        )
        conn.commit()

    def usage_since(self, since_iso: str, user_id: Optional[str] = None) -> Dict[str, int]:
        sql = (
            "SELECT count(*) AS calls, COALESCE(sum(total_tokens), 0) AS total_tokens "
            "FROM llm_usage WHERE created_at >= ?"
        )
        params: List[Any] = [since_iso]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        row = self.db.get_connection().execute(sql, tuple(params)).fetchone()
        return {
            "calls": int(row["calls"] if row else 0),
            "total_tokens": int(row["total_tokens"] if row else 0),
        }

    def last_calls(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.db.get_connection().execute(
            "SELECT provider, model, operation, prompt_tokens, completion_tokens, "
            "total_tokens, status, created_at FROM llm_usage ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


class SqliteAppSettingsRepository(AppSettingsRepositoryPort):
    """Small runtime key/value store for admin-selectable provider/model."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get(self, key: str) -> Optional[str]:
        row = self.db.get_connection().execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, current_utc_iso()),
        )
        conn.commit()

    def all(self) -> Dict[str, str]:
        rows = self.db.get_connection().execute("SELECT key, value FROM app_settings").fetchall()
        return {row["key"]: row["value"] for row in rows}


class SqliteRelationshipTypeRegistryRepository(RelationshipTypeRegistryPort):
    """Persisted rows of the open-ended relationship registry (U1).

    Seed meanings live in code (``DEFAULT_RELATIONSHIP_TYPES``); this table
    holds proposals made after extraction user edits. Matching is
    deterministic: normalized canonical names and aliases.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _seeds() -> List[RelationshipTypeRegistryEntry]:
        return list(DEFAULT_RELATIONSHIP_TYPES)

    def _user_entries(self, user_id: Optional[str]) -> List[RelationshipTypeRegistryEntry]:
        if not user_id:
            return []
        rows = self.db.get_connection().execute(
            "SELECT * FROM relationship_types WHERE user_id = ? OR user_id = '' ORDER BY created_at",
            (user_id,),
        ).fetchall()
        entries = []
        for r in rows:
            try:
                aliases = json.loads(r["aliases_json"] or "[]")
            except (TypeError, ValueError):
                aliases = []
            entries.append(
                RelationshipTypeRegistryEntry(
                    id=r["id"],
                    user_id=r["user_id"],
                    canonical_name=r["canonical_name"],
                    semantic_description=r["semantic_description"] or "",
                    aliases=aliases if isinstance(aliases, list) else [],
                    provenance=r["provenance"] or "registry",
                    user_edited=bool(r["user_edited"]),
                    created_at=r["created_at"] or "",
                    updated_at=r["updated_at"] or "",
                )
            )
        return entries

    # -------------------------------------------------------------------- port
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
        # Underscores and casing are not meaning-bearing in registry keys, so
        # "works_at", "works at" and "Works at" all match one entry.
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
        existing = self.find_equivalent(
            user_id, [canonical_name, *(aliases or [])]
        )
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
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO relationship_types
            (id, user_id, canonical_name, normalized_key, semantic_description,
             aliases_json, provenance, user_edited, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, normalized_key) DO UPDATE SET
                semantic_description = CASE
                    WHEN relationship_types.semantic_description = ''
                    THEN excluded.semantic_description
                    ELSE relationship_types.semantic_description END,
                aliases_json = CASE
                    WHEN relationship_types.aliases_json = '[]'
                    THEN excluded.aliases_json
                    ELSE relationship_types.aliases_json END,
                updated_at = excluded.updated_at
            """,
            (
                entry.id,
                entry.user_id,
                entry.canonical_name,
                entry.normalized_key,
                entry.semantic_description,
                json.dumps(entry.aliases),
                entry.provenance,
                1 if entry.user_edited else 0,
                entry.created_at,
                entry.updated_at,
            ),
        )
        conn.commit()
        return entry

    def update(
        self,
        entry_id: str,
        *,
        semantic_description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> bool:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT id FROM relationship_types WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return False
        if semantic_description is not None:
            conn.execute(
                "UPDATE relationship_types SET semantic_description = ?, updated_at = ? WHERE id = ?",
                (" ".join(semantic_description.split()), current_utc_iso(), entry_id),
            )
        if aliases is not None:
            cleaned = json.dumps(
                RelationshipTypeRegistryEntry.create(
                    canonical_name="placeholder", aliases=aliases
                ).aliases
            )
            conn.execute(
                "UPDATE relationship_types SET aliases_json = ?, updated_at = ? WHERE id = ?",
                (cleaned, current_utc_iso(), entry_id),
            )
        conn.commit()
        return True


class SqliteAdminAuditLogRepository(AdminAuditLogPort):
    """Append-only audit log for administrative operations (U4).

    One shared admin token is the actor identity; there is no fingerprinting
    and no per-admin attribution beyond the request IP when it is available.
    No secret material is ever written to a row.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

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
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO admin_audit_log
            (id, actor, action, resource_type, resource_id, user_id,
             ip_address, outcome, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                actor,
                action,
                resource_type,
                resource_id,
                user_id,
                ip_address or "unknown",
                outcome,
                " ".join((detail or "").split()),
                current_utc_iso(),
            ),
        )
        conn.commit()

    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        rows = self.db.get_connection().execute(
            """
            SELECT id, actor, action, resource_type, resource_id, user_id,
                   ip_address, outcome, detail, created_at
            FROM admin_audit_log
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        conn = self.db.get_connection()
        cur = conn.execute(
            "DELETE FROM admin_audit_log WHERE user_id = ? AND user_id != ''",
            (user_id,),
        )
        conn.commit()
        return cur.rowcount or 0
