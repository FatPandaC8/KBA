"""Text-KB use case (pipeline split, S1/S2): transcript text -> knowledge graph.

Implements the ``KnowledgeIngestorPort`` synchronously inside the request —
no worker, no job table, no queue, no polling (S2). One unit of work commits
capture + knowledge item + entities + relationships + embeddings (S4b); on
any error the unit of work rolls back and a *separate* small transaction
writes ``captures.last_error`` so admin can see why it failed (addendum
rule 5).

Idempotent on ``capture_id`` (S4a): the same id for the same user returns the
existing ingest result and creates nothing new; the same id for a different
user is a conflict.

This module must not import audio or STT code (architecture test in
``server/tests/architecture``).
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from server.app.application.dto import ExtractionResult
from server.app.application.ports import (
    CaptureRepositoryPort,
    DuplicateCandidateRepositoryPort,
    EmbeddingProviderPort,
    EmbeddingRepositoryPort,
    EntityRepositoryPort,
    KnowledgeExtractionPort,
    IngestResultDTO,
    KnowledgeIngestorPort,
    KnowledgeRepositoryPort,
    RecordSupportRepositoryPort,
    RelationshipRepositoryPort,
    RelationshipTypeRegistryPort,
    TombstoneRepositoryPort,
)
from server.app.domain.entities import (
    CaptureEntity,
    KnowledgeItemEntity,
    canonical_relation_name,
    current_utc_iso,
)
from server.app.domain.errors import ConflictError, ValidationError
from server.app.domain.value_objects import CaptureStatus
from .ingest import (
    collect_self_placeholders,
    conflicts_to_flag,
    plan_links,
    plan_normalize_first_person,
    plan_resolve_entities,
    plan_rewrite_self_endpoints,
)


@dataclass
class TextKBSettings:
    """One place to read pipeline limits from (no per-request providers)."""

    max_text_chars: int = 20000
    name_similarity_fn: Optional[Callable[[str, str], float]] = None  # default: ingest.name_similarity
    auto_link_threshold: float = 0.90
    flag_threshold: float = 0.75
    relationship_registry: Optional[RelationshipTypeRegistryPort] = None
    uow_factory: Optional[Callable[[], Any]] = None
    store_last_error: bool = True


class TextKBUseCase(KnowledgeIngestorPort):
    """One synchronous call: text -> capture -> knowledge item -> graph."""

    def __init__(
        self,
        capture_repo: CaptureRepositoryPort,
        knowledge_repo: KnowledgeRepositoryPort,
        entity_repo: EntityRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        duplicate_repo: DuplicateCandidateRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        embedder: EmbeddingProviderPort,
        support_repo: RecordSupportRepositoryPort,
        tombstone_repo: TombstoneRepositoryPort,
        extraction: KnowledgeExtractionPort,
        settings: TextKBSettings,
    ):
        self.capture_repo = capture_repo
        self.knowledge_repo = knowledge_repo
        self.entity_repo = entity_repo
        self.rel_repo = rel_repo
        self.duplicate_repo = duplicate_repo
        self.embedding_repo = embedding_repo
        self.embedder = embedder
        self.support_repo = support_repo
        self.tombstone_repo = tombstone_repo
        self.extraction = extraction
        self.settings = settings
        # set by the composition root (rule 5): writes captures.last_error in
        # a separate small transaction after the ingest UoW rolled back.
        self.on_capture_error: Optional[
            Callable[[str, str, str], None]
        ] = None

    # ------------------------------------------------------------------ run
    def ingest(self, user_id: str, capture_id: str, text: str) -> IngestResultDTO:
        text = " ".join((text or "").split()).strip()
        if not text:
            raise ValidationError("Transcript text is empty.")
        if len(text) > self.settings.max_text_chars:
            raise ValidationError(
                f"Transcript text is too long "
                f"({len(text)} > {self.settings.max_text_chars} characters)."
            )

        existing = self.capture_repo.get_by_id(capture_id, user_id=None)
        if existing is not None:
            if existing.user_id != user_id:
                raise ConflictError("capture_id is already in use by another account.")
            # Idempotent replay (S4a) only when the ingest output exists; a
            # capture row without a knowledge item (legacy/failed) still
            # needs its extraction run.
            if self.knowledge_repo.get_by_capture_id(capture_id, user_id=user_id):
                return self._existing_result(user_id, capture_id, existing)

        result = self.extraction.extract_graph(
            text,
            capture_id,
            user_id=user_id,
            registry_snapshot=self._registry_snapshot(user_id),
        )

        try:
            counts = self._persist_ingest(user_id, capture_id, text, result)
        except Exception:
            self._store_capture_error(user_id, capture_id)
            raise

        return IngestResultDTO(
            capture_id=capture_id,
            knowledge_item_id=result.knowledge_item.id,
            entities_added=counts["entities"],
            relationships_added=counts["relationships"],
            provider=extraction_provider_id(result),
        )

    # ------------------------------------------------------------- helpers
    def _persist_ingest(
        self,
        user_id: str,
        capture_id: str,
        text: str,
        result: ExtractionResult,
    ) -> Dict[str, int]:
        """One unit of work: capture + knowledge item + graph commit (S4b)."""
        now = current_utc_iso()
        capture = CaptureEntity(
            id=capture_id,
            idempotency_key=capture_id,
            audio_path="",
            user_id=user_id,
            duration_ms=0,
            status=CaptureStatus.RECEIVED,
            knowledge_item_id=result.knowledge_item.id,
            has_audio=False,
            audio_on_server=False,
            created_at=now,
            updated_at=now,
        )

        def _do() -> Dict[str, int]:
            self.capture_repo.save(capture)
            item = result.knowledge_item
            item.capture_id = capture_id
            item.user_id = user_id
            item.transcript = text
            self.knowledge_repo.save(item)
            counts = self._apply_graph(user_id, capture_id, result)
            capture.status = CaptureStatus.READY
            self.capture_repo.save(capture)
            return counts

        if self.settings.uow_factory:
            with self.settings.uow_factory():
                return _do()
        return _do()

    def _apply_graph(
        self,
        user_id: str,
        capture_id: str,
        result: ExtractionResult,
    ) -> Dict[str, int]:
        """Stages 1-6 of the ingest plan, written inside the SAME UoW (same
        semantics as the ADR pipeline, including the self-endpoint rewrite
        from Bug #2 and FK-safe embedding order)."""

        def _tombstoned(normalized_key: str) -> bool:
            return self.tombstone_repo.is_tombstoned(
                user_id, "entity", normalized_key
            )

        def _between(from_id: str, to_id: str):
            return self.rel_repo.get_between(user_id, from_id, to_id)

        # stage 1: normalize first person references to the self entity
        collapsed, dropped_self_ids = plan_normalize_first_person(result.entities)
        self_entity = self.entity_repo.get_or_create_self(user_id)
        result.relationships = plan_rewrite_self_endpoints(
            result.relationships,
            collect_self_placeholders(result.entities),
            self_entity.id,
        )
        if dropped_self_ids or any(e.is_self for e in collapsed):
            collapsed = [self_entity if e.is_self else e for e in collapsed]
        result.entities = collapsed

        # stages 2 + 4: resolution and dedup planning (reads inside the UoW)
        existing = self.entity_repo.get_all(user_id=user_id)
        id_map, decisions, to_save = plan_resolve_entities(
            user_id,
            capture_id,
            result.entities,
            existing,
            auto_link_threshold=self.settings.auto_link_threshold,
            flag_threshold=self.settings.flag_threshold,
            tombstone_check=_tombstoned,
            name_similarity_fn=(
                self.settings.name_similarity_fn or default_name_similarity
            ),

        )

        # stage 3: link planning; relation types flow through the open-ended
        # registry first (U1, same as the pre-split pipeline): equivalent
        # proposals reuse the canonical entry, new meanings gain one.
        if self.settings.relationship_registry is not None:
            for rel in result.relationships:
                proposal = canonical_relation_name(rel.relation_type) or canonical_relation_name(
                    "Related to"
                )
                entry = self.settings.relationship_registry.ensure(
                    user_id,
                    canonical_name=proposal,
                    provenance="extraction-proposal",
                )
                rel.relation_type = entry.canonical_name
        links = plan_links(result.relationships, id_map, user_id, capture_id)

        entity_by_id = {e.id: e for e in existing}
        for entity in to_save:
            self.entity_repo.save(entity)
        for decision in decisions:
            if decision.decision not in ("auto_linked", "flagged"):
                continue
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
                if (
                    candidate
                    and not candidate.description
                    and decision.source_entity.description
                ):
                    candidate.description = decision.source_entity.description
                    self.entity_repo.save(candidate)

        # Support index: every entity this capture mentions (DEL-01 sharing)
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

        for conflict_entity in conflicts_to_flag(links, _between):
            self.rel_repo.save(conflict_entity)

        # stage 6: orphans go last; the self entity is excluded by rule
        self.entity_repo.cleanup_orphans(user_id)

        # stage 5 (same UoW): item embedding for semantic search
        self._embed_item(user_id, result.knowledge_item)

        new_entities = sum(1 for d in decisions if d.decision == "new")
        return {
            "entities": new_entities,
            "relationships": len(links.relationships),
        }

    def _embed_item(self, user_id: str, item) -> None:
        try:
            vector = self.embedder.embed_item(item)
            self.embedding_repo.save(
                item.id,
                vector,
                user_id=user_id,
                model_name=getattr(self.embedder, "model_name", ""),
                dimension=getattr(self.embedder, "dimension", 0),
            )
        except Exception:
            # embedding failure degrades semantic retrieval, does not fail ingest
            pass

    def _existing_result(
        self, user_id: str, capture_id: str, existing: CaptureEntity
    ) -> IngestResultDTO:
        """Idempotent replay (S4a): same capture_id = return what exists."""
        item = self.knowledge_repo.get_by_capture_id(capture_id, user_id=user_id)
        supports = self.support_repo.list_for_record(user_id, capture_id)
        entity_ids = {x["target_id"] for x in supports if x["target_kind"] == "entity"}
        rel_ids = {x["target_id"] for x in supports if x["target_kind"] == "relationship"}
        return IngestResultDTO(
            capture_id=capture_id,
            knowledge_item_id=item.id if item else (existing.knowledge_item_id or ""),
            entities_added=len(entity_ids),
            relationships_added=len(rel_ids),
            provider="replayed",
        )

    def _registry_snapshot(self, user_id: str) -> Optional[List[Dict[str, Any]]]:
        registry = self.settings.relationship_registry
        if registry is None:
            return None
        try:
            entries = registry.list_for_user(user_id)
        except Exception:
            return None
        return [
            {
                "canonical_name": entry.canonical_name,
                "semantic_description": entry.semantic_description,
                "aliases": list(entry.aliases),
            }
            for entry in entries
        ]

    def _store_capture_error(self, user_id: str, capture_id: str) -> None:
        """Rule 5 default: keep the failure visible for admin in the capture
        row. Separate small transaction; the ingest itself rolled back."""
        if not self.settings.store_last_error or self.on_capture_error is None:
            return
        try:
            self.on_capture_error(user_id, capture_id, "Text-KB ingest failed.")
        except Exception:
            pass


def extraction_provider_id(result: ExtractionResult) -> str:
    """Provenance label mirrors the old pipeline ids (extraction_local/groq)."""
    return (
        getattr(result.knowledge_item, "provider_id", "")
        or result.metadata.get("provider_id", "")
        or "unknown"
    )


def default_name_similarity(a: str, b: str) -> float:
    from server.app.domain.entities import normalize_key

    return 1.0 if normalize_key(a) == normalize_key(b) else 0.0
