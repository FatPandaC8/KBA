"""U1 (open-ended relationship registry through the pipeline) and U4 (admin
audit log) integration coverage.

Every test drives the synchronous text-kb ingest with the rule-based
extractor; no test opens a socket or reads the real GROQ_API_KEY.
"""

import uuid

from fastapi.testclient import TestClient
from server.app.main import app
from server.app.infrastructure.config import get_settings

from .m3_support import container, ingest_text

client = TestClient(app)


def _admin_headers():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


# ---------------------------------------------------------------------- U1
def test_registry_normalises_and_reuses_canonical_relationships(
    user_factory, monkeypatch
):
    user = user_factory(client)

    ingest_text(client, user, "Echo depends on FastAPI.")
    ingest_text(client, user, "Echo relies on FastAPI.")
    ingest_text(client, user, "Echo works at Acme with Alice.")

    types = {r["type"] for r in client.get("/api/graph", headers=user.headers).json()["edges"]}
    # "relies on" normalised into the canonical "Depends on" (alias match)…
    assert "Depends on" in types
    # …while a genuinely new meaning gains its own registry entry.
    assert "Works at" in types

    registry_names = {
        e.canonical_name for e in container().rel_type_repo.list_for_user(user.id)
    }
    assert {"Depends on", "Works at"} <= registry_names


def test_evidence_utterance_is_persisted_with_relationships(user_factory, monkeypatch):
    user = user_factory(client)
    ingest_text(client, user, "Echo depends on FastAPI.")

    rels = client.get("/api/graph", headers=user.headers).json()["edges"]
    assert rels
    assert any("depends on" in (r.get("evidence") or "").lower() for r in rels)


def test_co_occurrence_never_creates_edges(user_factory, monkeypatch):
    """KG-02 updated for extractor v2.0 (echo-mvp): first-person cues like
    'met X' produce Me-links and pair links between the sentence's mentioned
    entities; the hard rule still enforced is that a sentence with NO typed
    cue and no first-person cue creates no edge at all."""
    user = user_factory(client)
    ingest_text(client, user, "I met Alice about the Echo project over coffee.")

    graph = client.get("/api/graph", headers=user.headers).json()
    names = {n["title"] for n in graph["nodes"]}
    assert {"Alice", "Echo"} <= names, "entities are still extracted"
    me_node = next(n for n in graph["nodes"] if n["is_self"])
    me_links = [e for e in graph["edges"] if me_node["id"] in (e["from_node"], e["to_node"])]
    assert me_links, "the v2.0 first-person cue produces a Met link"

    # A sentence with no typed cue and no first-person cue has no edges.
    user2 = user_factory(client)
    ingest_text(client, user2, "Alice was near the Echo project over coffee.")
    graph2 = client.get("/api/graph", headers=user2.headers).json()
    assert graph2["nodes"], "entities are still extracted"
    assert graph2["edges"] == [], graph2["edges"]


# ---------------------------------------------------------------------- U2
def test_removed_ask_endpoints_return_404(user_factory):
    user = user_factory(client)
    assert (
        client.get("/api/conversations", headers=user.headers).status_code == 404
    )
    assert (
        client.post(
            "/api/ask", json={"question": "hi"}, headers=user.headers
        ).status_code == 404
    )
    assert (
        client.delete(
            "/api/conversations/does-not-exist", headers=user.headers
        ).status_code == 404
    )


# ---------------------------------------------------------------------- U4
def test_admin_mutations_are_audited(user_factory):
    user = user_factory(client)
    headers = _admin_headers()

    # Knowledge delete is audited (the admin route reports its result).
    deleted = client.delete("/api/admin/knowledge/no-such-id", headers=headers)
    assert deleted.status_code == 200

    # AI config PUT with an invalid provider is audited as rejected …
    rejected = client.put(
        "/api/admin/ai-config",
        json={"provider": "nope", "model": "x"},
        headers=headers,
    )
    assert rejected.status_code == 400

    # … and a valid switch is audited as success.
    switched = client.put(
        "/api/admin/ai-config",
        json={"provider": "rule_based", "model": ""},
        headers=headers,
    )
    assert switched.status_code == 200

    rows = client.get("/api/admin/audit-log", headers=headers).json()["rows"]
    actions = {r["action"] for r in rows}
    assert {"knowledge.delete", "ai_config.update"} <= actions
    rejected_row = next(r for r in rows if r["outcome"] == "rejected")
    assert rejected_row["actor"] == "admin"
    assert rejected_row["resource_type"] == "settings"
    assert "token" not in rejected_row["detail"].lower()
    assert "key" not in rejected_row["detail"].lower()


def test_audit_log_requires_admin(user_factory):
    user = user_factory(client)
    resp = client.get("/api/admin/audit-log", headers=user.headers)
    assert resp.status_code == 401
