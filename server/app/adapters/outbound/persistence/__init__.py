import json
from typing import List, Optional, Tuple, Dict, Any
from server.app.application.ports import (
    KnowledgeRepositoryPort,
    RelationshipRepositoryPort,
    EmbeddingRepositoryPort,
    CaptureRepositoryPort,
    EvalRecordRepositoryPort,
    JobStatusRepositoryPort,
)
from server.app.domain.entities import (
    KnowledgeItemEntity,
    RelationshipEntity,
    CaptureEntity,
    EvalRecordEntity,
)
from server.app.application.dto import GraphDataDTO, GraphNodeDTO, GraphEdgeDTO, ProcessingJobDTO
from server.app.infrastructure.database import DatabaseManager

class SqliteKnowledgeRepository(KnowledgeRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, item: KnowledgeItemEntity) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT OR REPLACE INTO knowledge_items
        (id, capture_id, title, core_idea, details, transcript, concepts, tags, open_questions, candidate_relations, provenance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.id,
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
            item.created_at,
            item.updated_at
        ))
        conn.commit()

    def get_by_id(self, item_id: str) -> Optional[KnowledgeItemEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT * FROM knowledge_items WHERE id = ?", (item_id,)).fetchone()
        if not r:
            return None
        return self._row_to_entity(r)

    def get_by_capture_id(self, capture_id: str) -> Optional[KnowledgeItemEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT * FROM knowledge_items WHERE capture_id = ?", (capture_id,)).fetchone()
        if not r:
            return None
        return self._row_to_entity(r)

    def get_all(self, query: str = "", limit: Optional[int] = None, offset: int = 0) -> List[KnowledgeItemEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        sql = "SELECT * FROM knowledge_items"
        params = []
        if query:
            pattern = f"%{query}%"
            sql += " WHERE title LIKE ? OR core_idea LIKE ? OR transcript LIKE ? OR concepts LIKE ? OR tags LIKE ?"
            params.extend([pattern, pattern, pattern, pattern, pattern])
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = c.execute(sql, tuple(params)).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def count(self, query: str = "") -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        if query:
            pattern = f"%{query}%"
            r = c.execute(
                "SELECT count(*) as cnt FROM knowledge_items WHERE title LIKE ? OR core_idea LIKE ? OR transcript LIKE ? OR concepts LIKE ? OR tags LIKE ?",
                (pattern, pattern, pattern, pattern, pattern)
            ).fetchone()
        else:
            r = c.execute("SELECT count(*) as cnt FROM knowledge_items").fetchone()
        return r["cnt"] if r else 0

    def delete(self, item_id: str) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        # Find matching item IDs for cascade cleanup
        rows = c.execute("SELECT id FROM knowledge_items WHERE id = ? OR capture_id = ?", (item_id, item_id)).fetchall()
        target_ids = [r["id"] for r in rows]
        if item_id not in target_ids:
            target_ids.append(item_id)

        for tid in target_ids:
            c.execute("DELETE FROM knowledge_items WHERE id = ?", (tid,))
            c.execute("DELETE FROM relationships WHERE from_id = ? OR to_id = ?", (tid, tid))
            c.execute("DELETE FROM knowledge_embeddings WHERE item_id = ?", (tid,))
        conn.commit()

    def _row_to_entity(self, r: Any) -> KnowledgeItemEntity:
        return KnowledgeItemEntity(
            id=r["id"],
            capture_id=r["capture_id"],
            title=r["title"],
            core_idea=r["core_idea"],
            details=r["details"] if "details" in r.keys() and r["details"] else "",
            transcript=r["transcript"] or "",
            concepts=json.loads(r["concepts"] or "[]"),
            tags=json.loads(r["tags"] or "[]"),
            open_questions=json.loads(r["open_questions"] or "[]"),
            candidate_relations=json.loads(r["candidate_relations"] or "[]") if "candidate_relations" in r.keys() and r["candidate_relations"] else [],
            provenance=r["provenance"] or "voice-capture",
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

class SqliteRelationshipRepository(RelationshipRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, rel: RelationshipEntity) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT OR IGNORE INTO relationships (id, from_id, to_id, relation_type, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (rel.id, rel.from_id, rel.to_id, rel.relation_type, rel.status, rel.created_at))
        conn.commit()

    def get_by_id(self, rel_id: str) -> Optional[RelationshipEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
        if not r:
            return None
        return RelationshipEntity(
            id=r["id"],
            from_id=r["from_id"],
            to_id=r["to_id"],
            relation_type=r["relation_type"],
            status=r["status"],
            created_at=r["created_at"],
        )

    def get_all(self) -> List[RelationshipEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT * FROM relationships").fetchall()
        return [
            RelationshipEntity(
                id=r["id"],
                from_id=r["from_id"],
                to_id=r["to_id"],
                relation_type=r["relation_type"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def update_status(self, rel_id: str, status: str, relation_type: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        if relation_type:
            c.execute("UPDATE relationships SET status = ?, relation_type = ? WHERE id = ?", (status, relation_type, rel_id))
        else:
            c.execute("UPDATE relationships SET status = ? WHERE id = ?", (status, rel_id))
        conn.commit()

    def delete(self, rel_id: str) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))
        conn.commit()

    def get_graph(self) -> GraphDataDTO:
        conn = self.db.get_connection()
        c = conn.cursor()
        item_rows = c.execute("SELECT id, title FROM knowledge_items ORDER BY created_at DESC").fetchall()
        rel_rows = c.execute("SELECT * FROM relationships").fetchall()

        nodes: List[GraphNodeDTO] = []
        coord_presets = [
            (155.0, 128.0),
            (45.0, 50.0),
            (242.0, 48.0),
            (250.0, 212.0),
            (35.0, 220.0),
            (145.0, 278.0),
            (80.0, 150.0),
            (210.0, 160.0),
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

    def count(self) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT count(*) as cnt FROM relationships").fetchone()
        return r["cnt"] if r else 0

    def count_orphans(self) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("""
        SELECT count(*) as cnt FROM relationships
        WHERE from_id NOT IN (SELECT id FROM knowledge_items)
           OR to_id NOT IN (SELECT id FROM knowledge_items)
        """).fetchone()
        return r["cnt"] if r else 0

class SqliteEmbeddingRepository(EmbeddingRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, item_id: str, vector_bytes: bytes) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT OR REPLACE INTO knowledge_embeddings (item_id, embedding, updated_at)
        VALUES (?, ?, datetime('now'))
        """, (item_id, vector_bytes))
        conn.commit()

    def get_by_item_id(self, item_id: str) -> Optional[bytes]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT embedding FROM knowledge_embeddings WHERE item_id = ?", (item_id,)).fetchone()
        return r["embedding"] if r else None

    def get_all(self) -> List[Tuple[str, bytes]]:
        conn = self.db.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT item_id, embedding FROM knowledge_embeddings").fetchall()
        return [(r["item_id"], r["embedding"]) for r in rows]

    def delete(self, item_id: str) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM knowledge_embeddings WHERE item_id = ?", (item_id,))
        conn.commit()

    def count(self) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT count(*) as cnt FROM knowledge_embeddings").fetchone()
        return r["cnt"] if r else 0

class SqliteCaptureRepository(CaptureRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, capture: CaptureEntity) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT OR REPLACE INTO captures (id, idempotency_key, audio_path, duration_ms, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (capture.id, capture.idempotency_key, capture.audio_path, capture.duration_ms, capture.status, capture.created_at))
        conn.commit()

    def get_by_id(self, capture_id: str) -> Optional[CaptureEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if not r:
            return None
        return CaptureEntity(
            id=r["id"],
            idempotency_key=r["idempotency_key"],
            audio_path=r["audio_path"] or "",
            duration_ms=r["duration_ms"] or 0,
            status=r["status"] or "received",
            created_at=r["created_at"],
        )

    def get_by_idempotency_key(self, key: str) -> Optional[CaptureEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT * FROM captures WHERE idempotency_key = ?", (key,)).fetchone()
        if not r:
            return None
        return CaptureEntity(
            id=r["id"],
            idempotency_key=r["idempotency_key"],
            audio_path=r["audio_path"] or "",
            duration_ms=r["duration_ms"] or 0,
            status=r["status"] or "received",
            created_at=r["created_at"],
        )

    def list_recent(self, limit: int = 50) -> List[CaptureEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT * FROM captures ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [
            CaptureEntity(
                id=r["id"],
                idempotency_key=r["idempotency_key"],
                audio_path=r["audio_path"] or "",
                duration_ms=r["duration_ms"] or 0,
                status=r["status"] or "received",
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def list_all(self) -> List[CaptureEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT * FROM captures ORDER BY created_at DESC").fetchall()
        return [
            CaptureEntity(
                id=r["id"],
                idempotency_key=r["idempotency_key"],
                audio_path=r["audio_path"] or "",
                duration_ms=r["duration_ms"] or 0,
                status=r["status"] or "received",
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def delete(self, capture_id: str) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
        conn.commit()

    def clear_audio_path(self, capture_id: str) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("UPDATE captures SET audio_path = '' WHERE id = ?", (capture_id,))
        conn.commit()

    def count(self) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT count(*) as cnt FROM captures").fetchone()
        return r["cnt"] if r else 0

class SqliteEvalRecordRepository(EvalRecordRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, record: EvalRecordEntity) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT INTO model_eval_records (id, capture_id, transcript, structured_json, user_corrected, consent_given, pipeline_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.id,
            record.capture_id,
            record.transcript,
            record.structured_json,
            1 if record.user_corrected else 0,
            1 if record.consent_given else 0,
            record.pipeline_version,
            record.created_at,
        ))
        conn.commit()

    def get_all_consented(self) -> List[EvalRecordEntity]:
        conn = self.db.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT * FROM model_eval_records WHERE consent_given = 1 ORDER BY created_at DESC").fetchall()
        return [
            EvalRecordEntity(
                id=r["id"],
                capture_id=r["capture_id"],
                transcript=r["transcript"],
                structured_json=r["structured_json"],
                user_corrected=bool(r["user_corrected"]),
                consent_given=bool(r["consent_given"]),
                pipeline_version=r["pipeline_version"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def purge_unconsented(self) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        cur = c.execute("DELETE FROM model_eval_records WHERE consent_given = 0")
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def delete_by_capture_id(self, capture_id: str) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        cur = c.execute("DELETE FROM model_eval_records WHERE capture_id = ?", (capture_id,))
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def purge_all(self) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        cur = c.execute("DELETE FROM model_eval_records")
        deleted = cur.rowcount
        conn.commit()
        return deleted

class SqliteJobStatusRepository(JobStatusRepositoryPort):
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def record_job(self, job: ProcessingJobDTO) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT OR REPLACE INTO processing_jobs (id, capture_id, stage, status, duration_ms, error_message, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.id,
            job.capture_id,
            job.stage,
            job.status,
            job.duration_ms,
            job.error_message,
            job.created_at,
            job.updated_at,
        ))
        conn.commit()

    def update_job_status(self, capture_id: str, stage: str, status: str, error_message: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
        UPDATE processing_jobs
        SET stage = ?, status = ?, error_message = ?, updated_at = datetime('now')
        WHERE capture_id = ?
        """, (stage, status, error_message, capture_id))
        conn.commit()

    def get_recent_jobs(self, limit: int = 50) -> List[ProcessingJobDTO]:
        conn = self.db.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT * FROM processing_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [
            ProcessingJobDTO(
                id=r["id"],
                capture_id=r["capture_id"],
                stage=r["stage"],
                status=r["status"],
                duration_ms=r["duration_ms"] or 0,
                error_message=r["error_message"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def get_by_capture_id(self, capture_id: str) -> Optional[ProcessingJobDTO]:
        conn = self.db.get_connection()
        c = conn.cursor()
        r = c.execute("SELECT * FROM processing_jobs WHERE capture_id = ? ORDER BY created_at DESC LIMIT 1", (capture_id,)).fetchone()
        if not r:
            return None
        return ProcessingJobDTO(
            id=r["id"],
            capture_id=r["capture_id"],
            stage=r["stage"],
            status=r["status"],
            duration_ms=r["duration_ms"] or 0,
            error_message=r["error_message"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def delete_by_capture_id(self, capture_id: str) -> int:
        conn = self.db.get_connection()
        c = conn.cursor()
        cur = c.execute("DELETE FROM processing_jobs WHERE capture_id = ?", (capture_id,))
        deleted = cur.rowcount
        conn.commit()
        return deleted

