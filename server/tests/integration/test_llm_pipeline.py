"""LLM pipeline tests (pipeline split): every test uses the deterministic
fake LLM port and drives it through POST /api/text-kb.

No test in this file opens a socket or reads the real GROQ_API_KEY.
There is no job table any more: a provider failure surfaces as a typed 502 in
the SAME request, the ingest UoW rolls back, and a retry re-runs extraction
(the client re-posts the same capture_id). Stage outputs and resume-at-stage
are worker concepts and are gone.
"""

import json
import uuid

from fastapi.testclient import TestClient

from server.app.adapters.outbound.extraction.groq import GroqExtractionAdapter
from server.app.adapters.outbound.llm.fake import (
    FakeLLMClient,
    FakeScript,
    malformed,
    quota_after,
    timeout,
)
from server.app.domain.entities import KnowledgeItemEntity
from server.app.main import app

from .m3_support import container, ingest_text, new_capture_id

client = TestClient(app)

VALID = {
    "title": "Echo project",
    "core_idea": "Echo depends on FastAPI and Alice owns the roadmap.",
    "entities": [
        {"name": "Echo", "type": "project", "confidence": 0.95},
        {"name": "FastAPI", "type": "tool", "confidence": 0.9},
        {"name": "Alice", "type": "person", "confidence": 0.88},
    ],
    "relationships": [
        {
            "source": "Echo",
            "target": "FastAPI",
            "relation_type": "depends_on",
            "evidence": "Echo depends on FastAPI",
            "confidence": 0.9,
        },
        {
            "source": "Alice",
            "target": "Echo",
            "relation_type": "supports",
            "evidence": "Alice supports Echo",
            "confidence": 0.85,
        },
    ],
}


def _admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


def _install(fake: FakeLLMClient, monkeypatch, capture_id=None):
    """Wire the fake LLM into the ingest port (provider swap by
    composition, not per-request — S3)."""
    container_ = container()
    adapter = GroqExtractionAdapter(fake, pipeline_version="test")
    monkeypatch.setattr(container_.ingestor, "extraction", adapter)
    return container_.ingestor


def test_valid_fake_extraction_persists_graph_provider_and_usage(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([FakeScript(content=VALID)])
    _install(fake, monkeypatch)

    capture_id = ingest_text(client, user, "Echo depends on FastAPI. Alice supports Echo.")

    assert fake.remaining == 0 and len(fake.calls) == 1
    graph = client.get("/api/graph", headers=user.headers).json()
    names = {node["title"] for node in graph["nodes"]}
    assert {"Echo", "FastAPI", "Alice"} <= names
    assert {edge["type"] for edge in graph["edges"]} == {"Depends on", "Supports"}


def test_malformed_json_gets_one_bounded_repair(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([malformed(), FakeScript(content=VALID)])
    _install(fake, monkeypatch)

    capture_id = ingest_text(client, user, "Echo depends on FastAPI. Alice supports Echo.")

    assert len(fake.calls) == 2, "one attempt plus exactly one repair"
    graph = client.get("/api/graph", headers=user.headers).json()
    assert {"Echo", "FastAPI", "Alice"} <= {n["title"] for n in graph["nodes"]}


def test_schema_invalid_twice_fails_typed_without_falling_back(user_factory, monkeypatch):
    from server.app.domain.errors import ProviderError

    user = user_factory(client)
    fake = FakeLLMClient([malformed(), malformed()])
    ingestor = _install(fake, monkeypatch)

    capture_id = new_capture_id()
    response = client.post(
        "/api/text-kb",
        json={"capture_id": capture_id, "text": "Echo depends on FastAPI. Alice supports Echo."},
        headers=user.headers,
    )
    assert response.status_code == 502, response.text
    body = response.json()["detail"]
    assert body["class"] == "schema_invalid", body
    assert len(fake.calls) == 2, "one attempt plus exactly one repair"
    # nothing was created (one UoW rolled back / never started)
    assert [e for e in container().entity_repo.get_all(user_id=user.id) if not e.is_self] == []
    assert container().capture_repo.get_by_id(capture_id, user_id=user.id) is None


def test_timeout_provider_type_is_reported_and_nothing_persists(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([timeout()])
    _install(fake, monkeypatch)

    capture_id = new_capture_id()
    response = client.post(
        "/api/text-kb",
        json={"capture_id": capture_id, "text": "Echo depends on FastAPI. Alice supports Echo."},
        headers=user.headers,
    )
    assert response.status_code == 502, response.text
    body = response.json()["detail"]
    assert body["class"] in ("timeout", "network_error"), body
    assert [e for e in container().entity_repo.get_all(user_id=user.id) if not e.is_self] == []
    # No capture row: STT never wrote one and the ingest UoW never started.
    assert container().capture_repo.get_by_id(capture_id, user_id=user.id) is None


def test_quota_error_reports_specific_message(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([quota_after(42)])
    _install(fake, monkeypatch)

    capture_id = new_capture_id()
    response = client.post(
        "/api/text-kb",
        json={"capture_id": capture_id, "text": "Echo depends on FastAPI. Alice supports Echo."},
        headers=user.headers,
    )
    assert response.status_code == 502, response.text
    body = response.json()["detail"]
    assert body["class"] == "quota_exhausted", body
    assert "quota" in body["message"].lower(), body


def test_user_edited_knowledge_is_not_overwritten_by_a_later_save(user_factory):
    user = user_factory(client)
    item = KnowledgeItemEntity(
        id=str(uuid.uuid4()),
        capture_id=None,  # no capture row exists; a dangling FK is invalid data on Postgres
        title="Edited title",
        core_idea="Edited idea",
        user_id=user.id,
        user_edited=True,
    )
    container().knowledge_repo.save(item)

    replacement = KnowledgeItemEntity(
        id=item.id,
        capture_id=item.capture_id,
        title="Model title",
        core_idea="Model idea",
        user_id=user.id,
    )
    container().knowledge_repo.save(replacement)

    stored = container().knowledge_repo.get_by_id(item.id, user_id=user.id)
    assert stored.title == "Edited title"
    assert stored.core_idea == "Edited idea"


def test_tombstoned_entity_is_not_recreated(user_factory, monkeypatch):
    user = user_factory(client)
    container().tombstone_repo.add(user.id, "entity", "echo")
    fake = FakeLLMClient([FakeScript(content=VALID)])
    _install(fake, monkeypatch)

    ingest_text(client, user, "Echo depends on FastAPI. Alice supports Echo.")

    names = {
        entity.normalized_name
        for entity in container().entity_repo.get_all(user_id=user.id)
    }
    assert "echo" not in names
    assert "fastapi" in names


def test_admin_ai_config_never_exposes_key_and_switches_provider(user_factory, monkeypatch):
    user = user_factory(client)
    cfg = client.get("/api/admin/ai-config", headers=_admin_headers())
    assert cfg.status_code == 200
    body = cfg.json()
    assert body["provider"] == "rule_based"
    assert body["key_configured"] is False
    serialized = json.dumps(body).lower()
    assert "groq_api_key" not in serialized
    assert "bearer" not in serialized

    # Selecting Groq without a server key fails closed.
    denied = client.put(
        "/api/admin/ai-config",
        json={"provider": "groq", "model": "openai/gpt-oss-120b"},
        headers=_admin_headers(),
    )
    assert denied.status_code == 400

    changed = client.put(
        "/api/admin/ai-config",
        json={"provider": "rule_based", "model": "baseline-v1"},
        headers=_admin_headers(),
    )
    assert changed.status_code == 200
    assert changed.json()["consent_version"].endswith("rule_based:baseline-v1")

    fake = FakeLLMClient([FakeScript(content={"ok": True})])
    monkeypatch.setattr(container(), "llm_client", fake)
    tested = client.post("/api/admin/ai-config/test", headers=_admin_headers())
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert tested.json()["network_call"] is True
    assert fake.calls[0]["operation"] == "admin_test"
