"""Persistent, resumable processing pipeline (PRC-01 … PRC-06).

The job table is the contract. Each stage writes its output before advancing,
so a restarted backend can resume without re-running completed work and without
the client triggering anything.
"""

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from difflib import SequenceMatcher
from typing import Any, Dict, Iterator, List, Optional, Tuple

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
    RelationshipTypeRegistryPort,
    TombstoneRepositoryPort,
)
from server.app.domain.entities import (
    CaptureEntity,
    ExtractedEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
    canonical_relation_name,
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
    value = job.stage_outputs
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


class LeaseHeartbeat:
    """Keep a job lease alive while a slow provider call is in flight.

    Provider latency can exceed the lease window. Renewing from a small
    background thread means a slow but healthy LLM call cannot make the job
    look abandoned (and be claimed twice). Renewal never steals a lease from
    another worker: ``renew_lease`` only matches this owner.
    """

    def __init__(
        self,
        job_repo: JobStatusRepositoryPort,
        capture_id: str,
        lease_owner: str,
        lease_seconds: int,
        user_id: str,
    ):
        self.job_repo = job_repo
        self.capture_id = capture_id
        self.lease_owner = lease_owner
        self.lease_seconds = max(1, int(lease_seconds))
        self.user_id = user_id
        self.interval = max(1.0, self.lease_seconds / 3.0)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name=f"echo-lease-{self.capture_id[:8]}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if not self.job_repo.renew_lease(
                    self.capture_id,
                    self.lease_owner,
                    self.lease_seconds,
                    user_id=self.user_id,
                ):
                    # The lease is gone (completed, failed or re-claimed).
                    return
            except Exception:
                # A renewal failure must not kill the pipeline; the next tick
                # retries while the actual work continues.
                continue

    def __enter__(self) -> "LeaseHeartbeat":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()


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
        relationship_type_repo: Optional[RelationshipTypeRegistryPort] = None,
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
        self.relationship_type_repo = relationship_type_repo

    # ----------------------------------------------------------------- queuing
    def create_job(self, capture: CaptureEntity) -> ProcessingJobDTO:
        now = current_utc_iso()
        job = ProcessingJobDTO(
            id=capture.id,
            capture_id=capture.id,
            stage=JobStage.UPLOAD,
            status=JobStatus.QUEUED,
            attempt=0,
            error_class="",
            lease_owner="",
            lease_expires_at=None,
            stage_outputs={},
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

    def rerun_extraction_from_transcript(self, capture_id: str, user_id: str, transcript: str) -> Dict[str, int]:
        """Replace graph output for one capture using its edited transcript.

        Extraction is performed before removing the prior output. Shared graph
        records remain attached to their other captures; capture-exclusive
        records are removed through the same support index used by deletion.
        """
        result = self.extractor.extract_graph(
            transcript.strip(), capture_id, user_id=user_id,
            registry_snapshot=self._registry_snapshot(user_id),
        )
        supports = self.support_repo.list_for_record(user_id, capture_id)
        entity_ids = {x["target_id"] for x in supports if x["target_kind"] == "entity"}
        rel_ids = {x["target_id"] for x in supports if x["target_kind"] == "relationship"}
        entity_ids.update(e.id for e in self.entity_repo.list_by_capture(capture_id, user_id=user_id))
        rel_ids.update(r.id for r in self.rel_repo.get_all(user_id=user_id) if r.source_capture_id == capture_id)
        self.support_repo.delete_for_record(user_id, capture_id)
        removed_entities = removed_relationships = 0
        for entity_id in entity_ids:
            if self.support_repo.list_for_target(user_id, "entity", entity_id):
                continue
            removed_relationships += self.rel_repo.delete_for_entity(entity_id, user_id=user_id)
            self.duplicate_repo.delete_for_entity(entity_id, user_id=user_id)
            self.embedding_repo.delete(entity_id, user_id=user_id)
            self.entity_repo.delete(entity_id, user_id=user_id)
            removed_entities += 1
        for rel_id in rel_ids:
            if self.support_repo.list_for_target(user_id, "relationship", rel_id):
                continue
            if self.rel_repo.get_by_id(rel_id, user_id=user_id):
                self.rel_repo.delete(rel_id, user_id=user_id)
                self.embedding_repo.delete(rel_id, user_id=user_id)
                removed_relationships += 1
        self._save_extraction(user_id, capture_id, self._serialise_extraction(result))
        return {"entities_removed": removed_entities, "relationships_removed": removed_relationships}

    # ---------------------------------------------------------------- worker
    def process_next(self, worker_id: str = "worker-1") -> Optional[ProcessingJobDTO]:
        now = current_utc_iso()
        for job in self.job_repo.list_resumable(now, retry_limit=self.retry_limit):
            result = self.process(job.capture_id, job.user_id, worker_id)
            if result is not None:
                return result
        return None

    def process(self, capture_id: str, user_id: str, worker_id: str = "worker-1") -> Optional[ProcessingJobDTO]:
        job = self.job_repo.claim(
            capture_id,
            worker_id,
            self.lease_seconds,
            user_id=user_id,
            retry_limit=self.retry_limit,
        )
        if job is None:
            return None
        capture = self.capture_repo.get_by_id(capture_id, user_id=user_id)
        if capture is None:
            self.job_repo.record_attempt(
                capture_id, self.retry_limit, ErrorClass.INVALID_INPUT,
                "Recording no longer exists.", user_id=user_id,
                retry_limit=self.retry_limit,
            )
            return self.job_repo.get_by_capture_id(capture_id, user_id=user_id)

        try:
            with LeaseHeartbeat(
                self.job_repo, capture_id, worker_id, self.lease_seconds, user_id
            ):
                self._run(capture, job)
            self.job_repo.complete(capture_id, user_id=user_id)
            capture.status = CaptureStatus.READY
            self.capture_repo.save(capture)
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
            result = self.extractor.extract_graph(
                transcript,
                capture_id,
                user_id=user_id,
                registry_snapshot=self._registry_snapshot(user_id),
            )
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

    def _registry_snapshot(
        self, user_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        if self.relationship_type_repo is None:
            return None
        try:
            entries = self.relationship_type_repo.list_for_user(user_id)
        except Exception:
            return None
        return [
            {
                "canonical_name": entry.canonical_name,
                "semantic_description": entry.semantic_description,
                "aliases": entry.aliases,
            }
            for entry in entries
        ]

    def _normalize_relationship_types(
        self, user_id: str, relationships: List[RelationshipEntity]
    ) -> None:
        """Map every proposed relation type through the registry (U1).

        Runs in ``_save_extraction`` so both fresh and cached (pre-U1) payloads
        are normalised before persistence; ``ensure`` is idempotent.
        Semantically equivalent proposals (same normalized canonical name or
        alias) are reused; genuinely new meanings gain a registry entry.
        """
        if self.relationship_type_repo is None:
            return
        repo = self.relationship_type_repo
        for rel in relationships:
            proposal = canonical_relation_name(rel.relation_type)
            if not proposal:
                proposal = canonical_relation_name("Related to")
            entry = repo.ensure(
                user_id,
                canonical_name=proposal,
                provenance="extraction-proposal",
            )
            rel.relation_type = entry.canonical_name

    def _serialise_extraction(self, result: ExtractionResult) -> Dict[str, Any]:
        return {
            "knowledge_item": asdict(result.knowledge_item),
            "entities": [asdict(entity) for entity in result.entities],
            "relationships": [asdict(rel) for rel in result.relationships],
            "metadata": dict(result.metadata or {}),
        }

    def _deserialise_extraction(self, payload: Dict[str, Any]) -> ExtractionResult:
        def make(cls, data):
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: value for key, value in data.items() if key in allowed})

        return ExtractionResult(
            knowledge_item=make(KnowledgeItemEntity, payload["knowledge_item"]),
            entities=[make(ExtractedEntity, item) for item in payload.get("entities", [])],
            relationships=[make(RelationshipEntity, item) for item in payload.get("relationships", [])],
            metadata=dict(payload.get("metadata") or {}),
        )

    # -------------------------------------------------------------- persistence
    def _embed_knowledge_item(self, user_id: str, item: KnowledgeItemEntity) -> None:
        """Index the item itself for /api/knowledge/semantic-search (KG-04).

        The pipeline already indexes entities and relationships; without this
        an item is invisible to hybrid retrieval until an admin runs the
        embeddings backfill endpoint, which breaks the capture → search loop.
        """
        try:
            vector = self.embedder.embed_item(item)
            self.embedding_repo.save(
                item.id,
                vector,
                user_id=user_id,
                model_name=getattr(self.embedder, "model_name", ""),
                dimension=getattr(self.embedder, "dimension", 0),
            )
        except Exception as exc:
            # Retrieval falls back to lexical ranking; the job must still succeed.
            print(f"[Embedding Error] {exc}")

    def _save_extraction(self, user_id: str, capture_id: str, payload: Dict[str, Any]) -> None:
        result = self._deserialise_extraction(payload)
        # Relationship types flow through the open-ended registry before any
        # write; fresh and cached (pre-U1) payloads are normalised alike.
        self._normalize_relationship_types(user_id, result.relationships)

        # Fetch the real self entity from the database to avoid creating duplicates.
        # The extractor may have created a capture-specific self entity reference.
        self_entity = self.entity_repo.get_self_entity(user_id)

        # Replace any self entity in the extracted entities with the real one.
        if self_entity is not None:
            result.entities = [
                self_entity if e.is_self else e
                for e in result.entities
            ]

        existing = self.entity_repo.get_all(user_id=user_id)
        id_map, saved_entities = self._resolve_entities(user_id, capture_id, result.entities, existing)
        print(f"[DEBUG _save_extraction] saved_entities count: {len(saved_entities)}")
        for e in saved_entities:
            print(f"[DEBUG _save_extraction] saved_entity: {e.id} ({e.name}), has_flag: {hasattr(e, '_flag_score')}, id_map: {id_map.get(e.id)}")

        self.knowledge_repo.save(result.knowledge_item)
        self._embed_knowledge_item(user_id, result.knowledge_item)
        for entity in saved_entities:
            self.entity_repo.save(entity)
            # Entity embeddings are not stored in knowledge_embeddings (FK to knowledge_items)
            # self._embed(user_id, entity.id, self._entity_text(entity))

        # Record deferred duplicate candidates after entities are saved
        for entity in saved_entities:
            if hasattr(entity, '_flag_score'):
                print(f"[DEBUG _save_extraction] Recording flagged duplicate for entity {entity.id} ({entity.name}) with score {entity._flag_score}")
                self.duplicate_repo.record(user_id, entity.id, entity._flag_candidate_id, entity._flag_score, "flagged")
                delattr(entity, '_flag_score')
                delattr(entity, '_flag_candidate_id')
            elif id_map.get(entity.id) != entity.id:
                # Auto-linked: record the auto_linked duplicate
                # Find which candidate this entity was linked to
                candidate_id = id_map.get(entity.id)
                if candidate_id and candidate_id != entity.id:
                    # Find the score by re-computing similarity
                    candidate = next((e for e in existing if e.id == candidate_id), None)
                    if candidate:
                        score = name_similarity(entity.name, candidate.name)
                        self.duplicate_repo.record(user_id, entity.id, candidate_id, score, "auto_linked")
                        if not candidate.description and entity.description:
                            candidate.description = entity.description
                            self.entity_repo.save(candidate)

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
            # Relationship embeddings are not stored in knowledge_embeddings (FK to knowledge_items)
            # self._embed(user_id, persisted_id, f"{rel.relation_type} relationship")

        self._flag_conflicts(user_id, result.relationships, id_map)
        # Orphan cleanup at the END of the extraction pipeline: after auto-linking,
        # dedup, and all entities/relationships for this capture are persisted.
        # Runs inside the same transaction so no non-self orphan is ever committed.
        self.entity_repo.cleanup_orphans(user_id)

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
                # Auto-link: record duplicate candidate after entities are saved
                # (deferred via id_map)
                id_map[entity.id] = candidate.id
                seen[entity.normalized_name] = candidate.id
                continue

            if candidate is not None and best_score >= self.flag_threshold - _EPSILON:
                # Flag for user review: record after entity is saved
                id_map[entity.id] = entity.id
                seen[entity.normalized_name] = entity.id
                to_save.append(entity)
                # Store flag info for later recording
                entity._flag_score = best_score
                entity._flag_candidate_id = candidate.id
                print(f"[DEBUG _resolve_entities] Flagged entity {entity.id} ({entity.name}) with score {best_score}, candidate {candidate.id}")
                continue

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
            capture.id,
            attempt,
            error_class,
            str(exc),
            user_id=user_id,
            retry_limit=self.retry_limit,
        )
        capture.status = CaptureStatus.FAILED if terminal else CaptureStatus.RECEIVED
        self.capture_repo.save(capture)
        return self.job_repo.get_by_capture_id(capture.id, user_id=user_id)
