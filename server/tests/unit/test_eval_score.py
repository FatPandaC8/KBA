"""Deterministic tests for the repeatable extraction benchmark.

The benchmark must be reproducible and must never require a real provider.
"""

import json

import pytest

from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
from server.app.adapters.outbound.extraction.groq import GroqExtractionAdapter
from server.app.adapters.outbound.llm.fake import FakeLLMClient, FakeScript
from server.eval.score import (
    Score,
    build_extractor,
    canonical_name,
    load_gold,
    predict,
    run_benchmark,
)


GOLD = [
    {
        "id": "t-001",
        "transcript": "The Echo project depends on FastAPI.",
        "entities": [
            {"name": "Echo project", "type": "project"},
            {"name": "FastAPI", "type": "tool"},
        ],
        "relationships": [
            {"source": "Echo project", "target": "FastAPI", "type": "Depends on"}
        ],
    },
    {
        "id": "t-002",
        "transcript": "Alice supports the Echo project.",
        "entities": [
            {"name": "Alice", "type": "person"},
            {"name": "Echo project", "type": "project"},
        ],
        "relationships": [],
    },
]

VALID = {
    "title": "Echo project",
    "core_idea": "Echo depends on FastAPI.",
    "entities": [
        {"name": "Echo project", "type": "project", "confidence": 0.95},
        {"name": "FastAPI", "type": "tool", "confidence": 0.9},
    ],
    "relationships": [
        {
            "source": "Echo project",
            "target": "FastAPI",
            "relation_type": "depends_on",
            "evidence": "Echo project depends on FastAPI.",
            "confidence": 0.9,
        }
    ],
}


def _gold_file(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(GOLD), encoding="utf-8")
    return str(path)


def test_gold_loader_rejects_empty_transcript(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([{"id": "x", "transcript": "", "entities": []}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gold(str(path))


def test_canonical_name_ignores_article_and_case():
    assert canonical_name(" The Echo   Project ") == canonical_name("echo project")


def test_score_math_is_standard_precision_recall_f1():
    score = Score()
    score.add({"a", "b", "c"}, {"a", "b", "d"})
    assert score.true_positives == 2
    assert score.false_positives == 1
    assert score.false_negatives == 1
    assert score.precision == pytest.approx(2 / 3)
    assert score.recall == pytest.approx(2 / 3)
    assert score.f1 == pytest.approx(2 / 3)


def test_rule_based_benchmark_is_repeatable(tmp_path):
    examples = load_gold(_gold_file(tmp_path))
    first, _ = run_benchmark(
        examples,
        SemanticKnowledgeExtractor(),
        provider="rule_based",
        model="",
        gold_path=_gold_file(tmp_path),
    )
    second, _ = run_benchmark(
        examples,
        SemanticKnowledgeExtractor(),
        provider="rule_based",
        model="",
        gold_path=_gold_file(tmp_path),
    )
    assert first.as_dict() == second.as_dict()
    assert first.examples == 2


def test_hosted_benchmark_uses_scripted_fake_and_counts_nothing_real(tmp_path):
    examples = load_gold(_gold_file(tmp_path))
    fake = FakeLLMClient(default_content=VALID)
    extractor = GroqExtractionAdapter(fake, pipeline_version="test")
    result, predictions = run_benchmark(
        examples,
        extractor,
        provider="groq",
        model="fake-model",
        gold_path=_gold_file(tmp_path),
    )
    assert result.examples == 2
    # The fake replays one fixed graph for both transcripts, so the second
    # example's absent relationship/entity shows up as a measured miss.
    assert result.entity.true_positives == 3
    assert result.entity.false_positives == 1
    assert result.relationship.true_positives == 1
    assert result.relationship.false_positives == 1
    assert fake.remaining == 0
    assert all(prediction.error == "" for prediction in predictions)


def test_failed_example_is_a_miss_not_a_crash(tmp_path):
    examples = load_gold(_gold_file(tmp_path))
    fake = FakeLLMClient([FakeScript(raw_text="{not json"), FakeScript(raw_text="{not json")])
    extractor = GroqExtractionAdapter(fake, pipeline_version="test", repair_attempts=0)
    result, _ = run_benchmark(
        examples,
        extractor,
        provider="groq",
        model="fake-model",
        gold_path=_gold_file(tmp_path),
    )
    assert len(result.failures) == 2
    assert result.entity.true_positives == 0


def test_groq_benchmark_requires_explicit_opt_in():
    with pytest.raises(SystemExit):
        build_extractor("groq", "openai/gpt-oss-120b", allow_real_calls=False)


def test_unknown_provider_is_rejected():
    with pytest.raises(SystemExit):
        build_extractor("mystery", "", allow_real_calls=True)


def test_prediction_uses_entity_names_for_relationship_matching(tmp_path):
    examples = load_gold(_gold_file(tmp_path))
    fake = FakeLLMClient(default_content=VALID)
    extractor = GroqExtractionAdapter(fake, pipeline_version="test")
    prediction = predict(extractor, examples[0])
    assert ("echo project", "fastapi", "depends on") in prediction.relationships
