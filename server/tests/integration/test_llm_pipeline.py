"""LLM pipeline tests. Every test uses the deterministic fake port.

No test in this file opens a socket or reads the real GROQ_API_KEY.
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

from .m3_support import FakeTranscriber, container, process, upload

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


def _install(fake: FakeLLMClient, monkeypatch, transcript="Echo depends on FastAPI. Alice supports Echo."):
    uc = container().process_capture_uc
    monkeypatch.setattr(uc, "transcriber", FakeTranscriber(transcript))
    monkeypatch.setattr(
        uc,
        "extractor",
        GroqExtractionAdapter(fake, pipeline_version="test"),
    )
    return uc


def _job(capture_id, user_id):
    return container().job_repo.get_by_capture_id(capture_id, user_id=user_id)


def test_valid_fake_extraction_persists_graph_and_metadata(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([FakeScript(content=VALID)])
    _install(fake, monkeypatch)

    capture_id = upload(client, user)
    job = process(capture_id)

    assert job.status == "ready", job
    assert fake.remaining == 0 and len(fake.calls) == 1
    graph = client.get("/api/graph", headers=user.headers).json()
    names = {node["title"] for node in graph["nodes"]}
    assert {"Echo", "FastAPI", "Alice"} <= names
    assert {edge["type"] for edge in graph["edges"]} == {"Depends on", "Supports"}

    outputs = json.loads(_job(capture_id, user.id).stage_outputs)
    assert outputs["extraction"]["metadata"]["provider"] == "fake"
    assert outputs["extraction"]["metadata"]["repair_used"] is False
    assert outputs["extraction"]["metadata"]["total_tokens"] == 200


def test_malformed_json_gets_one_bounded_repair(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([malformed(), FakeScript(content=VALID)])
    _install(fake, monkeypatch)

    capture_id = upload(client, user)
    job = process(capture_id)

    assert job.status == "ready", job
    assert len(fake.calls) == 2
    outputs = json.loads(_job(capture_id, user.id).stage_outputs)
    assert outputs["extraction"]["metadata"]["repair_used"] is True


def test_schema_invalid_twice_fails_without_falling_back(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([malformed(), malformed()])
    _install(fake, monkeypatch)

    capture_id = upload(client, user)
    job = process(capture_id)

    assert job.status == "failed"
    assert job.error_class == "schema_invalid"
    assert len(fake.calls) == 2, "one attempt plus exactly one repair"
    assert container().entity_repo.get_all(user_id=user.id) == []


def test_timeout_is_retryable_and_never_silently_local(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([timeout()])
    _install(fake, monkeypatch)

    capture_id = upload(client, user)
    job = process(capture_id)

    assert job.status == "queued"
    assert job.error_class == "network_error"
    assert job.attempt == 1
    assert container().entity_repo.get_all(user_id=user.id) == []
    recording = client.get("/api/recordings", headers=user.headers).json()[0]
    # A recoverable network failure is automatically requeued, so it is not a
    # manual-retry terminal state.
    assert recording["status"] == "queued"
    assert recording["retryable"] is False


def test_quota_error_reports_specific_message_and_allows_manual_retry(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([quota_after(42)])
    _install(fake, monkeypatch)

    capture_id = upload(client, user)
    job = process(capture_id)

    assert job.status == "failed"
    assert job.error_class == "quota_exhausted"
    recording = client.get("/api/recordings", headers=user.headers).json()[0]
    assert "quota" in (recording["error_message"] or "").lower()
    assert recording["retryable"] is True


def test_resume_reuses_persisted_llm_output_without_second_call(user_factory, monkeypatch):
    user = user_factory(client)
    fake = FakeLLMClient([FakeScript(content=VALID)])
    _install(fake, monkeypatch)

    capture_id = upload(client, user)
    assert process(capture_id).status == "ready"
    assert len(fake.calls) == 1

    conn = container().db_manager.get_connection()
    job = _job(capture_id, user.id)
    outputs = json.loads(job.stage_outputs)
    outputs.pop("saved", None)
    conn.execute(
        "UPDATE processing_jobs SET status='queued', stage='save', attempt=0, "
        "stage_outputs=?, lease_owner='', lease_expires_at='' WHERE capture_id=? AND user_id=?",
        (json.dumps(outputs), capture_id, user.id),
    )
    conn.commit()

    resumed = process(capture_id, worker_id="resumed")
    assert resumed.status == "ready"
    assert len(fake.calls) == 1, "a resume must never re-call the LLM"


def test_user_edited_knowledge_is_not_overwritten_by_a_later_save(user_factory):
    user = user_factory(client)
    item = KnowledgeItemEntity(
        id=str(uuid.uuid4()),
        capture_id=str(uuid.uuid4()),
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

    capture_id = upload(client, user)
    assert process(capture_id).status == "ready"

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
