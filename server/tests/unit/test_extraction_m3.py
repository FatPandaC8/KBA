"""M3 extraction units: deterministic typing, certainty and provenance (KG-01, KG-03)."""

import pytest

from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
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


def test_empty_transcript_is_rejected():
    with pytest.raises(ValidationError):
        _extract("   ")
