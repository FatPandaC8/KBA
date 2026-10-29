"""Persistent, resumable processing pipeline (PRC-01 … PRC-06).

The job table is the contract. Each stage writes its output before advancing,
so a restarted backend can resume without re-running completed work and without
the client triggering anything.
"""

import json
import os
import time
import uuid
from dataclasses import asdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from server.app.application.dto import ExtractionResult, ProcessingJobDTO
from server.app.application.ports import (
    AudioTranscriptionPort,
    CaptureRepositoryPort,
    DuplicateCandidateRepositoryPort,
    EmbeddingProviderPort,
    EmbeddingRepositoryPort,
    EntityRepositoryPort,
    JobStatusRepositoryPort,
    KnowledgeExtractionPort,
    KnowledgeRepositoryPort,
    RecordSupportRepositoryPort,
    RelationshipRepositoryPort,
    TombstoneRepositoryPort,
)
from server.app.domain.entities import (
    CaptureEntity,
    ExtractedEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
    current_utc_iso,
    normalize_key,
)
from server.app.domain.errors import DomainError, InvalidInputAudioError
from server.app.domain.value_objects import (
    CaptureStatus,
    Certainty,
    ErrorClass,
    JobStage,
    JobStatus,
    RelationStatus,
    RelationType,
)

_EPSILON = 1e-9


def name_similarity(left: str, right: str) -> float:
    """Similarity used for duplicate matching (KG-02).

    Exact normalized names score 1.0. Otherwise a blend of edit distance and
    token overlap is used, so word order changes do not hide duplicates.
    """
    a, b = normalize_key(left), normalize_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    tokens_a, tokens_b = set(a.split()), set(b.split())
    union = tokens_a | tokens_b
    jaccard = len(tokens_a & tokens_b) / len(union) if union else 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    containment = 0.0
    if min(len(tokens_a), len(tokens_b)) == 1:
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) >= 4 and short in long.split():
            containment = 0.95
    return max(ratio, jaccard * 0.95, containment)


def _decode_stage_outputs(job: ProcessingJobDTO) -> Dict[str, Any]:
    try:
        value = json.loads(job.stage_outputs or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


class ProcessCaptureUseCase:
    def __init__(
        self,
        capture_repo: CaptureRepositoryPort,
        knowledge_repo: KnowledgeRepositoryPort,
        entity_repo: EntityRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        duplicate_repo: DuplicateCandidateRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        job_repo: JobStatusRepositoryPort,
        support_repo: RecordSupportRepositoryPort,
        tombstone_repo: TombstoneRepositoryPort,
        transcriber: AudioTranscriptionPort,
        extractor: KnowledgeExtractionPort,
        embedder: EmbeddingProviderPort,
        upload_dir: str = "server/uploads",
        auto_link_threshold: float = 0.90,
        flag_threshold: float = 0.75,
        retry_limit: int = 3,
        lease_seconds: int = 300,
    ):
        self.capture_repo = capture_repo
        self.knowledge_repo = knowledge_repo
        self.entity_repo = entity_repo
        self.rel_repo = rel_repo
        self.duplicate_repo = duplicate_repo
        self.embedding_repo = embedding_repo
        self.job_repo = job_repo
        self.support_repo = support_repo
        self.tombstone_repo = tombstone_repo
        self.transcriber = transcriber
        self.extractor = extractor
        self.embedder = embedder
        self.upload_dir = upload_dir
        self.auto_link_threshold = auto_link_threshold
        self.flag_threshold = flag_threshold
        self.retry_limit = retry_limit
        self.lease_seconds = lease_seconds

    # ----------------------------------------------------------------- queuing
    def create_job(self, capture: CaptureEntity) -> ProcessingJobDTO:
        now = current_utc_iso()
        job = ProcessingJobDTO(
            id=capture.id,
            capture_id=capture.id,
            stage=JobStage.UPLOAD,
            status=JobStatus.QUEUED,
            duration_ms=capture.duration_ms,
            error_message=None,
            created_at=now,
            updated_at=now,
            user_id=capture.user_id,
        )
        self.job_repo.record_job(job)
        return job

    def retry(self, capture_id: str, user_id: str) -> bool:
        reset = self.job_repo.reset_for_retry(capture_id, user_id=user_id)
        if reset:
            capture = self.capture_repo.get_by_id(capture_id, user_id=user_id)
            if capture:
                capture.status = CaptureStatus.RECEIVED
                self.capture_repo.save(capture)
        return reset

    # ---------------------------------------------------------------- worker
    def process_next(self, worker_id: str = "worker-1") -> Optional[ProcessingJobDTO]:
        now = current_utc_iso()
        for job in self.job_repo.list_resumable(now):
            result = self.process(job.capture_id, job.user_id, worker_id)
            if result is not None:
                return result
        return None

    def process(self, capture_id: str, user_id: str, worker_id: str = "worker-1") -> Optional[ProcessingJobDTO]:
        job = self.job_repo.claim(capture_id, worker_id, self.lease_seconds, user_id=user_id)
        if job is None:
            return None
        capture = self.capture_repo.get_by_id(capture_id, user_id=user_id)
        if capture is None:
            self.job_repo.record_attempt(
                capture_id, self.retry_limit, ErrorClass.INVALID_INPUT,
                "Recording no longer exists.", user_id=user_id,
            )
            return self.job_repo.get_by_capture_id(capture_id, user_id=user_id)

        try:
            self._run(capture, job)
            return self.job_repo.get_by_capture_id(capture_id, user_id=user_id)
        except Exception as exc:  # the worker must never die on one bad job
            return self._record_failure(job, capture, exc)

    # ------------------------------------------------------------------ stages
    def _run(self, capture: CaptureEntity, job: ProcessingJobDTO) -> None:
        user_id = capture.user_id
        capture_id = capture.id
        outputs = _decode_stage_outputs(job)
        stage_rank = JobStage.rank(job.stage)

        if stage_rank < JobStage.rank(JobStage.TRANSCRIBE):
            if not capture.audio_path or not os.path.exists(capture.audio_path):
                raise InvalidInputAudioError("Recording audio is missing on the server.")
            self.job_repo.save_stage_output(
                capture_id, JobStage.TRANSCRIBE, {"upload": True}, user_id=user_id
            )

        transcript = outputs.get("transcript")
        if not transcript:
            capture.status = CaptureStatus.TRANSCRIBING
            self.capture_repo.save(capture)
            transcript = self.transcriber.transcribe(capture.audio_path)
            if not transcript or not transcript.strip():
                raise InvalidInputAudioError("No intelligible speech detected in the recording.")
            self.job_repo.save_stage_output(
                capture_id, JobStage.EXTRACT, {"transcript": transcript}, user_id=user_id
            )
            outputs["transcript"] = transcript

        extraction = outputs.get("extraction")
        if not extraction:
            capture.status = CaptureStatus.EXTRACTING
            self.capture_repo.save(capture)
            result = self.extractor.extract_graph(transcript, capture_id, user_id=user_id)
            extraction = self._serialise_extraction(result)
            self.job_repo.save_stage_output(
                capture_id, JobStage.SAVE, {"extraction": extraction}, user_id=user_id
            )
            outputs["extraction"] = extraction

        if not outputs.get("saved"):
            capture.status = CaptureStatus.INDEXING
            self.capture_repo.save(capture)
            self._save_extraction(user_id, capture_id, extraction)
            self.job_repo.save_stage_output(
                capture_id, JobStage.COMPLETED, {"saved": True}, user_id=user_id
            )

        capture.status = CaptureStatus.READY
        self.capture_repo.save(capture)

    def _serialise_extraction(self, result: ExtractionResult) -> Dict[str, Any]:
        return {
            "knowledge_item": asdict(result.knowledge_item),
            "entities": [asdict(entity) for entity in result.entities],
            "relationships": [asdict(rel) for rel in result.relationships],
        }

    def _deserialise_extraction(self, payload: Dict[str, Any]) -> ExtractionResult:
        def make(cls, data):
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: value for key, value in data.items() if key in allowed})

        return ExtractionResult(
            knowledge_item=make(KnowledgeItemEntity, payload["knowledge_item"]),
            entities=[make(ExtractedEntity, item) for item in payload.get("entities", [])],
            relationships=[make(RelationshipEntity, item) for item in payload.get("relationships", [])],
        )

    # -------------------------------------------------------------- persistence
    def _save_extraction(self, user_id: str, capture_id: str, payload: Dict[str, Any]) -> None:
        result = self._deserialise_extraction(payload)
        existing = self.entity_repo.get_all(user_id=user_id)
        id_map, saved_entities = self._resolve_entities(user_id, capture_id, result.entities, existing)

        self.knowledge_repo.save(result.knowledge_item)
        for entity in saved_entities:
            self.entity_repo.save(entity)
            self._embed(user_id, entity.id, self._entity_text(entity))

        # Every entity this capture mentions must be supported by it, including
        # entities that were auto-linked to an existing node (DEL-01 sharing).
        for entity_id in sorted(set(id_map.values())):
            self.support_repo.add(user_id, capture_id, "entity", entity_id)

        for rel in result.relationships:
            source = id_map.get(rel.from_id)
            target = id_map.get(rel.to_id)
            if not source or not target or source == target:
                continue
            rel.from_id = source
            rel.to_id = target
            rel.user_id = user_id
            rel.source_capture_id = capture_id
            self.rel_repo.save(rel)
            persisted_id = rel.id
            for stored in self.rel_repo.get_between(user_id, source, target):
                if stored.relation_type == rel.relation_type:
                    persisted_id = stored.id
                    break
            self.support_repo.add(user_id, capture_id, "relationship", persisted_id)
            self._embed(user_id, persisted_id, f"{rel.relation_type} relationship")

        self._flag_conflicts(user_id, result.relationships, id_map)

    def _resolve_entities(
        self,
        user_id: str,
        capture_id: str,
        extracted: List[ExtractedEntity],
        existing: List[ExtractedEntity],
    ) -> Tuple[Dict[str, str], List[ExtractedEntity]]:
        """Apply duplicate bands and tombstones (KG-02, PRC-06).

        Returns a map from extracted id to the id that should be persisted, plus
        the entities that are genuinely new.
        """
        id_map: Dict[str, str] = {}
        to_save: List[ExtractedEntity] = []
        pool = [entity for entity in existing if entity.capture_id != capture_id]
        seen: Dict[str, str] = {}

        for entity in extracted:
            entity.user_id = user_id
            if self.tombstone_repo.is_tombstoned(user_id, "entity", entity.normalized_name):
                continue

            candidate = None
            best_score = 0.0
            for other in pool:
                score = name_similarity(entity.name, other.name)
                if score > best_score:
                    best_score, candidate = score, other

            exact = seen.get(entity.normalized_name)
            if exact:
                id_map[entity.id] = exact
                continue

            if candidate is not None and best_score >= self.auto_link_threshold - _EPSILON:
                id_map[entity.id] = candidate.id
                seen[entity.normalized_name] = candidate.id
                self.duplicate_repo.record(user_id, entity.id, candidate.id, best_score, "auto_linked")
                if not candidate.description and entity.description:
                    candidate.description = entity.description
                    self.entity_repo.save(candidate)
                continue

            if candidate is not None and best_score >= self.flag_threshold - _EPSILON:
                self.duplicate_repo.record(user_id, entity.id, candidate.id, best_score, "flagged")

            id_map[entity.id] = entity.id
            seen[entity.normalized_name] = entity.id
            to_save.append(entity)

        return id_map, to_save

    def _flag_conflicts(
        self, user_id: str, relationships: List[RelationshipEntity], id_map: Dict[str, str]
    ) -> None:
        """Keep both sides of a contradiction and mark them (KG-03)."""
        for rel in relationships:
            source = id_map.get(rel.from_id)
            target = id_map.get(rel.to_id)
            if not source or not target:
                continue
            for other in self.rel_repo.get_between(user_id, source, target):
                if other.relation_type == rel.relation_type:
                    continue
                if (
                    RelationType.CONTRADICTS in (rel.relation_type, other.relation_type)
                    or other.certainty == Certainty.CONFLICTING
                ):
                    other.certainty = Certainty.CONFLICTING
                    other.status = RelationStatus.CONFLICTING
                    self.rel_repo.save(other)

    def _entity_text(self, entity: ExtractedEntity) -> str:
        return f"{entity.name} {entity.entity_type} {entity.description}".strip()

    def _embed(self, user_id: str, target_id: str, text: str) -> None:
        try:
            vector = self.embedder.embed_text(text)
            self.embedding_repo.save(
                target_id,
                vector,
                user_id=user_id,
                model_name=getattr(self.embedder, "model_name", ""),
                dimension=getattr(self.embedder, "dimension", 0),
            )
        except Exception as exc:
            # Retrieval falls back to lexical ranking; the job must still succeed.
            print(f"[Embedding Error] {exc}")

    # ---------------------------------------------------------------- failures
    def _record_failure(
        self, job: ProcessingJobDTO, capture: CaptureEntity, exc: Exception
    ) -> ProcessingJobDTO:
        user_id = capture.user_id
        error_class = getattr(exc, "error_class", ErrorClass.PROVIDER)
        attempt = (job.attempt or 0) + 1
        terminal = (
            not ErrorClass.is_recoverable(error_class)
            or attempt >= self.retry_limit
            or isinstance(exc, InvalidInputAudioError)
        )
        self.job_repo.record_attempt(
            capture.id, attempt, error_class, str(exc), user_id=user_id
        )
        capture.status = CaptureStatus.FAILED if terminal else CaptureStatus.RECEIVED
        self.capture_repo.save(capture)
        return self.job_repo.get_by_capture_id(capture.id, user_id=user_id)
