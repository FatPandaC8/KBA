"""Graph queries: clustering, semantic search and entity management (KG, SRCH)."""

from typing import Any, Dict, List, Optional

from server.app.application.dto import (
    EntityDTO,
    GraphDataDTO,
    GraphSearchDTO,
    RelationshipDTO,
    ScoredEntityDTO,
)
from server.app.application.ports import (
    DuplicateCandidateRepositoryPort,
    EmbeddingProviderPort,
    EmbeddingRepositoryPort,
    EntityRepositoryPort,
    RecordSupportRepositoryPort,
    RelationshipRepositoryPort,
    TombstoneRepositoryPort,
)
from server.app.domain.entities import ExtractedEntity, RelationshipEntity, normalize_key
from server.app.domain.errors import EntityNotFoundError, ValidationError
from server.app.domain.value_objects import Certainty, RelationStatus

from . import extracted_entity_to_dto, rel_to_dto

# Question words and fillers carry no retrieval signal; leaving them in both
# inflates lexical scores and hides unrelated queries.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "is", "are", "was", "were", "be", "been", "what", "which", "who", "whom",
    "whose", "when", "where", "why", "how", "my", "me", "mine", "i", "you",
    "your", "we", "our", "they", "their", "he", "she", "it", "its", "this",
    "that", "these", "those", "do", "does", "did", "done", "about", "tell",
    "say", "said", "give", "show", "list", "please", "can", "could", "would",
    "should", "has", "have", "had", "any", "some", "there", "than", "then",
}

# `bge-small-en-v1.5` gives unrelated question/name pairs a cosine of roughly
# 0.42–0.52, while a genuine match scores about 0.74 or higher. Without this
# floor every query matches every entity and the assistant answers questions
# the notes cannot support (QA-02).
_SEMANTIC_RELEVANCE = 0.62


def _tokens(value: str) -> set:
    return {
        token
        for token in normalize_key(value).split()
        if len(token) > 1 and token not in _STOPWORDS
    }


class GraphQueryUseCase:
    def __init__(
        self,
        entity_repo: EntityRepositoryPort,
        rel_repo: RelationshipRepositoryPort,
        embedding_repo: EmbeddingRepositoryPort,
        embedder: EmbeddingProviderPort,
        duplicate_repo: DuplicateCandidateRepositoryPort,
        support_repo: RecordSupportRepositoryPort,
        tombstone_repo: TombstoneRepositoryPort,
    ):
        self.entity_repo = entity_repo
        self.rel_repo = rel_repo
        self.embedding_repo = embedding_repo
        self.embedder = embedder
        self.duplicate_repo = duplicate_repo
        self.support_repo = support_repo
        self.tombstone_repo = tombstone_repo

    # ------------------------------------------------------------------- graph
    def get_graph(self, user_id: str) -> GraphDataDTO:
        return self.rel_repo.get_graph(user_id=user_id)

    # ------------------------------------------------------------------ search
    def search(self, user_id: str, query: str, limit: int = 20) -> GraphSearchDTO:
        query_text = (query or "").strip()
        if not query_text:
            return GraphSearchDTO(entities=[], relationships=[])

        entities = self.entity_repo.get_all(user_id=user_id)
        relationships = self.rel_repo.get_all(user_id=user_id)
        entity_by_id = {entity.id: entity for entity in entities}
        query_tokens = _tokens(query_text)

        query_vector: Optional[bytes] = None
        try:
            query_vector = self.embedder.embed_text(query_text)
        except Exception:
            query_vector = None

        stored: Dict[str, bytes] = {}
        if query_vector is not None:
            try:
                stored = dict(self.embedding_repo.get_all(user_id=user_id))
            except Exception:
                stored = {}

        scored: List[ScoredEntityDTO] = []
        for entity in entities:
            semantic = 0.0
            if query_vector is not None and entity.id in stored:
                try:
                    semantic = max(0.0, self.embedder.calculate_similarity(query_vector, stored[entity.id]))
                except Exception:
                    semantic = 0.0
            haystack = f"{entity.name} {entity.entity_type} {entity.description}"
            lexical = _lexical_score(query_tokens, haystack)
            # Semantic similarity alone is not evidence: unrelated questions
            # score above zero against every name. Keep an entity only when the
            # query shares a token with it or the embedding is clearly close.
            if lexical <= 0 and semantic < _SEMANTIC_RELEVANCE:
                continue
            score = (0.75 * semantic) + (0.25 * lexical) if query_vector is not None else lexical
            if score > 0:
                scored.append(ScoredEntityDTO(entity=extracted_entity_to_dto(entity), score=round(score, 4)))
        scored.sort(key=lambda item: item.score, reverse=True)
        top_entities = scored[:limit]
        top_ids = {item.entity.id for item in top_entities}

        related: List[RelationshipDTO] = []
        for rel in relationships:
            if rel.from_id in top_ids or rel.to_id in top_ids:
                related.append(rel_to_dto(rel))
                continue
            source = entity_by_id.get(rel.from_id)
            target = entity_by_id.get(rel.to_id)
            haystack = " ".join(filter(None, [
                rel.relation_type,
                source.name if source else "",
                target.name if target else "",
            ]))
            if _lexical_score(query_tokens, haystack) > 0:
                related.append(rel_to_dto(rel))

        return GraphSearchDTO(entities=top_entities, relationships=related[: limit * 2])

    # ---------------------------------------------------------------- entities
    def get_entity_detail(self, user_id: str, entity_id: str) -> Dict[str, Any]:
        entity = self.entity_repo.get_by_id(entity_id, user_id=user_id)
        if not entity:
            raise EntityNotFoundError("Entity", entity_id)
        names = {entity.id: entity.name}
        relationships = []
        for rel in self.rel_repo.list_for_entity(user_id, entity_id):
            for endpoint in (rel.from_id, rel.to_id):
                if endpoint not in names:
                    other = self.entity_repo.get_by_id(endpoint, user_id=user_id)
                    names[endpoint] = other.name if other else ""
            relationships.append({
                **rel_to_dto(rel).__dict__,
                "from_name": names.get(rel.from_id, ""),
                "to_name": names.get(rel.to_id, ""),
            })
        return {
            "entity": extracted_entity_to_dto(entity).__dict__,
            "relationships": relationships,
        }

    def update_entity(
        self, user_id: str, entity_id: str, name: Optional[str], description: Optional[str]
    ) -> EntityDTO:
        if name is not None and not name.strip():
            raise ValidationError("Entity name cannot be empty")
        if not self.entity_repo.update_fields(entity_id, user_id, name, description):
            raise EntityNotFoundError("Entity", entity_id)
        entity = self.entity_repo.get_by_id(entity_id, user_id=user_id)
        return extracted_entity_to_dto(entity)

    def delete_entity(self, user_id: str, entity_id: str) -> None:
        entity = self.entity_repo.get_by_id(entity_id, user_id=user_id)
        if not entity:
            raise EntityNotFoundError("Entity", entity_id)
        self.tombstone_repo.add(user_id, "entity", entity.normalized_name)
        self.rel_repo.delete_for_entity(entity_id, user_id=user_id)
        self.support_repo.delete_for_target(user_id, "entity", entity_id)
        self.duplicate_repo.delete_for_entity(entity_id, user_id=user_id)
        self.embedding_repo.delete(entity_id, user_id=user_id)
        self.entity_repo.delete(entity_id, user_id=user_id)

    # ----------------------------------------------------------- relationships
    def delete_relationship(self, user_id: str, relationship_id: str) -> None:
        if not self.rel_repo.get_by_id(relationship_id, user_id=user_id):
            raise EntityNotFoundError("Relationship", relationship_id)
        self.support_repo.delete_for_target(user_id, "relationship", relationship_id)
        self.embedding_repo.delete(relationship_id, user_id=user_id)
        self.rel_repo.delete(relationship_id, user_id=user_id)

    def update_relationship(
        self, user_id: str, relationship_id: str, status: str, relation_type: Optional[str] = None
    ) -> RelationshipDTO:
        if status not in (RelationStatus.SUGGESTED, RelationStatus.CONFIRMED):
            raise ValidationError("Invalid relationship status")
        if not self.rel_repo.get_by_id(relationship_id, user_id=user_id):
            raise EntityNotFoundError("Relationship", relationship_id)
        self.rel_repo.update_status(relationship_id, status, relation_type=relation_type, user_id=user_id)
        return rel_to_dto(self.rel_repo.get_by_id(relationship_id, user_id=user_id))

    def conflicts(self, user_id: str) -> List[RelationshipDTO]:
        return [
            rel_to_dto(rel)
            for rel in self.rel_repo.get_all(user_id=user_id)
            if rel.certainty == Certainty.CONFLICTING
        ]


def _lexical_score(query_tokens: set, text: str) -> float:
    if not query_tokens:
        return 0.0
    text_tokens = _tokens(text)
    if not text_tokens:
        return 0.0
    overlap = query_tokens & text_tokens
    if not overlap:
        # Prefix match keeps "project" findable from "projects".
        overlap = {
            token for token in query_tokens
            if any(candidate.startswith(token) or token.startswith(candidate) for candidate in text_tokens)
        }
    return len(overlap) / len(query_tokens)
