"""Free, local extraction of entities and relationships.

No transcript text leaves the server and no paid provider is involved. The
extractor is deliberately rule-based and deterministic: the same transcript and
capture always produce the same entity and relationship identifiers, which is
what makes the ``extract`` stage idempotent (PRC-04).
"""

import re
import uuid
from typing import Dict, List, Optional, Tuple

from server.app.application.dto import ExtractionResult
from server.app.application.ports import KnowledgeExtractionPort
from server.app.domain.entities import (
    ExtractedEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
    normalize_key,
)
from server.app.domain.value_objects import Certainty, EntityType, RelationStatus, RelationType
from server.app.domain.errors import ValidationError

PROVIDER_ID = "extraction_local"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_CAP_PHRASE = re.compile(r"\b([A-Z][\w&.'\-]*(?:\s+[A-Z][\w&.'\-]*){0,3})\b")
_QUOTED = re.compile(r"[\"\u201c']([^\"\u201d'\n]{2,60})[\"\u201d']")
_NOUN_CUE = re.compile(
    r"\b(?:the|a|an|my|our|this|that)\s+"
    r"([a-z][a-z0-9\-]+(?:\s+[a-z][a-z0-9\-]+){0,3})\s+"
    r"(project|app|application|idea|platform|tool|system|service|feature|product)\b",
    re.IGNORECASE,
)
_PERSON_CUE = re.compile(
    r"\b(?:with|by|from|told|asked|met|message[sd]?|call(?:ed)?)\s+"
    r"([A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+)?)"
)
_PLACE_CUE = re.compile(
    r"\b(?:in|at|near|visit(?:ed)?|moved to)\s+"
    r"([A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+)?)"
)

_STOP_PHRASES = {
    "i", "the", "this", "that", "these", "those", "it", "we", "they", "he",
    "she", "you", "and", "but", "so", "then", "when", "while", "if", "because",
    "today", "tomorrow", "yesterday", "okay", "ok", "yes", "no", "maybe",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "note", "idea", "actually",
    "also", "however", "well", "right", "sure", "first", "second", "finally",
}

_TOOL_NAMES = {
    "python", "flutter", "dart", "fastapi", "sqlite", "postgres", "redis",
    "docker", "kubernetes", "react", "typescript", "javascript", "swift",
    "kotlin", "android", "ios", "linux", "git", "github", "figma", "notion",
}

_PROJECT_WORDS = {
    "project", "app", "application", "platform", "product", "system", "service",
    "feature", "backend", "frontend", "website", "api",
}

_PERSON_WORDS = {
    "friend", "colleague", "manager", "partner", "boss", "teammate", "founder",
    "investor", "customer", "client", "wife", "husband", "brother", "sister",
}

_HEDGES = (
    "maybe", "might", "probably", "perhaps", "i think", "not sure",
    "unsure", "possibly", "seems", "kind of", "sort of",
)

_NEGATIONS = (
    "not ", "n't", "no longer", "never", "contradicts", "conflicts with",
    "disagree", "wrong about", "isn't", "aren't", "wasn't", "weren't",
)

_RELATION_CUES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (RelationType.DEPENDS_ON, ("depends on", "relies on", "requires", "needs")),
    (RelationType.SUPPORT, ("supports", "helps", "enables", "improves", "backs")),
    (RelationType.EXAMPLE_OF, ("example of", "such as", "for instance")),
    (RelationType.CONSTRAINED_BY, ("constrained by", "limited by", "blocked by", "stuck on")),
    (RelationType.CONTRADICTS, ("contradicts", "conflicts with", "disagree", "opposes", "but not")),
)


def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "echo:" + ":".join(parts)))


def _clean_name(value: str) -> str:
    return " ".join((value or "").strip(" .,;:!?\"'").split())


def _is_stop_phrase(value: str) -> bool:
    tokens = normalize_key(value).split()
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0] in _STOP_PHRASES:
        return True
    return all(token in _STOP_PHRASES for token in tokens)


class SemanticKnowledgeExtractor(KnowledgeExtractionPort):
    """Deterministic local extractor with confidence and provenance."""

    def __init__(self, pipeline_version: str = "v2.0-echo-mvp"):
        self.pipeline_version = pipeline_version

    # ------------------------------------------------------------------ public
    def extract(self, transcript: str, capture_id: str, user_id: str = "") -> KnowledgeItemEntity:
        return self.extract_graph(transcript, capture_id, user_id=user_id).knowledge_item

    def extract_graph(self, transcript: str, capture_id: str, user_id: str = "") -> ExtractionResult:
        clean_text = " ".join((transcript or "").split())
        if not clean_text:
            raise ValidationError("Cannot extract knowledge from empty transcript")

        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(clean_text) if s.strip()]
        entities = self._extract_entities(sentences, capture_id, user_id)
        relationships = self._extract_relationships(sentences, entities, capture_id, user_id)
        item = self._build_item(clean_text, sentences, entities, capture_id, user_id)
        return ExtractionResult(knowledge_item=item, entities=entities, relationships=relationships)

    # ---------------------------------------------------------------- entities
    def _extract_entities(
        self, sentences: List[str], capture_id: str, user_id: str
    ) -> List[ExtractedEntity]:
        found: Dict[Tuple[str, str], ExtractedEntity] = {}

        def add(raw_name: str, entity_type: str, confidence: float) -> None:
            name = _clean_name(raw_name)
            if len(name) < 2 or _is_stop_phrase(name):
                return
            key = (normalize_key(name), entity_type)
            if key in found:
                existing = found[key]
                existing.confidence = max(existing.confidence, confidence)
                return
            found[key] = ExtractedEntity.create(
                id=_stable_id(user_id, capture_id, entity_type, normalize_key(name)),
                capture_id=capture_id,
                name=name,
                user_id=user_id,
                entity_type=entity_type,
                description="",
                confidence=confidence,
                certainty=Certainty.CONFIRMED,
                provenance="voice-capture",
                provider_id=PROVIDER_ID,
                model_version=self.pipeline_version,
            )

        for sentence in sentences:
            lowered = sentence.lower()

            for match in _QUOTED.finditer(sentence):
                add(match.group(1), EntityType.CONCEPT, 0.84)

            for match in _NOUN_CUE.finditer(sentence):
                noun = _clean_name(match.group(1))
                kind_word = match.group(2).lower()
                entity_type = EntityType.PROJECT if kind_word in _PROJECT_WORDS else EntityType.CONCEPT
                add(f"{noun} {kind_word}" if kind_word in _PROJECT_WORDS else noun, entity_type, 0.74)

            for match in _PERSON_CUE.finditer(sentence):
                candidate = match.group(1)
                before = sentence[: match.start()].lower()
                if any(word in before.split()[-4:] for word in _PERSON_WORDS) or any(
                    verb in lower_context(sentence, match.start())
                    for verb in ("told", "asked", "met", "said", "called")
                ):
                    add(candidate, EntityType.PERSON, 0.8)

            for match in _PLACE_CUE.finditer(sentence):
                add(match.group(1), EntityType.PLACE, 0.7)

            for match in _CAP_PHRASE.finditer(sentence):
                phrase = _clean_name(match.group(1))
                if not phrase or _is_stop_phrase(phrase):
                    continue
                if match.start() == 0 and phrase.lower() in _STOP_PHRASES:
                    continue
                first = phrase.split()[0].lower()
                if first in _TOOL_NAMES:
                    add(phrase, EntityType.TOOL, 0.78)
                elif phrase.lower() in _PROJECT_WORDS:
                    add(phrase, EntityType.PROJECT, 0.7)
                else:
                    add(phrase, EntityType.CONCEPT, 0.68)

        return sorted(found.values(), key=lambda e: (e.entity_type, e.normalized_name))

    # ----------------------------------------------------------- relationships
    def _extract_relationships(
        self,
        sentences: List[str],
        entities: List[ExtractedEntity],
        capture_id: str,
        user_id: str,
    ) -> List[RelationshipEntity]:
        by_sentence_name = {entity.normalized_name: entity for entity in entities}
        deduped: Dict[Tuple[str, str, str], RelationshipEntity] = {}

        for sentence in sentences:
            lowered = sentence.lower()
            mentioned = [
                entity for name, entity in by_sentence_name.items() if name and name in lowered
            ]
            if len(mentioned) < 2:
                continue
            mentioned.sort(key=lambda e: lowered.find(e.normalized_name))
            relation_type, confidence = self._classify_sentence(lowered)
            hedged = any(hedge in lowered for hedge in _HEDGES)
            contradicting = relation_type == RelationType.CONTRADICTS

            for index, source in enumerate(mentioned):
                for target in mentioned[index + 1:]:
                    if source.id == target.id:
                        continue
                    key = (source.id, target.id, relation_type)
                    if key in deduped:
                        deduped[key].confidence = max(deduped[key].confidence, confidence)
                        continue
                    deduped[key] = RelationshipEntity.create(
                        id=_stable_id(user_id, capture_id, source.id, target.id, relation_type),
                        from_id=source.id,
                        to_id=target.id,
                        user_id=user_id,
                        relation_type=relation_type,
                        status=RelationStatus.CONFLICTING if contradicting else RelationStatus.SUGGESTED,
                        certainty=(
                            Certainty.CONFLICTING
                            if contradicting
                            else (Certainty.UNCERTAIN if hedged or confidence < 0.65 else Certainty.CONFIRMED)
                        ),
                        confidence=confidence,
                        source_capture_id=capture_id,
                        provenance="voice-capture",
                    )

        return sorted(deduped.values(), key=lambda r: (r.from_id, r.to_id, r.relation_type))

    def _classify_sentence(self, lowered: str) -> Tuple[str, float]:
        for relation_type, cues in _RELATION_CUES:
            for cue in cues:
                if cue in lowered:
                    if relation_type == RelationType.CONTRADICTS:
                        return relation_type, 0.82
                    return relation_type, 0.84
        if any(negation in lowered for negation in _NEGATIONS):
            return RelationType.CONTRADICTS, 0.76
        return RelationType.RELATED_TO, 0.6

    # ------------------------------------------------------------------ record
    def _build_item(
        self,
        clean_text: str,
        sentences: List[str],
        entities: List[ExtractedEntity],
        capture_id: str,
        user_id: str,
    ) -> KnowledgeItemEntity:
        first = sentences[0] if sentences else clean_text
        title = first[:80].rstrip(" .,;:!?") or "Voice note"
        open_questions = [s for s in sentences if s.endswith("?")]
        details = " ".join(sentences[1:]) if len(sentences) > 1 else ""
        return KnowledgeItemEntity.create(
            id=_stable_id(user_id, capture_id, "knowledge_item"),
            capture_id=capture_id,
            title=title,
            core_idea=first,
            user_id=user_id,
            details=details,
            transcript=clean_text,
            concepts=sorted({entity.name for entity in entities}),
            tags=sorted({entity.entity_type for entity in entities}),
            open_questions=open_questions,
            candidate_relations=sorted(
                {f"{e.name} ({e.entity_type})" for e in entities}
            ),
            provenance="voice-capture",
            provider_id=PROVIDER_ID,
            model_version=self.pipeline_version,
        )


def lower_context(sentence: str, position: int, window: int = 24) -> str:
    return sentence[max(0, position - window): position].lower()
