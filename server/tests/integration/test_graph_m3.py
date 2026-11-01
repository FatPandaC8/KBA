"""M3 graph tests: clustering, layout budget, search, entity management, tombstones."""

import json
import time
import uuid

from fastapi.testclient import TestClient

from server.app.domain.entities import normalize_key
from server.app.main import app

from .m3_support import container, ingest

client = TestClient(app)


def _seed_large_graph(user_id: str, count: int = 2000):
    import psycopg

    from server.tests.postgres_testinfra import worker_database_url

    with psycopg.connect(worker_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            now = "2026-01-01T00:00:00+00:00"
            entity_rows = []
            for index in range(count):
                entity_rows.append(
                    (
                        str(uuid.uuid4()),
                        user_id,
                        None,  # capture_id = NULL
                        f"Node {index}",
                        f"node {index}",
                        "concept",
                        "",
                        0.5,
                        "confirmed",
                        "test",
                        "test",
                        "test",
                        False,
                        now,
                        now,
                    )
                )
            cur.executemany(
                """
                INSERT INTO entities
                (id, user_id, capture_id, name, normalized_name, entity_type, description,
                 confidence, certainty, provenance, provider_id, model_version,
                 user_edited, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                entity_rows,
            )
            relation_rows = []
            for index in range(count - 1):
                relation_rows.append(
                    (
                        str(uuid.uuid4()),
                        user_id,
                        entity_rows[index][0],
                        entity_rows[index + 1][0],
                        "Related to",
                        "suggested",
                        0.6,
                        "confirmed",
                        None,  # source_capture_id = NULL
                        "test",  # provenance
                        False,  # user_edited
                        now,
                    )
                )
            cur.executemany(
                """
                INSERT INTO relationships
                (id, user_id, from_id, to_id, relation_type, status, confidence,
                 certainty, source_capture_id, provenance, user_edited, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                relation_rows,
            )
            return entity_rows



def test_graph_layout_is_clustered_and_deterministic(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI. Alice supports Echo.", monkeypatch)

    first = client.get("/api/graph", headers=user.headers).json()
    second = client.get("/api/graph", headers=user.headers).json()

    assert first == second
    assert first["nodes"] and first["edges"] and first["clusters"]
    assert sum(cluster["size"] for cluster in first["clusters"]) == len(first["nodes"])
    for node in first["nodes"]:
        assert node["cluster_id"]
        assert -2000 <= node["x"] <= 3000 and -2000 <= node["y"] <= 3000
        assert node["certainty"] in {"confirmed", "uncertain", "conflicting"}


def test_graph_handles_two_thousand_nodes_within_budget(user_factory):
    user = user_factory(client)
    _seed_large_graph(user.id, count=2000)

    started = time.perf_counter()
    response = client.get("/api/graph", headers=user.headers)
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    body = response.json()
    # +1 for the self entity that is automatically created for each user
    assert len(body["nodes"]) == 2001
    assert len(body["edges"]) == 1999
    assert body["clusters"]
    # Server-side layout must stay interactive for the 2,000 node budget.
    assert elapsed < 5.0, f"graph layout took {elapsed:.2f}s"
    size = len(json.dumps(body))
    assert size < 5 * 1024 * 1024, f"graph payload is {size} bytes"


def test_graph_search_finds_entities_by_name_and_prefix(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI.", monkeypatch)

    result = client.get("/api/graph/search", params={"q": "Fast"}, headers=user.headers)
    assert result.status_code == 200
    names = [item["entity"]["name"] for item in result.json()["entities"]]
    assert "FastAPI" in names
    assert "transcript" not in result.text

    empty = client.get("/api/graph/search", params={"q": "  "}, headers=user.headers)
    assert empty.json() == {"entities": [], "relationships": []}


def test_graph_search_does_not_match_everything_for_an_unrelated_query(
    user_factory, monkeypatch
):
    """Semantic similarity alone must not turn search into a "return all" call."""
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI. Alice supports Echo.", monkeypatch)

    unrelated = client.get(
        "/api/graph/search", params={"q": "What is my blood type?"}, headers=user.headers
    )
    assert unrelated.status_code == 200
    assert unrelated.json() == {"entities": [], "relationships": []}

    # A real match still works, by token and by name.
    matched = client.get(
        "/api/graph/search", params={"q": "FastAPI"}, headers=user.headers
    ).json()
    assert [item["entity"]["name"] for item in matched["entities"]] == ["FastAPI"]


def test_entity_detail_update_and_delete(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI.", monkeypatch)
    graph = client.get("/api/graph", headers=user.headers).json()
    target = next(node for node in graph["nodes"] if node["title"] == "FastAPI")

    detail = client.get(f"/api/graph/entities/{target['id']}", headers=user.headers)
    assert detail.status_code == 200
    assert detail.json()["entity"]["id"] == target["id"]
    assert detail.json()["relationships"]

    updated = client.patch(
        f"/api/graph/entities/{target['id']}",
        json={"name": "FastAPI v2", "description": "Backend framework"},
        headers=user.headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "FastAPI v2"
    assert updated.json()["description"] == "Backend framework"

    assert client.delete(f"/api/graph/entities/{target['id']}", headers=user.headers).status_code == 200
    assert client.get(f"/api/graph/entities/{target['id']}", headers=user.headers).status_code == 404
    assert client.delete(f"/api/graph/entities/{target['id']}", headers=user.headers).status_code == 404


def test_deleted_entity_is_not_recreated_by_later_captures(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Alice supports Echo.", monkeypatch)
    graph = client.get("/api/graph", headers=user.headers).json()
    alice = next(node for node in graph["nodes"] if node["title"] == "Alice")

    assert client.delete(f"/api/graph/entities/{alice['id']}", headers=user.headers).status_code == 200
    assert container().tombstone_repo.is_tombstoned(user.id, "entity", normalize_key("Alice"))

    ingest(client, user, "Alice supports Echo again.", monkeypatch)
    names = {node["title"] for node in client.get("/api/graph", headers=user.headers).json()["nodes"]}
    assert "Alice" not in names


def test_graph_is_scoped_to_the_owner(user_factory, monkeypatch):
    alice = user_factory(client)
    bob = user_factory(client)
    ingest(client, alice, "Alice supports Echo.", monkeypatch)
    alice_node = client.get("/api/graph", headers=alice.headers).json()["nodes"][0]

    # Bob's graph should only contain his self entity (no other nodes)
    bob_graph = client.get("/api/graph", headers=bob.headers).json()
    assert len(bob_graph["nodes"]) == 1
    assert bob_graph["nodes"][0]["title"] == "Me"
    assert bob_graph["nodes"][0]["kind"] == "self"
    assert bob_graph["edges"] == []
    assert (
        client.get(f"/api/graph/entities/{alice_node['id']}", headers=bob.headers).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/graph/entities/{alice_node['id']}",
            json={"name": "Stolen"},
            headers=bob.headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/graph/entities/{alice_node['id']}", headers=bob.headers).status_code
        == 404
    )
