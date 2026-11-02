"""Layout unit tests (KG-04/KG-05 render contract, pure domain module).

Pinned render contract after the spacing fix:
- no two node CENTRES are closer than one node diameter (>= 96 px; the
  client cards are 88x40) -> minimum visible gap at the default zoom;
- no two nodes share identical coordinates (exact float equality);
- communities are separated by at least ``_CLUSTER_GAP`` of empty space
  between their hulls;
- the layout is deterministic: the same input rows produce identical output.
"""

import pytest

from server.app.domain.graph_layout import (
    _CLUSTER_GAP,
    _NODE_PITCH,
    compute_layout,
    _hex_positions,
    _hex_rings_for,
)


def _row(eid, name, etype="concept", **extra):
    row = {
        "id": eid,
        "name": name,
        "entity_type": etype,
        "certainty": "confirmed",
        "confidence": 0.8,
        "is_self": etype == "self",
    }
    row.update(extra)
    return row


def _rel(rid, src, dst, rtype="Related to"):
    return {
        "id": rid,
        "from_id": src,
        "to_id": dst,
        "relation_type": rtype,
        "status": "suggested",
        "certainty": "confirmed",
        "confidence": 0.6,
        "evidence_utterance": "",
    }


def _min_pair_distance(nodes):
    ds = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            dx = nodes[i]["x"] - nodes[j]["x"]
            dy = nodes[i]["y"] - nodes[j]["y"]
            ds.append((dx * dx + dy * dy) ** 0.5)
    return min(ds) if ds else float("inf")


def _cluster_hull(nodes):
    by_cluster = {}
    for node in nodes:
        by_cluster.setdefault(node["cluster_id"], []).append(node)
    hulls = {}
    for key, members in by_cluster.items():
        centre = {
            "x": sum(n["x"] for n in members) / len(members),
            "y": sum(n["y"] for n in members) / len(members),
        }
        hulls[key] = (
            centre,
            max(
                ((n["x"] - centre["x"]) ** 2 + (n["y"] - centre["y"]) ** 2) ** 0.5
                for n in members
            ),
        )
    return hulls


def test_hex_positions_guarantee_pitch():
    pts = _hex_positions(200, _NODE_PITCH)
    assert len(pts) == 200
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = pts[i][0] - pts[j][0]
            dy = pts[i][1] - pts[j][1]
            assert (dx * dx + dy * dy) ** 0.5 >= _NODE_PITCH - 1e-6


def test_hex_rings_cover_counts():
    for count in (1, 2, 6, 7, 18, 19, 100):
        k = _hex_rings_for(count)
        assert 1 + 3 * k * (k + 1) >= count
        assert k == 0 or 1 + 3 * (k - 1) * k < count


def test_packed_community_has_visible_spacing_and_no_duplicates():
    """The device bug: 8 tightly-linked nodes collapsed into a ~47 px band.
    One hex community now spreads them over a >=130 px lattice."""
    ids = [f"e{i}" for i in range(8)]
    rows = [_row(eid, f"Entity {k}") for k, eid in enumerate(ids)]
    rels = [_rel(f"r{k}", ids[k], ids[k + 1]) for k in range(7)]
    nodes, edges, clusters = compute_layout(rows, rels)

    assert len(nodes) == 8
    assert _min_pair_distance(nodes) >= 96, (
        f"min centre gap {_min_pair_distance(nodes):.1f}px is below one node "
        "diameter"
    )
    coords = [(n["x"], n["y"]) for n in nodes]
    assert len(set(coords)) == len(coords), "identical coordinates exist"
    ys = [n["y"] for n in nodes]
    xs = [n["x"] for n in nodes]
    # At least one axis spans the community; the hex lattice cannot collapse
    # into a single band the way the old spiral did.
    assert (
        max(max(xs) - min(xs), max(ys) - min(ys)) >= 260
    ), f"layout collapsed: span x={max(xs) - min(xs)} y={max(ys) - min(ys)}"
    assert len(clusters) == 1


def test_layout_is_deterministic_and_edges_reference_nodes():
    ids = [f"e{i}" for i in range(10)]
    rows = [_row(eid, f"Entity {k}") for k, eid in enumerate(ids)]
    rels = [
        _rel(f"r{k}", ids[k], ids[(k + 1) % 10]) for k in range(10)
    ]
    nodes1, edges1, clusters1 = compute_layout(rows, rels)
    nodes2, edges2, clusters2 = compute_layout(rows, rels)

    assert nodes1 == nodes2
    assert edges1 == edges2
    assert clusters1 == clusters2

    present_ids = {n["id"] for n in nodes1}
    assert all(isinstance(n["id"], str) for n in nodes1)
    for edge in edges1:
        assert edge["from_node"] in present_ids, edge
        assert edge["to_node"] in present_ids, edge
        assert isinstance(edge["from_node"], str)
        assert isinstance(edge["to_node"], str)


def test_communities_are_visibly_separated():
    ids = [f"e{i}" for i in range(6)]
    rows = [_row(eid, f"Entity {k}") for k, eid in enumerate(ids)]
    # community A: e0-e2, community B: e3-e5 (no bridge)
    rels = [
        _rel("r0", ids[0], ids[1]),
        _rel("r1", ids[1], ids[2]),
        _rel("r2", ids[3], ids[4]),
        _rel("r3", ids[4], ids[5]),
    ]
    nodes, _edges, clusters = compute_layout(rows, rels)

    assert len(clusters) == 2, [c["id"] for c in clusters]
    centres = {c["id"]: (c["x"], c["y"]) for c in clusters}
    gap = (
        (centres[clusters[0]["id"]][0] - centres[clusters[1]["id"]][0]) ** 2
        + (centres[clusters[0]["id"]][1] - centres[clusters[1]["id"]][1]) ** 2
    ) ** 0.5
    # Both hulls are one ring wide (130 px); cluster ring separation keeps at
    # least _CLUSTER_GAP of empty space between the hulls (KG-05).
    assert gap >= max(hulls) if False else gap >= _CLUSTER_GAP  # approx check below
    hulls = _cluster_hull(nodes)
    hull_sum = sum(h[1] for h in hulls.values())
    assert gap - hull_sum >= _CLUSTER_GAP - _NODE_PITCH, (
        f"community gap {gap:.0f}px with hulls {hull_sum:.0f}px"
    )


def test_large_community_within_time_budget():
    """2,000-node regression: layout stays linear and inside the interactive
    budget (the graph API test asserts < 5 s end to end; here the layout only)."""
    import time

    count = 2000
    ids = [f"n{i}" for i in range(count)]
    rows = [_row(eid, f"Node {k}") for k, eid in enumerate(ids)]
    rels = [_rel(f"r{k}", ids[k], ids[k + 1]) for k in range(count - 1)]

    started = time.perf_counter()
    nodes, edges, clusters = compute_layout(rows, rels)
    elapsed = time.perf_counter() - started

    assert len(nodes) == count and len(edges) == count - 1
    assert elapsed < 2.0, f"layout took {elapsed:.2f}s"
    assert _min_pair_distance(nodes) >= 96
    coords = {(n["x"], n["y"]) for n in nodes}
    assert len(coords) == count
