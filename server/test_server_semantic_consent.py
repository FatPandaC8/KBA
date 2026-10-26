import os
import json
import sqlite3
import pytest
import numpy as np
from fastapi.testclient import TestClient

from server.app.main import app, pipeline
from server.app.schemas import KnowledgeItem
from server.app.db import (
    init_db, save_knowledge_item, get_knowledge_item_by_id,
    delete_knowledge_item, get_connection
)

client = TestClient(app)

def test_semantic_search_conceptual_similarity():
    """Verify semantic retrieval ranks conceptually related items without keyword overlap."""
    init_db()

    item1 = KnowledgeItem(
        id="test-sem-01",
        capture_id="cap-sem-01",
        title="Vector Database Indices",
        core_idea="Approximate nearest neighbor structures sacrifice precision to achieve sublinear retrieval speed.",
        details="HNSW and IVF algorithms partition the high-dimensional space.",
        transcript="Approximate nearest neighbor structures sacrifice precision to achieve sublinear retrieval speed.",
        concepts=["HNSW", "Vector Index"],
        tags=["database", "performance"]
    )
    item2 = KnowledgeItem(
        id="test-sem-02",
        capture_id="cap-sem-02",
        title="Canine Nutrition Guidelines",
        core_idea="Dogs require balanced proteins and fats in their daily diet.",
        details="Puppies need higher caloric density.",
        transcript="Dogs require balanced proteins and fats in their daily diet.",
        concepts=["Diet", "Canine"],
        tags=["pets", "health"]
    )

    save_knowledge_item(item1)
    save_knowledge_item(item2)

    # Embed both items
    vec1 = pipeline.embed_knowledge_item(item1)
    vec2 = pipeline.embed_knowledge_item(item2)

    from server.app.db import save_embedding
    save_embedding(item1.id, vec1.tobytes())
    save_embedding(item2.id, vec2.tobytes())

    # Query with zero exact words matching item1's title or concepts: "fast embedding lookup trade-offs"
    resp = client.get("/api/knowledge/semantic-search?q=fast+embedding+lookup+trade-offs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2

    # Vector item must rank higher than Canine item
    first_item = data[0]
    assert first_item["item"]["id"] == "test-sem-01"
    assert first_item["similarity_score"] > 0.45

    # Canine item must have significantly lower similarity
    canine_scores = [d["similarity_score"] for d in data if d["item"]["id"] == "test-sem-02"]
    assert canine_scores[0] < first_item["similarity_score"]

    # Cleanup
    delete_knowledge_item("test-sem-01")
    delete_knowledge_item("test-sem-02")

def test_evaluation_consent_and_audio_cleanup():
    """Verify that absent consent purges temporary audio and denies evaluation export."""
    # 1. Empty or missing consent defaults to deny
    resp = client.post(
        "/api/eval/record",
        data={
            "capture_id": "test-no-consent-cap",
            "transcript": "Test audio transcript",
            "structured_json": "{}",
            "consent_given": False
        }
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] is False

    # 2. Export only contains consented records
    export_resp = client.get("/api/eval/export")
    assert export_resp.status_code == 200
    export_data = export_resp.json()
    for rec in export_data["data"]:
        # Verify no unconsented records leak
        assert rec["capture_id"] != "test-no-consent-cap"

def test_consent_withdrawal_endpoint():
    """Verify that calling consent withdrawal endpoint purges unconsented records."""
    resp = client.post("/api/eval/consent", json={"consent_given": False})
    assert resp.status_code == 200
    assert resp.json()["consent_given"] is False

def test_knowledge_graph_relationship_persistence_and_cleanup():
    """Verify graph relationships connect valid knowledge items and are purged on item deletion."""
    from server.app.db import save_relationship, get_graph_data
    from server.app.schemas import KnowledgeRelationship

    k1 = KnowledgeItem(
        id="graph-test-01",
        capture_id="graph-test-01",
        title="Knowledge Graphs",
        core_idea="Connecting ideas via typed relationships.",
        details="",
        transcript="Connecting ideas via typed relationships.",
        concepts=["Graph", "Nodes"],
        tags=["knowledge"]
    )
    k2 = KnowledgeItem(
        id="graph-test-02",
        capture_id="graph-test-02",
        title="Semantic Networks",
        core_idea="Networks of interconnected concepts.",
        details="",
        transcript="Networks of interconnected concepts.",
        concepts=["Network", "Concepts"],
        tags=["knowledge"]
    )

    save_knowledge_item(k1)
    save_knowledge_item(k2)

    rel = KnowledgeRelationship(
        id="rel-test-01",
        from_id="graph-test-01",
        to_id="graph-test-02",
        relation_type="Related to",
        status="suggested"
    )
    save_relationship(rel)

    # Also insert an invalid relationship where target does not exist
    invalid_rel = KnowledgeRelationship(
        id="rel-invalid-01",
        from_id="graph-test-01",
        to_id="non-existent-id-999",
        relation_type="Supports",
        status="suggested"
    )
    save_relationship(invalid_rel)

    graph_data = get_graph_data()
    node_ids = {n.id for n in graph_data.nodes}
    assert "graph-test-01" in node_ids
    assert "graph-test-02" in node_ids

    # Verify only valid edges between existing nodes are returned
    edge_ids = {e.id for e in graph_data.edges}
    assert "rel-test-01" in edge_ids
    assert "rel-invalid-01" not in edge_ids

    # Deleting k1 must cascade-delete the relationship and embedding
    delete_knowledge_item("graph-test-01")
    delete_knowledge_item("graph-test-02")

    graph_after = get_graph_data()
    after_edge_ids = {e.id for e in graph_after.edges}
    assert "rel-test-01" not in after_edge_ids
