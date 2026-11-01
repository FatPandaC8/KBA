"""Persistent, resumable processing pipeline (PRC-01 … PRC-06).

The job table is the contract. Each stage writes its output before advancing,
so a restarted backend can resume without re-running completed work and without
the client triggering anything.
"""

import json
import os
import random
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

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
from server.app.domain.job_state import RetryPolicy as JobRetryPolicy
from server.app.domain.job_state import next_state_after_failure
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
        uow_factory: Optional[Callable[[], Any]] = None,
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
        # R1: application code opens the UoW (one connection/transaction); the
        # adapters inside it are the same repos shared above.
        self.uow_factory = uow_factory
        self.retry_policy = JobRetryPolicy(max_attempts=max(1, retry_limit))

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
    # ---------------------------------------------------------------- worker
    def process_next(self, worker_id: str = "worker-1") -> Optional[ProcessingJobDTO]:
        """Claim the oldest claimable job (FOR UPDATE SKIP LOCKED, R5)."""
        job_dto = self.job_repo.claim_next(worker_id, self.lease_seconds, self.retry_limit)
        if job_dto is None:
            return None
        return self._execute_claimed(job_dto, worker_id)

    def process(self, capture_id: str, user_id: str, worker_id: str = "worker-1") -> Optional[ProcessingJobDTO]:
        """Claim (short tx) → process (NO transaction) → persist → complete.

        On any exception the lease is invalidated by the failure record, the
        ORIGINAL traceback is logged with correlation ids, and failure is
        recorded in a NEW transaction. A single bad job never kills the loop.
        """
        job = self.job_repo.claim(
            capture_id,
            worker_id,
            self.lease_seconds,
            user_id=user_id,
            retry_limit=self.retry_limit,
        )
        if job is None:
            return None
        return self._execute_claimed(job, worker_id)

    def _execute_claimed(
        self, job: ProcessingJobDTO, worker_id: str
    ) -> Optional[ProcessingJobDTO]:
        capture_id = job.capture_id
        user_id = job.user_id
        capture = self.capture_repo.get_by_id(capture_id, user_id=user_id)
        if capture is None:
            import logging

            logging.getLogger("echo.jobs").error(
                "job capture missing job_id=%s capture_id=%s attempt=%s",
                job.id, capture_id, job.attempt,
            )
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
    def _save_extraction(self, user_id: str, capture_id: str, payload: Dict[str, Any]) -> None:
        """R4: plan stages 1-4 pure, then apply stages 5-6 inside ONE UoW.

        Stage order lives in ``application.use_cases.ingest.STAGE_ORDER`` and is
        pinned by a test. All graph writes for one capture commit together.
        """
        result = self._deserialise_extraction(payload)
        # Relationship types flow through the open-ended registry before any
        # write; fresh and cached (pre-U1) payloads are normalised alike.
        self._normalize_relationship_types(user_id, result.relationships)

        def _tombstoned(normalized_key: str) -> bool:
            return self.tombstone_repo.is_tombstoned(user_id, "entity", normalized_key)

        def _between(from_id: str, to_id: str):
            return self.rel_repo.get_between(user_id, from_id, to_id)

        if self.uow_factory:
            with self.uow_factory():
                self._run_ingest(user_id, capture_id, result, _tombstoned, _between)
        else:
            self._run_ingest(user_id, capture_id, result, _tombstoned, _between)

    def _run_ingest(
        self,
        user_id: str,
        capture_id: str,
        result: ExtractionResult,
        tombstone_check: Callable[[str], bool],
        existing_between: Callable[[str, str], List[RelationshipEntity]],
    ) -> None:
        """Runs INSIDE the unit of work opened by ``_save_extraction``.

        Stage semantics (STAGE_ORDER):
        1 normalize_first_person - canonical self replaces every placeholder
        2 resolve_entities       - reads existing graph rows
        3 link                   - relationship endpoints mapped through the plan
        4 dedup                  - auto-link / flag bands recorded
        5 embeddings             - item vector written in the same transaction
        6 prune_orphans          - non-self orphans removed at the very end
        """
        from .ingest import (
            plan_links,
            plan_normalize_first_person,
            plan_resolve_entities,
            conflicts_to_flag,
        )

        # -- stage 1: normalize first person references to the self entity --
        collapsed, dropped_self_ids = plan_normalize_first_person(result.entities)
        self_entity = self.entity_repo.get_or_create_self(user_id)
        if dropped_self_ids or any(e.is_self for e in collapsed):
            canonical_id = self_entity.id
            collapsed = [
                self_entity
                if e.is_self
                else e
                for e in collapsed
            ]
            for rel in result.relationships:
                if rel.from_id in dropped_self_ids:
                    rel.from_id = canonical_id
                if rel.to_id in dropped_self_ids:
                    rel.to_id = canonical_id
        result.entities = collapsed

        # -- stages 2 + 4: resolution and dedup planning (reads inside the tx) --
        existing = self.entity_repo.get_all(user_id=user_id)
        id_map, decisions, to_save = plan_resolve_entities(
            user_id,
            capture_id,
            result.entities,
            existing,
            auto_link_threshold=self.auto_link_threshold,
            flag_threshold=self.flag_threshold,
            tombstone_check=tombstone_check,
            name_similarity_fn=name_similarity,
        )

        # -- stage 3: link planning --
        links = plan_links(result.relationships, id_map, user_id, capture_id)

        # -- writes: knowledge item first, then entities, then embeddings ----
        # (embeddings stage 5 targets rows that exist in THIS transaction)
        self.knowledge_repo.save(result.knowledge_item)
        self._embed_item_in_tx(user_id, result.knowledge_item)

        entity_by_id = {e.id: e for e in existing}
        for entity in to_save:
            self.entity_repo.save(entity)
        for decision in decisions:
            if decision.decision not in ("auto_linked", "flagged"):
                continue
            # duplicate_candidates rows are FK-checked against entities; the
            # auto-linked source row is merged (never persisted), so record
            # the pair onto the surviving canonical row instead (FK-safe,
            # same informational meaning).
            source_id = (
                decision.source_entity.id
                if decision.decision == "flagged"
                else decision.candidate_id
            )
            self.duplicate_repo.record(
                user_id,
                source_id,
                decision.candidate_id,
                decision.score,
                decision.decision,
            )
            if decision.decision == "auto_linked":
                candidate = entity_by_id.get(decision.candidate_id)
                if candidate and not candidate.description and decision.source_entity.description:
                    candidate.description = decision.source_entity.description
                    self.entity_repo.save(candidate)

        # Support index: every entity this capture mentions (DEL-01 sharing).
        for entity_id in sorted(set(id_map.values())):
            self.support_repo.add(user_id, capture_id, "entity", entity_id)

        for rel in links.relationships:
            self.rel_repo.save(rel)
            persisted_id = rel.id
            for stored in self.rel_repo.get_between(user_id, rel.from_id, rel.to_id):
                if stored.relation_type == rel.relation_type:
                    persisted_id = stored.id
                    break
            self.support_repo.add(user_id, capture_id, "relationship", persisted_id)

        for conflict_entity in conflicts_to_flag(links, existing_between):
            self.rel_repo.save(conflict_entity)

        # -- stage 6: orphans go last; the self entity is excluded by rule ----
        self.entity_repo.cleanup_orphans(user_id)

    def _embed_item_in_tx(self, user_id: str, item) -> None:
        """Stage 5: index the item for /api/knowledge/semantic-search (KG-04).

        Called inside the ingest transaction so the FK target exists. An
        embedding failure degrades retrieval to lexical ranking but must not
        kill the capture pipeline.
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
            import logging

            logging.getLogger("echo.jobs").warning(
                "embedding degraded (lexical fallback) item_id=%s error=%s",
                item.id, exc,
            )

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
        """R5 failure path.

        1. Log the ORIGINAL error (with traceback) tagged with job/capture ids
           and the attempt number.
        2. Record the failure in a NEW transaction, scheduling the retry with
           the domain state machine (D7 backoff + jitter) or failing terminally.
        Everything after the log is one fresh transaction (record_attempt +
        capture save are separate short repo calls like today).
        """
        import logging

        logger = logging.getLogger("echo.jobs")
        logger.error(
            "job attempt failed job_id=%s capture_id=%s attempt=%s error=%s",
            job.id, capture.id, job.attempt or 0, exc,
            exc_info=exc,
        )
        error_class = getattr(exc, "error_class", ErrorClass.PROVIDER)
        attempt = (job.attempt or 0) + 1
        target_state, retry_delay = next_state_after_failure(
            "running", error_class, attempt, self.retry_policy
        )
        retry_at = None
        if target_state == "queued":
            from datetime import datetime, timedelta, timezone

            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=retry_delay.total_seconds())).isoformat()
        terminal = target_state == "failed"
        self.job_repo.record_attempt(
            capture.id,
            attempt,
            error_class,
            str(exc),
            user_id=capture.user_id,
            retry_limit=self.retry_limit,
            retry_at=retry_at,
        )
        capture.status = CaptureStatus.FAILED if terminal else CaptureStatus.RECEIVED
        self.capture_repo.save(capture)
        return self.job_repo.get_by_capture_id(capture.id, user_id=capture.user_id)
