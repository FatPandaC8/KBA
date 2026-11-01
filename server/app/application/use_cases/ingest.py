"""Ingest pipeline stages (ADR R4).

The stage order is defined HERE and only here; a test pins it. Stages 1-4
(normalize → resolve → link → dedup) are pure planning functions over the
extraction result and the current entity set, producing an ``IngestPlan``.
Stage 5 (embeddings) and stage 6 (prune orphans) are applied inside the SAME
unit of work as every other write, so the embeddings FK always sees rows that
exist in the transaction.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.app.domain.entities import (
    ExtractedEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
    current_utc_iso,
    normalize_key,
)

STAGE_ORDER = (
    "normalize_first_person",
    "resolve_entities",
    "link",
    "dedup",
    "embeddings",
    "prune_orphans",
)


@dataclass
class EntityDecision:
    source_entity: ExtractedEntity
    """Extracted entity carrying its original id."""
    target_id: str
    """``sources`` id that should be persisted (dedup target)."""
    decision: str  # "new" | "auto_linked" | "flagged" | "tombstoned"
    score: float = 0.0
    candidate_id: Optional[str] = None


@dataclass
class LinkPlan:
    relationships: List[RelationshipEntity] = field(default_factory=list)
    conflict_flags: List[str] = field(default_factory=list)
    skipped_relationships: int = 0


@dataclass
class IngestPlan:
    """Everything stage 1-4 decided before any write happens."""

    user_id: str
    capture_id: str
    knowledge_item: KnowledgeItemEntity
    entity_decisions: List[EntityDecision] = field(default_factory=list)
    new_entities: List[ExtractedEntity] = field(default_factory=list)
    links: LinkPlan = field(default_factory=LinkPlan)
    metadata: Dict[str, Any] = field(default_factory=dict)


def plan_normalize_first_person(
    extraction_entities: List[ExtractedEntity],
) -> List[ExtractedEntity]:
    """Stage 1: exactly one self-entity placeholder survives normalization.

    Collapses duplicates to the first placeholder (the applier substitutes the
    canonical ``get_or_create_self`` id later). Returns the collapsed list and
    a mapping from dropped placeholder id -> kept placeholder id.
    """
    self_entities = [e for e in extraction_entities if e.is_self]
    if len(self_entities) <= 1:
        return list(extraction_entities), {}
    keep = self_entities[0]
    dropped: Dict[str, str] = {}
    for entity in self_entities[1:]:
        dropped[entity.id] = keep.id
    return [e for e in extraction_entities if e.id not in dropped], dropped


def plan_resolve_entities(
    user_id: str,
    capture_id: str,
    entities: List[ExtractedEntity],
    existing: List[ExtractedEntity],
    *,
    auto_link_threshold: float,
    flag_threshold: float,
    tombstone_check: Callable[[str], bool],
    name_similarity_fn: Callable[[str, str], float],
) -> Tuple[Dict[str, str], List[EntityDecision], List[ExtractedEntity]]:
    """Stage 2 + 4 (tombstones/dedup bands): id→persisted-id map and decisions."""
    epsilon = 1e-9
    id_map: Dict[str, str] = {}
    decisions: List[EntityDecision] = []
    to_save: List[ExtractedEntity] = []
    pool = [entity for entity in existing if entity.capture_id != capture_id]
    seen: Dict[str, str] = {}

    for entity in entities:
        entity.user_id = user_id
        if tombstone_check(entity.normalized_name):
            decisions.append(
                EntityDecision(entity, entity.id, "tombstoned")
            )
            continue

        candidate = None
        best_score = 0.0
        for other in pool:
            score = name_similarity_fn(entity.name, other.name)
            if score > best_score:
                best_score, candidate = score, other

        exact = seen.get(entity.normalized_name)
        if exact:
            id_map[entity.id] = exact
            decisions.append(EntityDecision(entity, exact, "dedup_within_capture"))
            continue

        if candidate is not None and best_score >= auto_link_threshold - epsilon:
            id_map[entity.id] = candidate.id
            seen[entity.normalized_name] = candidate.id
            decisions.append(
                EntityDecision(entity, candidate.id, "auto_linked", best_score, candidate.id)
            )
            continue

        if candidate is not None and best_score >= flag_threshold - epsilon:
            id_map[entity.id] = entity.id
            seen[entity.normalized_name] = entity.id
            to_save.append(entity)
            decisions.append(
                EntityDecision(entity, entity.id, "flagged", best_score, candidate.id)
            )
            continue

        id_map[entity.id] = entity.id
        seen[entity.normalized_name] = entity.id
        to_save.append(entity)
        decisions.append(EntityDecision(entity, entity.id, "new"))

    return id_map, decisions, to_save


def plan_links(
    relationships: List[RelationshipEntity],
    id_map: Dict[str, str],
    user_id: str,
    capture_id: str,
) -> LinkPlan:
    """Stage 3: map relationship endpoints through the id map."""
    plan = LinkPlan()
    for rel in relationships:
        source = id_map.get(rel.from_id)
        target = id_map.get(rel.to_id)
        if not source or not target or source == target:
            plan.skipped_relationships += 1
            continue
        rel.from_id = source
        rel.to_id = target
        rel.user_id = user_id
        rel.source_capture_id = capture_id
        plan.relationships.append(rel)
    return plan


def conflicts_to_flag(
    links: LinkPlan,
    existing_between: Callable[[str, str], List[RelationshipEntity]],
) -> List[RelationshipEntity]:
    """KG-03: keep both sides of a contradiction and mark them."""
    flagged: List[RelationshipEntity] = []
    for rel in links.relationships:
        for other in existing_between(rel.from_id, rel.to_id):
            if other.relation_type == rel.relation_type:
                continue
            if other.certainty == "conflicting":
                continue
            from server.app.domain.value_objects import Certainty, RelationStatus

            if "Contradicts" in (rel.relation_type, other.relation_type):
                other.certainty = Certainty.CONFLICTING
                other.status = RelationStatus.CONFLICTING
                flagged.append(other)
    return flagged
