"""Repeatable extraction benchmark against a fixed gold set.

This is a measurement tool, not a gate. It runs the exact extraction adapter
the pipeline uses, compares the resulting graph with hand-labelled gold
entities/relationships, and prints precision, recall and F1.

The rule-based extractor is the pinned baseline: it is deterministic, offline
and free, so a candidate (e.g. a Groq model) can be compared on the same gold
set without changing anything else.

Gold set format (single JSON file, see server/eval_data/gold/gold_v1.json)::

    [
      {
        "id": "gold-001",
        "transcript": "The Echo project depends on FastAPI.",
        "entities": [{"name": "Echo project", "type": "project"}],
        "relationships": [
          {"source": "Echo project", "target": "FastAPI", "type": "Depends on"}
        ]
      }
    ]

Usage::

    # Deterministic, offline baseline. Never opens a socket.
    python -m server.eval.score --provider rule_based

    # Compare the pinned baseline with the configured hosted provider.
    python -m server.eval.score --provider groq \
        --model openai/gpt-oss-120b --allow-real-calls

Real provider calls are opt-in (``--allow-real-calls``) and use
``GROQ_API_KEY`` from the environment. The key is never printed, logged or
written to the report. Token usage is reported so a run can be budgeted
against the free tier.
"""

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server.app.adapters.outbound.extraction import SemanticKnowledgeExtractor
from server.app.adapters.outbound.extraction.groq import GroqExtractionAdapter
from server.app.adapters.outbound.llm.factory import build_llm_client
from server.app.application.dto import ExtractionResult
from server.app.domain.entities import normalize_key
from server.app.domain.errors import ProviderError
from server.app.infrastructure.config import get_settings

DEFAULT_GOLD = os.path.join(REPO_ROOT, "server", "eval_data", "gold", "gold_v1.json")
DEFAULT_MODEL = "openai/gpt-oss-120b"

_ARTICLES = ("the ", "a ", "an ")


# --------------------------------------------------------------------------- gold


@dataclass(frozen=True)
class GoldExample:
    id: str
    transcript: str
    entities: Tuple[Tuple[str, str], ...]
    relationships: Tuple[Tuple[str, str, str], ...]


def load_gold(path: str) -> List[GoldExample]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list) or not raw:
        raise ValueError("Gold file must be a non-empty JSON array of examples.")
    examples: List[GoldExample] = []
    seen: Set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Gold example #{index} is not an object.")
        example_id = str(item.get("id") or f"gold-{index:03d}")
        if example_id in seen:
            raise ValueError(f"Duplicate gold example id: {example_id}")
        seen.add(example_id)
        transcript = str(item.get("transcript") or "").strip()
        if not transcript:
            raise ValueError(f"Gold example {example_id} has an empty transcript.")
        entities = []
        for entity in item.get("entities") or []:
            name = str(entity.get("name") or "").strip()
            kind = str(entity.get("type") or "").strip()
            if not name or not kind:
                raise ValueError(f"Gold example {example_id} has an invalid entity.")
            entities.append((canonical_name(name), kind.lower()))
        relationships = []
        for rel in item.get("relationships") or []:
            source = canonical_name(str(rel.get("source") or ""))
            target = canonical_name(str(rel.get("target") or ""))
            kind = str(rel.get("type") or "").strip()
            if not source or not target or not kind:
                raise ValueError(f"Gold example {example_id} has an invalid relationship.")
            relationships.append((source, target, kind.lower()))
        examples.append(
            GoldExample(
                id=example_id,
                transcript=transcript,
                entities=tuple(entities),
                relationships=tuple(relationships),
            )
        )
    return examples


def canonical_name(value: str) -> str:
    """Case/article/punctuation-insensitive name key for fair matching."""
    key = normalize_key(value)
    for article in _ARTICLES:
        if key.startswith(article):
            key = key[len(article):]
            break
    return key


# ------------------------------------------------------------------- prediction


@dataclass
class Prediction:
    entities: Set[Tuple[str, str]]
    relationships: Set[Tuple[str, str, str]]
    error: str = ""


def predict(extractor: Any, example: GoldExample) -> Prediction:
    try:
        result: ExtractionResult = extractor.extract_graph(
            example.transcript, example.id, user_id="benchmark"
        )
    except Exception as exc:  # a failed example is a miss, not a crash
        return Prediction(entities=set(), relationships=set(), error=type(exc).__name__)

    names: Dict[str, str] = {}
    entities: Set[Tuple[str, str]] = set()
    for entity in result.entities:
        key = canonical_name(entity.name)
        if not key:
            continue
        names[entity.id] = key
        entities.add((key, str(entity.entity_type).lower()))

    relationships: Set[Tuple[str, str, str]] = set()
    for rel in result.relationships:
        source = names.get(rel.from_id)
        target = names.get(rel.to_id)
        if not source or not target:
            continue
        relationships.add((source, target, str(rel.relation_type).lower()))

    return Prediction(entities=entities, relationships=relationships)


# ---------------------------------------------------------------------- metrics


@dataclass
class Score:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def add(self, gold: Iterable, predicted: Iterable) -> None:
        gold_set, predicted_set = set(gold), set(predicted)
        self.true_positives += len(gold_set & predicted_set)
        self.false_positives += len(predicted_set - gold_set)
        self.false_negatives += len(gold_set - predicted_set)


@dataclass
class BenchmarkResult:
    provider: str
    model: str
    gold_path: str
    gold_hash: str
    examples: int
    entity: Score
    relationship: Score
    failures: List[str]
    resolved_model: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "resolved_model": self.resolved_model,
            "gold_path": self.gold_path,
            "gold_sha256": self.gold_hash,
            "examples": self.examples,
            "entities": {
                "precision": round(self.entity.precision, 4),
                "recall": round(self.entity.recall, 4),
                "f1": round(self.entity.f1, 4),
                "tp": self.entity.true_positives,
                "fp": self.entity.false_positives,
                "fn": self.entity.false_negatives,
            },
            "relationships": {
                "precision": round(self.relationship.precision, 4),
                "recall": round(self.relationship.recall, 4),
                "f1": round(self.relationship.f1, 4),
                "tp": self.relationship.true_positives,
                "fp": self.relationship.false_positives,
                "fn": self.relationship.false_negatives,
            },
            "failed_examples": self.failures,
        }


def run_benchmark(
    examples: Sequence[GoldExample],
    extractor: Any,
    *,
    provider: str,
    model: str,
    gold_path: str,
) -> Tuple[BenchmarkResult, List[Prediction]]:
    entity = Score()
    relationship = Score()
    failures: List[str] = []
    predictions: List[Prediction] = []

    for example in examples:
        prediction = predict(extractor, example)
        predictions.append(prediction)
        entity.add(example.entities, prediction.entities)
        relationship.add(example.relationships, prediction.relationships)
        if prediction.error:
            failures.append(f"{example.id}: {prediction.error}")

    result = BenchmarkResult(
        provider=provider,
        model=model,
        gold_path=gold_path,
        gold_hash=file_sha256(gold_path),
        examples=len(examples),
        entity=entity,
        relationship=relationship,
        failures=failures,
        resolved_model=getattr(extractor, "resolved_model", "") or "",
    )
    return result, predictions


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# -------------------------------------------------------------------- providers


class _MemoryUsageRepository:
    """In-process usage ledger so the benchmark does not touch the app DB."""

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    def usage_since(
        self, since_iso: str, user_id: Optional[str] = None
    ) -> Dict[str, int]:
        # A benchmark run is short; every recorded row is in the window.
        return {
            "calls": len(self.rows),
            "total_tokens": sum(int(row.get("total_tokens") or 0) for row in self.rows),
        }

    def last_calls(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.rows[-limit:]

    @property
    def totals(self) -> Dict[str, int]:
        return {
            "calls": len(self.rows),
            "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in self.rows),
            "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in self.rows),
            "total_tokens": sum(int(row.get("total_tokens") or 0) for row in self.rows),
        }


class _CountingClient:
    """Delegate to the real client but count calls and tokens."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.provider = getattr(inner, "provider", "groq")
        self.model = getattr(inner, "model", "")
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def complete_json(self, **kwargs: Any):
        self.calls += 1
        response = self.inner.complete_json(**kwargs)
        self.prompt_tokens += int(getattr(response, "prompt_tokens", 0) or 0)
        self.completion_tokens += int(getattr(response, "completion_tokens", 0) or 0)
        self.total_tokens += int(getattr(response, "total_tokens", 0) or 0)
        return response

    @property
    def totals(self) -> Dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def build_extractor(provider: str, model: str, allow_real_calls: bool) -> Tuple[Any, Any]:
    """Return (extractor, usage_source). Raises on unsafe/invalid selection."""
    provider = (provider or "").strip().lower()

    if provider in ("", "rule_based", "local"):
        return SemanticKnowledgeExtractor(pipeline_version="benchmark"), None

    if provider == "groq":
        if not allow_real_calls:
            raise SystemExit(
                "Refusing to call Groq without --allow-real-calls. "
                "This command spends real free-tier quota."
            )
        # Explicit, scoped opt-in for this process only. Automated tests never
        # reach this path because they do not pass --allow-real-calls.
        os.environ["ECHO_ALLOW_REAL_LLM"] = "1"
        settings = get_settings()
        if model:
            settings.groq_model = model
        settings.llm_provider = "groq"
        if not settings.groq_api_key:
            raise SystemExit("GROQ_API_KEY is not configured; cannot run the Groq provider.")
        usage = _MemoryUsageRepository()
        inner = build_llm_client(settings, usage)
        if inner is None:
            raise SystemExit("No LLM client was built for provider=groq.")
        client = _CountingClient(inner)
        adapter = GroqExtractionAdapter(client, pipeline_version="benchmark")
        adapter.resolved_model = getattr(client, "model", model)
        return adapter, client

    raise SystemExit(f"Unknown provider {provider!r}. Use rule_based or groq.")


# ------------------------------------------------------------------------ print


def _format_score(score: Score) -> str:
    return (
        f"P={score.precision:.3f} R={score.recall:.3f} F1={score.f1:.3f} "
        f"(tp={score.true_positives} fp={score.false_positives} fn={score.false_negatives})"
    )


def print_result(result: BenchmarkResult, usage: Optional[Dict[str, int]] = None) -> None:
    label = f"{result.provider}" + (f" · {result.resolved_model}" if result.resolved_model else "")
    print(f"Gold set : {result.gold_path}")
    print(f"SHA-256  : {result.gold_hash}")
    print(f"Examples : {result.examples}")
    print(f"Provider : {label}")
    print(f"Entities : {_format_score(result.entity)}")
    print(f"Relations: {_format_score(result.relationship)}")
    if result.failures:
        print(f"Failed   : {', '.join(result.failures)}")
    if usage:
        print(
            "Tokens   : "
            f"calls={usage.get('calls', 0)} "
            f"prompt={usage.get('prompt_tokens', 0)} "
            f"completion={usage.get('completion_tokens', 0)} "
            f"total={usage.get('total_tokens', 0)}"
        )


def print_delta(baseline: BenchmarkResult, candidate: BenchmarkResult) -> None:
    print("\nDelta vs rule_based baseline")
    print(
        "  entity F1     "
        f"{candidate.entity.f1 - baseline.entity.f1:+.3f} "
        f"(baseline {baseline.entity.f1:.3f} -> {candidate.entity.f1:.3f})"
    )
    print(
        "  relationship F1 "
        f"{candidate.relationship.f1 - baseline.relationship.f1:+.3f} "
        f"(baseline {baseline.relationship.f1:.3f} -> {candidate.relationship.f1:.3f})"
    )


# -------------------------------------------------------------------------- CLI


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repeatable extraction benchmark with the rule-based baseline."
    )
    parser.add_argument("--provider", default="rule_based", help="rule_based or groq")
    parser.add_argument("--model", default="", help=f"Model for hosted providers (default {DEFAULT_MODEL})")
    parser.add_argument("--gold", default=DEFAULT_GOLD, help="Path to the gold JSON file")
    parser.add_argument(
        "--allow-real-calls",
        action="store_true",
        help="Required before any hosted provider call is made.",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write the JSON result (key material is never included).",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Skip the rule-based baseline comparison.",
    )
    args = parser.parse_args(argv)

    gold_path = os.path.abspath(args.gold)
    if not os.path.isfile(gold_path):
        raise SystemExit(f"Gold set not found: {gold_path}")
    examples = load_gold(gold_path)

    provider = (args.provider or "rule_based").strip().lower()
    model = args.model or (DEFAULT_MODEL if provider == "groq" else "")
    extractor, usage_source = build_extractor(provider, model, args.allow_real_calls)
    result, _predictions = run_benchmark(
        examples, extractor, provider=provider, model=model, gold_path=gold_path
    )
    usage = usage_source.totals if usage_source is not None else None
    print_result(result, usage)

    payload: Dict[str, Any] = {"result": result.as_dict()}
    if usage is not None:
        payload["usage"] = usage

    if provider != "rule_based" and not args.no_baseline:
        baseline_extractor = SemanticKnowledgeExtractor(pipeline_version="benchmark")
        baseline, _ = run_benchmark(
            examples,
            baseline_extractor,
            provider="rule_based",
            model="deterministic",
            gold_path=gold_path,
        )
        payload["baseline"] = baseline.as_dict()
        print_delta(baseline, result)

    if args.json_out:
        out_path = os.path.abspath(args.json_out)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
