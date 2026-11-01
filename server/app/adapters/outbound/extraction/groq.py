"""Groq-backed knowledge extraction.

Only the transcript text leaves the server. The response is schema-constrained
by the provider and validated again locally. A single bounded repair attempt is
made when the first response is malformed or schema-invalid; the error is never
silently replaced with rule-based output.
"""

import uuid
from typing import Any, Dict, Optional

from server.app.application.dto import ExtractionResult
from server.app.application.ports import KnowledgeExtractionPort, LLMChatPort
from server.app.domain.entities import (
    ExtractedEntity,
    KnowledgeItemEntity,
    RelationshipEntity,
    normalize_key,
)
from server.app.domain.errors import (
    ProviderMalformedResponseError,
    ProviderSchemaError,
    ValidationError,
)
from server.app.domain.value_objects import Certainty, RelationStatus
from .first_person import map_first_person_to_self, find_self_entity

from ..llm.validation import (
    EXTRACTION_SCHEMA,
    EXTRACTION_SCHEMA_NAME,
    validate_extraction,
)

PROVIDER_ID = "extraction_groq"

# Placeholder text for a relation type the model could not determine. Only
# allowed through the prompt policy as a last resort, and mapped to the
# canonical registry entry with the same meaning.
_LAST_RESORT_RELATION = "Related to"

_SYSTEM = (
    "You extract a small knowledge graph from one voice-note transcript. "
    "Return JSON that exactly matches the schema. Rules: "
    "1) Extract only entities explicitly named or clearly described in the transcript; never invent. "
    "2) Use directed relationships: source and target must exactly match an entity name you return. "
    "3) Only state a relationship when the transcript explicitly expresses it. "
    "Never create a relationship just because two names appear in the same sentence. "
    "4) relation_type is the meaning of the stated link in your own words "
    "(a short phrase such as 'Depends on', 'Manages', 'Met with', 'Is the CEO of'). "
    "When the REGISTRY SNAPSHOT contains a type whose meaning matches the utterance, "
    "reuse its exact canonical name instead of proposing a variant. "
    "Use 'Related to' only when two entities are explicitly linked but no more specific "
    "meaning can be determined from the words spoken. "
    "5) evidence must quote the exact fragment of the transcript that states the link. "
    "6) confidence is a number between 0 and 1. "
    "7) title is a short noun phrase; core_idea is one sentence. "
    "If the transcript has no usable named entities, return one concept entity for its main subject."
)


def _registry_prompt_block(
    registry_snapshot: Optional[List[Dict[str, str]]],
) -> str:
    if not registry_snapshot:
        return ""
    lines = []
    for entry in registry_snapshot:
        name = (entry.get("canonical_name") or "").strip()
        if not name:
            continue
        description = (entry.get("semantic_description") or "").strip()
        aliases = [a for a in (entry.get("aliases") or []) if a]
        line = f"- {name}"
        if description:
            line += f": {description}"
        if aliases:
            line += f" (also: {', '.join(aliases)})"
        lines.append(line)
    if not lines:
        return ""
    return "\nREGISTRY SNAPSHOT (reuse these canonical names when their meaning matches):\n" + "\n".join(lines)


def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "echo:" + ":".join(parts)))


def _repair_prompt(user_prompt: str, error: str) -> str:
    return (
        f"{user_prompt}\n\n"
        "Your previous answer was rejected by strict validation. "
        f"Validation error: {error}. "
        "Return ONLY a corrected JSON object that satisfies the schema. "
        "Do not add commentary, markdown fences, or extra keys."
    )


class GroqExtractionAdapter(KnowledgeExtractionPort):
    def __init__(
        self,
        client: LLMChatPort,
        *,
        pipeline_version: str = "v2.0-echo-mvp",
        provider_id: str = PROVIDER_ID,
        repair_attempts: int = 1,
        max_prompt_chars: int = 24000,
    ):
        self.client = client
        self.pipeline_version = pipeline_version
        self.provider_id = provider_id
        self.repair_attempts = max(0, min(1, int(repair_attempts)))
        self.max_prompt_chars = max(1000, int(max_prompt_chars))
        self.last_metadata: Dict[str, Any] = {}

    def extract(self, transcript: str, capture_id: str, user_id: str = "") -> KnowledgeItemEntity:
        return self.extract_graph(transcript, capture_id, user_id).knowledge_item

    def _parse(
        self,
        transcript: str,
        registry_snapshot: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        user_prompt = f"Transcript:\n{transcript}{_registry_prompt_block(registry_snapshot)}"
        last_error = ""
        for attempt in range(0, self.repair_attempts + 1):
            prompt = user_prompt if attempt == 0 else _repair_prompt(user_prompt, last_error)
            try:
                response = self.client.complete_json(
                    operation="extraction",
                    system=_SYSTEM,
                    user=prompt,
                    schema=EXTRACTION_SCHEMA,
                    schema_name=EXTRACTION_SCHEMA_NAME,
                    max_tokens=1400,
                    temperature=0.1,
                )
                data = validate_extraction(response.content)
                self.last_metadata = {
                    "provider": response.provider,
                    "model": response.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                    "attempts": response.attempts,
                    "repair_used": attempt > 0,
                    "latency_ms": response.latency_ms,
                }
                return data
            except (ProviderMalformedResponseError, ProviderSchemaError) as exc:
                last_error = str(exc)
                if attempt >= self.repair_attempts:
                    raise ProviderSchemaError(
                        "The AI extraction could not produce valid graph JSON "
                        f"after {attempt + 1} attempt(s)."
                    ) from exc
        raise ProviderSchemaError("The AI extraction failed validation.")

    def extract_graph(
        self,
        transcript: str,
        capture_id: str,
        user_id: str = "",
        registry_snapshot: Optional[List[Dict[str, str]]] = None,
    ) -> ExtractionResult:
        clean = " ".join((transcript or "").split())
        if not clean:
            raise ValidationError("Cannot extract knowledge from an empty transcript")
        if len(clean) > self.max_prompt_chars:
            clean = clean[: self.max_prompt_chars]

        data = self._parse(clean, registry_snapshot)

        entities = []
        for item in data["entities"]:
            entities.append(
                ExtractedEntity.create(
                    id=_stable_id(
                        user_id, capture_id, item["type"], normalize_key(item["name"])
                    ),
                    capture_id=capture_id,
                    name=item["name"],
                    user_id=user_id,
                    entity_type=item["type"],
                    description="",
                    confidence=item["confidence"],
                    certainty=Certainty.CONFIRMED,
                    provenance="llm-extraction",
                    provider_id=self.provider_id,
                    model_version=self.pipeline_version,
                )
            )

        # Map first-person references to the self entity (shared post-processing)
        self_entity = find_self_entity(entities)
        entities = map_first_person_to_self(entities, user_id, capture_id, self_entity, transcript=clean, provider_id=self.provider_id)

        by_name = {normalize_key(entity.name): entity for entity in entities}

        relationships = []
        for item in data["relationships"]:
            source = by_name.get(normalize_key(item["source"]))
            target = by_name.get(normalize_key(item["target"]))
            if not source or not target or source.id == target.id:
                continue
            contradictory = item["relation_type"] == "Contradicts"
            relationships.append(
                RelationshipEntity.create(
                    id=_stable_id(
                        user_id,
                        capture_id,
                        source.id,
                        target.id,
                        item["relation_type"],
                    ),
                    from_id=source.id,
                    to_id=target.id,
                    user_id=user_id,
                    relation_type=item["relation_type"],
                    status=(
                        RelationStatus.CONFLICTING
                        if contradictory
                        else RelationStatus.SUGGESTED
                    ),
                    certainty=(
                        Certainty.CONFLICTING if contradictory else Certainty.CONFIRMED
                    ),
                    confidence=item["confidence"],
                    source_capture_id=capture_id,
                    provenance="llm-extraction",
                    evidence_utterance=item.get("evidence", "")[:280],
                )
            )

        item = KnowledgeItemEntity.create(
            id=_stable_id(user_id, capture_id, "knowledge_item"),
            capture_id=capture_id,
            title=data["title"][:160],
            core_idea=data["core_idea"][:600],
            user_id=user_id,
            details="",
            transcript=clean,
            concepts=sorted({entity.name for entity in entities}),
            tags=sorted({entity.entity_type for entity in entities}),
            open_questions=[s for s in clean.split(".") if s.strip().endswith("?")],
            candidate_relations=[],
            provenance="llm-extraction",
            provider_id=self.provider_id,
            model_version=self.pipeline_version,
        )
        return ExtractionResult(
            knowledge_item=item,
            entities=entities,
            relationships=relationships,
            metadata=dict(self.last_metadata),
        )
