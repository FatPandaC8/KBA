"""M3 extraction units: deterministic typing, certainty and provenance (KG-01, KG-03)."""

import pytest

from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
from server.app.adapters.outbound.extraction.groq import GroqExtractionAdapter
from server.app.adapters.outbound.llm.fake import FakeLLMClient, FakeScript
from server.app.domain.errors import ValidationError
from server.app.domain.value_objects import Certainty, EntityType, RelationType

TRANSCRIPT = (
    "I met Alice about the Echo project. "
    "Echo depends on FastAPI. "
    "Maybe the launch is risky."
)


def _extract(transcript=TRANSCRIPT, capture_id="capture-1", user_id="user-1"):
    return SemanticKnowledgeExtractor().extract_graph(
        transcript, capture_id, user_id=user_id
    )


def _extract_groq(transcript, capture_id, user_id, fake_response):
    """Helper to test Groq extractor with a fake LLM response."""
    fake_client = FakeLLMClient(script=[FakeScript(content=fake_response)])
    adapter = GroqExtractionAdapter(client=fake_client)
    return adapter.extract_graph(transcript, capture_id, user_id=user_id)


def test_extraction_is_deterministic_with_stable_ids_and_provenance():
    first = _extract()
    second = _extract()

    assert [e.id for e in first.entities] == [e.id for e in second.entities]
    assert [r.id for r in first.relationships] == [r.id for r in second.relationships]
    assert first.knowledge_item.id == second.knowledge_item.id
    assert first.knowledge_item.transcript == TRANSCRIPT

    for entity in first.entities:
        assert entity.user_id == "user-1"
        assert entity.capture_id == "capture-1"
        assert entity.provider_id == "extraction_local"
        assert entity.model_version
        assert 0.0 < entity.confidence <= 1.0
        assert entity.certainty == Certainty.CONFIRMED

    assert any(e.name == "FastAPI" and e.entity_type == EntityType.TOOL for e in first.entities)


def test_extraction_keeps_ids_scoped_per_user_and_capture():
    alice = _extract(capture_id="capture-1", user_id="alice")
    bob = _extract(capture_id="capture-1", user_id="bob")

    assert {e.id for e in alice.entities}.isdisjoint({e.id for e in bob.entities})


def test_hedged_statement_is_marked_uncertain():
    result = _extract("Maybe Echo depends on FastAPI.")
    assert result.relationships
    assert all(r.certainty == Certainty.UNCERTAIN for r in result.relationships)


def test_negation_marks_relationship_conflicting():
    result = _extract("Echo contradicts FastAPI.")
    assert result.relationships
    assert all(r.relation_type == RelationType.CONTRADICTS for r in result.relationships)
    assert all(r.certainty == Certainty.CONFLICTING for r in result.relationships)
    assert all(r.status == "conflicting" for r in result.relationships)


def test_negated_dependency_is_never_extracted_as_contradiction():
    # U1: negation must not fabricate a Contradicts fact from "not X depends
    # on Y"; and without an explicit typed cue nothing is extracted.
    result = _extract("Echo no longer depends on FastAPI.")
    assert result.relationships == []


def test_co_occurrence_alone_never_creates_an_edge():
    # U1: two entities mentioned together without a typed cue stay unlinked.
    result = _extract("I saw Alice near the Echo project.")
    assert result.relationships == []


def test_cued_relationship_keeps_evidence_and_direction():
    result = _extract("Echo depends on FastAPI.")
    rels = result.relationships
    assert len(rels) == 1
    rel = rels[0]
    assert rel.relation_type == RelationType.DEPENDS_ON
    assert "depends on" in rel.evidence_utterance.lower()
    names = {e.id: e.name for e in result.entities}
    assert names[rel.from_id] == "Echo"
    assert names[rel.to_id] == "FastAPI"


def test_empty_transcript_is_rejected():
    with pytest.raises(ValidationError):
        _extract("   ")


def test_local_extractor_maps_first_person_to_self_entity():
    """First-person pronouns (i, me, etc.) map to the self entity."""
    result = _extract("Today I met Minh.", capture_id="cap-1", user_id="user-1")

    # Should have self entity
    self_entities = [e for e in result.entities if e.is_self]
    assert len(self_entities) == 1
    self_entity = self_entities[0]
    assert self_entity.name == "Me"
    assert self_entity.entity_type == EntityType.SELF

    # Should have Minh entity
    minh_entities = [e for e in result.entities if e.normalized_name == "minh"]
    assert len(minh_entities) == 1

    # Should have relationship from self to Minh
    rels = [r for r in result.relationships if r.from_id == self_entity.id]
    assert len(rels) >= 1
    assert rels[0].to_id == minh_entities[0].id


def test_local_extractor_maps_english_first_person_to_self():
    """English first-person pronouns (I, me, we) map to the self entity."""
    result = _extract("I met Alice yesterday.", capture_id="cap-2", user_id="user-2")

    self_entities = [e for e in result.entities if e.is_self]
    assert len(self_entities) == 1

    alice_entities = [e for e in result.entities if e.normalized_name == "alice"]
    assert len(alice_entities) == 1

    # Relationship from self to Alice
    rels = [r for r in result.relationships if r.from_id == self_entities[0].id]
    assert len(rels) >= 1
    assert rels[0].to_id == alice_entities[0].id


def test_groq_extractor_maps_first_person_to_self_entity():
    """Groq extractor also maps first-person references to self entity via post-processing."""
    # Fake LLM response that includes a first-person entity
    fake_response = {
        "title": "Meeting with Minh",
        "core_idea": "User met Minh today.",
        "entities": [
            {"name": "Me", "type": "person", "confidence": 0.9},
            {"name": "Minh", "type": "person", "confidence": 0.9},
        ],
        "relationships": [
            {"source": "Me", "target": "Minh", "relation_type": "Met", "confidence": 0.9, "evidence": "I met Minh"}
        ]
    }
    result = _extract_groq("Today I met Minh.", "cap-3", "user-3", fake_response)

    # Should have self entity (added by post-processing)
    self_entities = [e for e in result.entities if e.is_self]
    assert len(self_entities) == 1
    self_entity = self_entities[0]
    assert self_entity.name == "Me"
    assert self_entity.entity_type == EntityType.SELF

    # Should have Minh entity
    minh_entities = [e for e in result.entities if e.normalized_name == "minh"]
    assert len(minh_entities) == 1

    # Relationship should be from self to Minh
    rels = [r for r in result.relationships if r.from_id == self_entity.id]
    assert len(rels) >= 1
    assert rels[0].to_id == minh_entities[0].id
