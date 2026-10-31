import os
from typing import Any, Dict, List, Optional

from server.app.domain.entities import (
    KnowledgeItemEntity,
    ExtractedEntity,
    RelationshipEntity,
    CaptureEntity,
    EvalRecordEntity,
    canonical_relation_name,
)
from server.app.domain.value_objects import CaptureStatus
from server.app.domain.errors import EntityNotFoundError
from ..ports import (
    KnowledgeRepositoryPort,
    EntityRepositoryPort,
    RelationshipRepositoryPort,
    RelationshipTypeRegistryPort,
    DuplicateCandidateRepositoryPort,
    EmbeddingRepositoryPort,
    CaptureRepositoryPort,
    EvalRecordRepositoryPort,
    JobStatusRepositoryPort,
    KnowledgeExtractionPort,
    EmbeddingProviderPort,
    UserRepositoryPort,
    SessionRepositoryPort,
    EmailTokenRepositoryPort,
    ConsentRepositoryPort,
    TombstoneRepositoryPort,
    RecordSupportRepositoryPort,
    AdminAuditLogPort,
)
from ..dto import (
    KnowledgeItemDTO,
    EntityDTO,
    RelationshipDTO,
    GraphDataDTO,
    ScoredKnowledgeItemDTO,
    SystemHealthDTO,
    ProcessingJobDTO,
    DetailedCaptureViewDTO,
)


def entity_to_dto(e: KnowledgeItemEntity) -> KnowledgeItemDTO:
    return KnowledgeItemDTO(
        id=e.id,
        capture_id=e.capture_id,
        title=e.title,
        core_idea=e.core_idea,
        details=e.details,
        transcript=e.transcript,
        concepts=e.concepts,
        tags=e.tags,
        open_questions=e.open_questions,
        candidate_relations=e.candidate_relations,
        provenance=e.provenance,
        created_at=e.created_at,
        updated_at=e.updated_at,
        provider_id=e.provider_id,
        model_version=e.model_version,
    )


def extracted_entity_to_dto(e: ExtractedEntity) -> EntityDTO:
    return EntityDTO(
        id=e.id,
        name=e.name,
        entity_type=e.entity_type,
        description=e.description,
        confidence=e.confidence,
        certainty=e.certainty,
        provenance=e.provenance,
        capture_id=e.capture_id,
        created_at=e.created_at,
        updated_at=e.updated_at,
        provider_id=e.provider_id,
        model_version=e.model_version,
    )


def rel_to_dto(r: RelationshipEntity) -> RelationshipDTO:
    return RelationshipDTO(
        id=r.id,
        from_id=r.from_id,
        to_id=r.to_id,
        relation_type=r.relation_type,
        status=r.status,
        created_at=r.created_at,
        certainty=r.certainty,
        confidence=r.confidence,
        source_capture_id=r.source_capture_id,
    )


class SemanticRecallUseCase:
    def __init__(
        self,
        knowledge_repo: KnowledgeRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        embedder: EmbeddingProviderPort,
    ):
        self.knowledge_repo = knowledge_repo
        self.embedding_repo = embedding_repo
        self.embedder = embedder

    def execute(self, query: str, user_id: str, limit: int = 20) -> List[ScoredKnowledgeItemDTO]:
        query_text = query.strip()
        if not query_text:
            return []

        q_bytes = self.embedder.embed_text(query_text)
        stored_embeddings = self.embedding_repo.get_all(user_id=user_id)
        if not stored_embeddings:
            return []

        all_items = {item.id: item for item in self.knowledge_repo.get_all(user_id=user_id)}
        scored: List[ScoredKnowledgeItemDTO] = []
        for item_id, vec_bytes in stored_embeddings:
            if item_id not in all_items:
                continue
            sim = self.embedder.calculate_similarity(q_bytes, vec_bytes)
            scored.append(ScoredKnowledgeItemDTO(
                item=entity_to_dto(all_items[item_id]),
                similarity_score=sim,
            ))

        scored.sort(key=lambda x: x.similarity_score, reverse=True)
        return scored[:limit]


class ManageKnowledgeUseCase:
    def __init__(
        self,
        knowledge_repo: KnowledgeRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        extractor: KnowledgeExtractionPort,
        embedder: EmbeddingProviderPort,
    ):
        self.knowledge_repo = knowledge_repo
        self.rel_repo = rel_repo
        self.embedding_repo = embedding_repo
        self.extractor = extractor
        self.embedder = embedder

    def list_knowledge(self, user_id: Optional[str], query: str = "", limit: Optional[int] = None, offset: int = 0) -> List[KnowledgeItemDTO]:
        items = self.knowledge_repo.get_all(query=query, limit=limit, offset=offset, user_id=user_id)
        return [entity_to_dto(i) for i in items]

    def get_knowledge(self, item_id: str, user_id: Optional[str]) -> KnowledgeItemDTO:
        item = self.knowledge_repo.get_by_id(item_id, user_id=user_id)
        if not item:
            raise EntityNotFoundError("KnowledgeItem", item_id)
        return entity_to_dto(item)

    def save_or_sync_knowledge(self, item_dto: KnowledgeItemDTO, user_id: str) -> KnowledgeItemDTO:
        existing = self.knowledge_repo.get_by_id(item_dto.id, user_id=user_id)
        if not existing and item_dto.capture_id:
            existing = self.knowledge_repo.get_by_capture_id(item_dto.capture_id, user_id=user_id)

        target_id = existing.id if existing else item_dto.id
        entity = KnowledgeItemEntity(
            id=target_id,
            capture_id=item_dto.capture_id,
            title=item_dto.title,
            core_idea=item_dto.core_idea,
            user_id=user_id,
            details=item_dto.details,
            transcript=item_dto.transcript,
            concepts=item_dto.concepts,
            tags=item_dto.tags,
            open_questions=item_dto.open_questions,
            candidate_relations=item_dto.candidate_relations,
            provenance=item_dto.provenance,
            created_at=item_dto.created_at,
            updated_at=item_dto.updated_at,
        )
        self.knowledge_repo.save(entity)

        if not existing:
            # Admin/manual saves keep entity extraction out of scope; the
            # capture pipeline owns graph extraction.
            pass

        try:
            vec_bytes = self.embedder.embed_item(entity)
            self.embedding_repo.save(entity.id, vec_bytes, user_id=user_id)
        except Exception as e:
            print(f"[Embedding Sync Error] {e}")

        return entity_to_dto(entity)

    def delete_knowledge(self, item_id: str, user_id: Optional[str]) -> None:
        self.knowledge_repo.delete(item_id, user_id=user_id)


class ManageRelationshipsUseCase:
    def __init__(
        self,
        rel_repo: RelationshipRepositoryPort,
        relationship_type_repo: Optional[RelationshipTypeRegistryPort] = None,
    ):
        self.rel_repo = rel_repo
        self.relationship_type_repo = relationship_type_repo

    def get_graph(self, user_id: Optional[str]) -> GraphDataDTO:
        return self.rel_repo.get_graph(user_id=user_id)

    def update_relationship(
        self,
        rel_id: str,
        status: str,
        user_id: Optional[str],
        relation_type: Optional[str] = None,
    ) -> bool:
        if not self.rel_repo.get_by_id(rel_id, user_id=user_id):
            return False
        normalized_type = relation_type
        if normalized_type is not None and self.relationship_type_repo is not None:
            # A user-typed relation label also goes through the registry (U1)
            # so corrections reuse canonical meanings instead of forking keys.
            proposal = canonical_relation_name(normalized_type)
            if proposal:
                entry = self.relationship_type_repo.ensure(
                    user_id,
                    canonical_name=proposal,
                    provenance="user-edit",
                    user_edited=True,
                )
                normalized_type = entry.canonical_name
        self.rel_repo.update_status(rel_id, status=status, relation_type=normalized_type, user_id=user_id)
        return True

    def delete_relationship(self, rel_id: str, user_id: Optional[str]) -> bool:
        if not self.rel_repo.get_by_id(rel_id, user_id=user_id):
            return False
        self.rel_repo.delete(rel_id, user_id=user_id)
        return True


class BackfillEmbeddingsUseCase:
    def __init__(
        self,
        knowledge_repo: KnowledgeRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        embedder: EmbeddingProviderPort,
    ):
        self.knowledge_repo = knowledge_repo
        self.embedding_repo = embedding_repo
        self.embedder = embedder

    def execute(self) -> Dict[str, int]:
        all_items = self.knowledge_repo.get_all()
        stored_ids = {item_id for item_id, _ in self.embedding_repo.get_all()}
        indexed = 0
        failed = 0
        for item in all_items:
            if item.id not in stored_ids:
                try:
                    vec_bytes = self.embedder.embed_item(item)
                    self.embedding_repo.save(item.id, vec_bytes, user_id=item.user_id)
                    indexed += 1
                except Exception as e:
                    print(f"[Embedding Backfill Error on {item.id}] {e}")
                    failed += 1
        return {"total_items": len(all_items), "newly_indexed": indexed, "failed": failed}


class DeleteCaptureUseCase:
    """Deletes one record and only the knowledge it exclusively supported.

    Audio is removed before database rows so that a permission/filesystem
    failure cannot silently report success while leaving retained audio behind.
    Knowledge shared with another record is kept (DEL-01).
    """

    def __init__(
        self,
        capture_repo: CaptureRepositoryPort,
        knowledge_repo: KnowledgeRepositoryPort,
        entity_repo: EntityRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        duplicate_repo: DuplicateCandidateRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        job_repo: JobStatusRepositoryPort,
        eval_repo: EvalRecordRepositoryPort,
        support_repo: RecordSupportRepositoryPort,
        upload_dir: str,
    ):
        self.capture_repo = capture_repo
        self.knowledge_repo = knowledge_repo
        self.entity_repo = entity_repo
        self.rel_repo = rel_repo
        self.duplicate_repo = duplicate_repo
        self.embedding_repo = embedding_repo
        self.job_repo = job_repo
        self.eval_repo = eval_repo
        self.support_repo = support_repo
        self.upload_dir = upload_dir

    def execute(self, capture_id: str, user_id: str) -> Dict[str, Any]:
        capture = self.capture_repo.get_by_id(capture_id, user_id=user_id)
        audio_removed = False
        if capture and capture.audio_path:
            real_path = os.path.realpath(capture.audio_path)
            upload_root = os.path.realpath(self.upload_dir)
            if not (real_path == upload_root or real_path.startswith(upload_root + os.sep)):
                raise RuntimeError("Refusing to delete audio outside the upload directory")
            if os.path.exists(real_path):
                os.remove(real_path)
                audio_removed = True

        supports = self.support_repo.list_for_record(user_id, capture_id)
        entity_ids = {
            entry["target_id"] for entry in supports if entry["target_kind"] == "entity"
        }
        relationship_ids = {
            entry["target_id"] for entry in supports if entry["target_kind"] == "relationship"
        }
        # Legacy rows may predate support tracking; keep their capture link as a
        # fallback so deletion still cleans them up.
        entity_ids.update(
            e.id for e in self.entity_repo.list_by_capture(capture_id, user_id=user_id)
        )
        relationship_ids.update(
            r.id for r in self.rel_repo.get_all(user_id=user_id)
            if r.source_capture_id == capture_id
        )
        supports_removed = self.support_repo.delete_for_record(user_id, capture_id)

        entities_removed = 0
        relationships_removed = 0

        for entity_id in entity_ids:
            if self.support_repo.list_for_target(user_id, "entity", entity_id):
                continue  # shared with another record
            relationships_removed += self.rel_repo.delete_for_entity(entity_id, user_id=user_id)
            self.duplicate_repo.delete_for_entity(entity_id, user_id=user_id)
            self.embedding_repo.delete(entity_id, user_id=user_id)
            self.entity_repo.delete(entity_id, user_id=user_id)
            entities_removed += 1

        for rel_id in relationship_ids:
            rel = self.rel_repo.get_by_id(rel_id, user_id=user_id)
            if not rel:
                continue
            if self.support_repo.list_for_target(user_id, "relationship", rel_id):
                continue
            self.embedding_repo.delete(rel_id, user_id=user_id)
            self.rel_repo.delete(rel_id, user_id=user_id)
            relationships_removed += 1

        self.knowledge_repo.delete(capture_id, user_id=user_id)
        jobs_deleted = self.job_repo.delete_by_capture_id(capture_id, user_id=user_id)
        eval_deleted = self.eval_repo.delete_by_capture_id(capture_id, user_id=user_id)
        if capture:
            self.capture_repo.delete(capture_id, user_id=user_id)

        return {
            "deleted": capture is not None,
            "capture_id": capture_id,
            "audio_removed": audio_removed,
            "entities_removed": entities_removed,
            "relationships_removed": relationships_removed,
            "jobs_deleted": jobs_deleted,
            "eval_records_deleted": eval_deleted,
            "supports_removed": supports_removed,
        }


class PurgeRetainedAudioUseCase:
    """Removes server-retained capture audio after consent withdrawal."""

    def __init__(self, capture_repo: CaptureRepositoryPort, upload_dir: str):
        self.capture_repo = capture_repo
        self.upload_dir = upload_dir

    def execute(self, user_id: Optional[str] = None) -> int:
        upload_root = os.path.realpath(self.upload_dir)
        removed = 0
        for capture in self.capture_repo.list_all(user_id=user_id):
            if not capture.audio_path:
                continue
            real_path = os.path.realpath(capture.audio_path)
            if not (real_path == upload_root or real_path.startswith(upload_root + os.sep)):
                raise RuntimeError("Refusing to purge audio outside the upload directory")
            if os.path.exists(real_path):
                os.remove(real_path)
                removed += 1
            self.capture_repo.clear_audio_path(capture.id, user_id=user_id)
        return removed


class AccountDeletionUseCase:
    """Hard-deletes one user's data and revokes access immediately."""

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        session_repo: SessionRepositoryPort,
        email_token_repo: EmailTokenRepositoryPort,
        consent_repo: ConsentRepositoryPort,
        capture_repo: CaptureRepositoryPort,
        knowledge_repo: KnowledgeRepositoryPort,
        entity_repo: EntityRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        duplicate_repo: DuplicateCandidateRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        job_repo: JobStatusRepositoryPort,
        eval_repo: EvalRecordRepositoryPort,
        tombstone_repo: TombstoneRepositoryPort,
        support_repo: RecordSupportRepositoryPort,
        upload_dir: str,
        audit_repo: Optional[AdminAuditLogPort] = None,
    ):
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.email_token_repo = email_token_repo
        self.consent_repo = consent_repo
        self.capture_repo = capture_repo
        self.knowledge_repo = knowledge_repo
        self.entity_repo = entity_repo
        self.rel_repo = rel_repo
        self.duplicate_repo = duplicate_repo
        self.embedding_repo = embedding_repo
        self.job_repo = job_repo
        self.eval_repo = eval_repo
        self.tombstone_repo = tombstone_repo
        self.support_repo = support_repo
        self.upload_dir = upload_dir
        self.audit_repo = audit_repo

    def execute(self, user_id: str) -> Dict[str, Any]:
        upload_root = os.path.realpath(self.upload_dir)
        removed_audio = 0
        for capture in self.capture_repo.list_all(user_id=user_id):
            if not capture.audio_path:
                continue
            real_path = os.path.realpath(capture.audio_path)
            if real_path == upload_root or real_path.startswith(upload_root + os.sep):
                if os.path.exists(real_path):
                    os.remove(real_path)
                    removed_audio += 1

        # Revoke access before removing rows.
        sessions_revoked = self.session_repo.revoke_all_for_user(user_id)

        items = self.knowledge_repo.get_all(user_id=user_id)
        for item in items:
            self.knowledge_repo.delete(item.id, user_id=user_id)
        for entity in self.entity_repo.get_all(user_id=user_id):
            self.entity_repo.delete(entity.id, user_id=user_id)
        for rel in self.rel_repo.get_all(user_id=user_id):
            self.rel_repo.delete(rel.id, user_id=user_id)
        self.duplicate_repo.delete_for_user(user_id)
        for item_id, _ in self.embedding_repo.get_all(user_id=user_id):
            self.embedding_repo.delete(item_id, user_id=user_id)

        for capture in self.capture_repo.list_all(user_id=user_id):
            self.job_repo.delete_by_capture_id(capture.id, user_id=user_id)
            self.capture_repo.delete(capture.id, user_id=user_id)

        self.eval_repo.delete_for_user(user_id)
        self.support_repo.delete_for_user(user_id)
        self.tombstone_repo.delete_for_user(user_id)
        self.consent_repo.delete_for_user(user_id)
        self.email_token_repo.delete_for_user(user_id)
        self.session_repo.delete_for_user(user_id)
        if self.audit_repo is not None:
            # Audit rows naming this user's data are personal data too (U4).
            self.audit_repo.delete_for_user(user_id)
        self.user_repo.delete(user_id)

        user_upload_dir = os.path.join(upload_root, user_id)
        if os.path.realpath(user_upload_dir).startswith(upload_root + os.sep) and os.path.isdir(user_upload_dir):
            try:
                os.rmdir(user_upload_dir)
            except OSError:
                pass

        return {
            "deleted": True,
            "sessions_revoked": sessions_revoked,
            "audio_files_removed": removed_audio,
        }


class AdminSystemStatusUseCase:
    def __init__(
        self,
        knowledge_repo: KnowledgeRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        capture_repo: CaptureRepositoryPort,
        job_repo: JobStatusRepositoryPort,
        pipeline_version: str,
        upload_dir: str = "server/uploads",
    ):
        self.knowledge_repo = knowledge_repo
        self.rel_repo = rel_repo
        self.embedding_repo = embedding_repo
        self.capture_repo = capture_repo
        self.job_repo = job_repo
        self.pipeline_version = pipeline_version
        self.upload_dir = upload_dir

    def get_health(self) -> SystemHealthDTO:
        k_count = self.knowledge_repo.count()
        r_count = self.rel_repo.count()
        e_count = self.embedding_repo.count()

        audio_bytes = 0
        if os.path.exists(self.upload_dir):
            for root, _, files in os.walk(self.upload_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.isfile(fp):
                        audio_bytes += os.path.getsize(fp)

        recent_jobs = self.job_repo.get_recent_jobs(limit=10)
        active_jobs = sum(1 for j in recent_jobs if j.status == "processing")

        return SystemHealthDTO(
            status="ok",
            service="Echo Knowledge Backend",
            pipeline_version=self.pipeline_version,
            database="connected",
            knowledge_count=k_count,
            relationship_count=r_count,
            embeddings_count=e_count,
            audio_storage_bytes=audio_bytes,
            active_jobs_count=active_jobs,
        )

    def get_recent_jobs(self, limit: int = 50) -> List[ProcessingJobDTO]:
        return self.job_repo.get_recent_jobs(limit=limit)

    def get_detailed_captures(self, limit: int = 50) -> List[DetailedCaptureViewDTO]:
        captures = self.capture_repo.list_recent(limit=limit)
        results: List[DetailedCaptureViewDTO] = []
        for c in captures:
            has_audio = bool(c.audio_path and os.path.exists(c.audio_path))
            audio_url = f"/api/admin/captures/{c.id}/audio" if has_audio else None

            k_item = self.knowledge_repo.get_by_capture_id(c.id)
            if not k_item:
                k_item = self.knowledge_repo.get_by_id(c.id)

            job = self.job_repo.get_by_capture_id(c.id)
            stage = job.stage if job else ("ready" if k_item else c.status)
            status = job.status if job else ("ready" if k_item else c.status)
            error_message = job.error_message if job else None
            original_transcript = k_item.transcript if k_item else None

            results.append(DetailedCaptureViewDTO(
                capture_id=c.id,
                created_at=c.created_at,
                duration_ms=c.duration_ms,
                has_audio=has_audio,
                audio_url=audio_url,
                original_transcript=original_transcript,
                stage=stage,
                status=status,
                error_message=error_message,
                resolved_item=entity_to_dto(k_item) if k_item else None,
            ))
        return results

    def get_detailed_capture_by_id(self, capture_id: str) -> Optional[DetailedCaptureViewDTO]:
        c = self.capture_repo.get_by_id(capture_id)
        if not c:
            return None
        has_audio = bool(c.audio_path and os.path.exists(c.audio_path))
        audio_url = f"/api/admin/captures/{c.id}/audio" if has_audio else None

        k_item = self.knowledge_repo.get_by_capture_id(c.id)
        if not k_item:
            k_item = self.knowledge_repo.get_by_id(c.id)

        job = self.job_repo.get_by_capture_id(c.id)
        stage = job.stage if job else ("ready" if k_item else c.status)
        status = job.status if job else ("ready" if k_item else c.status)
        error_message = job.error_message if job else None
        original_transcript = k_item.transcript if k_item else None

        return DetailedCaptureViewDTO(
            capture_id=c.id,
            created_at=c.created_at,
            duration_ms=c.duration_ms,
            has_audio=has_audio,
            audio_url=audio_url,
            original_transcript=original_transcript,
            stage=stage,
            status=status,
            error_message=error_message,
            resolved_item=entity_to_dto(k_item) if k_item else None,
        )


# M3 use cases live in focused modules; re-exported for container wiring.
from .jobs import ProcessCaptureUseCase, name_similarity  # noqa: E402,F401
from .graph import GraphQueryUseCase  # noqa: E402,F401
