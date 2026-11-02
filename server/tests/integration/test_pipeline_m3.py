"""M3 pipeline tests (pipeline split, S1/S2): real Postgres, real UoW, real
rule-based extraction through POST /api/text-kb — duplicates, conflicts,
deletion, privacy. Job rows, leases, retries and the worker loop no longer
exist; retrying is the client re-posting the SAME capture_id.
"""

import json

from fastapi.testclient import TestClient

from server.app.main import app

from .m3_support import container, ingest_text, new_capture_id

client = TestClient(app)


def _self_node(graph):
    return next(node for node in graph["nodes"] if node["is_self"])


def _graph_me_links(client, user):
    """Me's non-seed relationships the way the detail sheet shows them."""
    graph = client.get("/api/graph", headers=user.headers).json()
    self_node = _self_node(graph)
    detail = client.get(
        f"/api/graph/entities/{self_node['id']}", headers=user.headers
    ).json()
    return graph, [r for r in detail["relationships"]]


def test_first_person_text_capture_links_entity_to_self(user_factory, monkeypatch):
    """Bug #2 regression (real Postgres, real UoW): a first person capture
    must leave the new entity in the graph, linked to Me."""

    user = user_factory(client)
    ingest_text(client, user, "I met Anna at the cafe yesterday.")

    graph, links = _graph_me_links(client, user)
    anna = [node for node in graph["nodes"] if node["title"] == "Anna"]
    assert anna, f"Anna missing from graph: {[n['title'] for n in graph['nodes'] if n['title'].startswith(('Anna','Me'))]}"

    self_links = [r for r in links if r["from_name"] == "Me" or r["to_name"] == "Me"]
    anna_link = [r for r in self_links if "Anna" in (r["from_name"], r["to_name"])]
    assert anna_link, f"no Me<->Anna link: {links}"

    # exactly one self entity for the user
    assert sum(1 for node in graph["nodes"] if node["is_self"]) == 1

    # cleanup_orphans must not have removed Anna after she lost no relations
    detail = client.get(f"/api/graph/entities/{anna[0]['id']}", headers=user.headers)
    assert detail.status_code == 200


def test_second_capture_reuses_anna_and_adds_new_relation(user_factory, monkeypatch):
    """Bug #2 regression: a second capture must dedup shared entities and add
    the capture's NEW self link."""

    user = user_factory(client)
    ingest_text(client, user, "I met Anna at the cafe yesterday.")
    ingest_text(client, user, "I met Ben at the park today.")

    graph = client.get("/api/graph", headers=user.headers).json()
    annas = [node for node in graph["nodes"] if node["title"] == "Anna"]
    bens = [node for node in graph["nodes"] if node["title"] == "Ben"]
    assert len(annas) == 1, f"Anna duplicated: {[(n['title'], n['id']) for n in graph['nodes'] if 'anna' in n['title'].lower()]}"
    assert len(bens) == 1, "Ben missing or duplicated"

    # two distinct self links, one per capture
    self_links = {
        tuple(sorted((r["from_name"], r["to_name"]))) for r in _graph_me_links(client, user)[1]
    }
    assert {("Anna", "Me"), ("Ben", "Me")} <= self_links, self_links


def test_ingest_is_idempotent_per_capture_id(user_factory):
    """S4a: re-posting the SAME capture_id returns the existing result and
    must NOT create a second capture or duplicate the graph."""
    user = user_factory(client)
    capture_id = ingest_text(client, user, "Echo depends on FastAPI.")
    graph_before = client.get("/api/graph", headers=user.headers).json()

    for _ in range(4):
        replay = client.post(
            "/api/text-kb",
            headers=user.headers,
            json={"capture_id": capture_id, "text": "Echo depends on FastAPI."},
        )
        assert replay.status_code == 200, replay.text

    recordings = client.get("/api/recordings", headers=user.headers).json()
    assert [r["capture_id"] for r in recordings] == [capture_id]
    assert client.get("/api/graph", headers=user.headers).json() == graph_before


def test_client_reads_stay_stable_without_a_job(user_factory):
    """Regression: repeated reads (app reopen) never mutate state; the only
    write path is POST /api/text-kb."""
    user = user_factory(client)
    ingest_text(client, user, "Echo depends on FastAPI.")

    for _ in range(5):
        assert client.get("/api/recordings", headers=user.headers).status_code == 200
        assert client.get("/api/graph", headers=user.headers).status_code == 200
    assert len(
        container().capture_repo.list_recent(limit=50, user_id=user.id)
    ) == 1, "POST /api/text-kb is the only write path"


def test_duplicate_entities_auto_link_above_090_and_flag_between_075_and_090(user_factory):
    user = user_factory(client)
    ingest_text(client, user, "the Echo project depends on FastAPI. Acme Rocket supports FastAPI.")

    # Second capture: similar entities should auto-link (>=0.90) or be flagged (0.75-0.90)
    ingest_text(client, user, "the Echo project matters. Acme Rocket Labs is promising.")

    entities = container().entity_repo.get_all(user_id=user.id)
    echo_projects = [e for e in entities if e.normalized_name == "echo project"]
    assert len(echo_projects) == 1, ">= 0.90 must auto-link instead of duplicating"

    flagged = container().duplicate_repo.list_flagged(user.id)
    assert flagged, "0.75-0.90 must be recorded for the user to decide"
    scores = [entry["score"] for entry in flagged]
    assert all(0.75 <= score < 0.90 for score in scores)


def test_contradicting_edges_are_both_kept_and_marked(user_factory, monkeypatch):
    user = user_factory(client)
    ingest_text(client, user, "Echo supports FastAPI.")
    ingest_text(client, user, "Echo contradicts FastAPI.")

    graph = client.get("/api/graph", headers=user.headers).json()
    edges = graph["edges"]
    types = {edge["type"] for edge in edges}
    assert "Supports" in types and "Contradicts" in types
    assert any(edge["certainty"] == "conflicting" for edge in edges)


def test_deleting_one_record_keeps_entities_still_supported_by_another(user_factory, monkeypatch):
    user = user_factory(client)
    first = ingest_text(client, user, "Echo depends on FastAPI.")
    second = ingest_text(client, user, "Echo supports Alice.")

    names = {n.title for n in container().graph_query_uc.get_graph(user.id).nodes}
    assert {"Echo", "FastAPI", "Alice"} <= names

    assert client.delete(f"/api/captures/{first}", headers=user.headers).status_code == 200
    names = {n.title for n in container().graph_query_uc.get_graph(user.id).nodes}
    assert "Echo" in names, "shared entity must survive"
    assert "FastAPI" not in names

    assert client.delete(f"/api/captures/{second}", headers=user.headers).status_code == 200
    # After all captures deleted, only the self entity remains
    nodes = container().graph_query_uc.get_graph(user.id).nodes
    assert len(nodes) == 1
    assert nodes[0].title == "Me"
    assert nodes[0].kind == "self"


def test_client_responses_never_expose_transcripts(user_factory, monkeypatch):
    """D5/C3: no client-facing endpoint returns the transcript text. The
    upload/status/audio endpoints are removed with the worker."""
    user = user_factory(client)
    ingest_text(client, user, "Echo depends on FastAPI.", new_capture_id())

    knowledge = client.get("/api/knowledge", headers=user.headers).json()
    recordings = client.get("/api/recordings", headers=user.headers).json()
    graph = client.get("/api/graph", headers=user.headers).json()
    entity_id = graph["nodes"][0]["id"]
    detail = client.get(f"/api/graph/entities/{entity_id}", headers=user.headers).json()

    for payload in (knowledge, recordings, graph, detail):
        assert "transcript" not in json.dumps(payload)

    # Payload stays in capture-truth shape (pipeline split): no stage/status.
    assert recordings, "the capture is listed"
    assert "stage" not in recordings[0]
    capture_id = recordings[0]["capture_id"]
    assert client.get(
        f"/api/recordings/{capture_id}/status", headers=user.headers
    ).status_code == 404
    assert client.get(
        f"/api/recordings/{capture_id}/audio", headers=user.headers
    ).status_code == 404
    assert client.post("/api/captures/upload", headers=user.headers).status_code in (404, 405)
