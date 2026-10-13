"""Extraction port: the schema, the KnowledgeExtractor protocol, and a deterministic stub.

Ponytail: the stub is rule-based (stdlib re), so tests need no model loaded. A real
quantized local model plugs into the same KnowledgeExtractor protocol later.
"""
from __future__ import annotations

import re
from typing import List, Optional, Protocol

from pydantic import BaseModel, ConfigDict, field_validator


class EvidenceSpan(BaseModel):
    note_offset: int
    note_length: int
    quoted_text: str


class EntityProposal(BaseModel):
    mention: str
    canonical_name: str
    entity_type: str
    aliases: List[str] = []
    confidence: float
    evidence: List[EvidenceSpan]

    @field_validator("entity_type")
    @classmethod
    def _et(cls, v: str) -> str:
        allowed = {"person", "organization", "place", "concept", "other"}
        if v not in allowed:
            raise ValueError(f"entity_type must be one of {allowed}")
        return v


class FactProposal(BaseModel):
    subject_mention: str
    predicate: str
    object_mention: Optional[str] = None
    value_text: Optional[str] = None
    value_type: Optional[str] = None
    assertion_type: str
    confidence: float
    evidence: List[EvidenceSpan]

    @field_validator("assertion_type")
    @classmethod
    def _at(cls, v: str) -> str:
        if v not in ("explicit", "inferred"):
            raise ValueError("assertion_type must be 'explicit' or 'inferred'")
        return v


class RelationshipProposal(BaseModel):
    source_mention: str
    target_mention: str
    predicate: str
    assertion_type: str
    confidence: float
    evidence: List[EvidenceSpan]


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    prompt_version: str
    entities: List[EntityProposal] = []
    facts: List[FactProposal] = []
    relationships: List[RelationshipProposal] = []

    @field_validator("model", "prompt_version")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v


class KnowledgeExtractor(Protocol):
    """Interface every model adapter must satisfy; injected at runtime."""

    def extract(self, note_content: str) -> ExtractionOutput: ...


# ponytail: deterministic stub extractor. Captures "Alice works at Acme." style
# sentences with a regex; everything else yields nothing. Replace this with a
# real local model that returns the same ExtractionOutput envelope.
_WORKS_AT = re.compile(r"([A-Z][\w']+) works at ([A-Z][\w']+)\.")


def _span(content: str, text: str) -> EvidenceSpan | None:
    """Build a UTF-16 code-unit evidence span for `text` found in `content`."""
    idx = content.find(text)
    if idx < 0:
        return None
    # Python str indexing is UTF-16 code units for BMP (matches the client convention).
    start = len(content[:idx].encode("utf-16-le")) // 2
    end = start + len(text.encode("utf-16-le")) // 2
    return EvidenceSpan(note_offset=start, note_length=end - start, quoted_text=text)


class StubExtractor:
    """Deterministic, model-free extraction. Output always schema-valid."""

    model_name = "stub"
    prompt_version = "v1"

    def extract(self, note_content: str) -> ExtractionOutput:
        content = note_content.strip()
        entities: list[EntityProposal] = []
        facts: list[FactProposal] = []
        relationships: list[RelationshipProposal] = []

        for subj, obj in _WORKS_AT.findall(content):
            es = _span(content, f"{subj} works at {obj}.")
            if es is None:
                continue
            entities.append(EntityProposal(
                mention=subj, canonical_name=subj, entity_type="person", confidence=0.98,
                evidence=[es],
            ))
            entities.append(EntityProposal(
                mention=obj, canonical_name=obj, entity_type="organization", confidence=0.98,
                evidence=[es],
            ))
            relationships.append(RelationshipProposal(
                source_mention=subj, target_mention=obj, predicate="works_at",
                assertion_type="explicit", confidence=0.97, evidence=[es],
            ))
        return ExtractionOutput(
            model=self.model_name, prompt_version=self.prompt_version,
            entities=entities, facts=facts, relationships=relationships,
        )
