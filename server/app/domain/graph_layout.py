"""Shared graph layout computation for both SQLite and PostgreSQL repositories.

This module provides deterministic community detection and layout for the graph canvas.
Label propagation runs over the entity graph. Unconnected nodes are grouped
by entity type so a sparse graph still renders as readable clusters. Output
is stable for the same data set, which keeps client-side caches valid.
"""

import math
from typing import Any, Dict, List, Tuple

from server.app.application.dto import GraphDataDTO, GraphClusterDTO, GraphEdgeDTO, GraphNodeDTO


def _cos(value: float) -> float:
    return math.cos(value)


def _sin(value: float) -> float:
    return math.sin(value)


def _plural_label(entity_type: str) -> str:
    """Map entity type to a plural label for clusters."""
    return {
        "person": "People",
        "project": "Projects",
        "concept": "Concepts",
        "place": "Places",
        "organization": "Organizations",
        "tool": "Tools",
        "event": "Events",
        "self": "Self",
    }.get(entity_type.lower(), entity_type.capitalize() + "s")


def compute_graph_layout(
    entity_rows: List[Dict[str, Any]],
    rel_rows: List[Dict[str, Any]],
) -> Tuple[List[Any], List[Any], List[Any]]:
    """Deterministic community detection and layout for the graph canvas.

    Label propagation runs over the entity graph. Unconnected nodes are grouped
    by entity type so a sparse graph still renders as readable clusters. Output
    is stable for the same data set, which keeps client-side caches valid.

    Args:
        entity_rows: List of entity dicts with keys: id, name, entity_type, certainty, confidence, is_self
        rel_rows: List of relationship dicts with keys: id, from_id, to_id, relation_type, status, certainty, confidence

    Returns:
        Tuple of (nodes, edges, clusters) as DTOs
    """
    entity_ids = [row["id"] for row in entity_rows]
    entity_by_id = {row["id"]: row for row in entity_rows}

    adjacency: Dict[str, set] = {eid: set() for eid in entity_ids}
    valid_edges: List[Any] = []
    for rel in rel_rows:
        source, target = rel["from_id"], rel["to_id"]
        if source in entity_by_id and target in entity_by_id and source != target:
            adjacency[source].add(target)
            adjacency[target].add(source)
            valid_edges.append(rel)

    labels: Dict[str, str] = {eid: eid for eid in entity_ids}
    # At most 8 passes keeps this linear-ish for the 2,000-node budget.
    for _ in range(8):
        changed = False
        for eid in entity_ids:
            neighbours = adjacency[eid]
            if not neighbours:
                continue
            counts: Dict[str, int] = {}
            for neighbour in neighbours:
                label = labels[neighbour]
                counts[label] = counts.get(label, 0) + 1
            best_label = min(counts.items(), key=lambda item: (-item[1], item[0]))[0]
            if counts[best_label] > counts.get(labels[eid], 0):
                labels[eid] = best_label
                changed = True
            if not changed:
                break

    members: Dict[str, List[str]] = {}
    for eid in entity_ids:
        if adjacency[eid]:
            members.setdefault(f"community:{labels[eid]}", []).append(eid)
        else:
            row = entity_by_id[eid]
            members.setdefault(f"type:{(row['entity_type'] or 'concept').lower()}", []).append(eid)

    ordered = sorted(members.items(), key=lambda item: (-len(item[1]), item[0]))
    total = max(1, len(ordered))
    clusters: List[GraphClusterDTO] = []
    positions: Dict[str, Tuple[float, float]] = {}

    for index, (key, ids) in enumerate(ordered):
        angle = (2 * math.pi * index) / total
        ring = 0.0 if total == 1 else 330.0
        cx = 500.0 + ring * math.cos(angle)
        cy = 500.0 + ring * math.sin(angle)
        if key.startswith("type:"):
            label = _plural_label(key.split(":", 1)[1])
        else:
            type_counts: Dict[str, int] = {}
            for eid in ids:
                etype = (entity_by_id[eid]["entity_type"] or "concept").lower()
                type_counts[etype] = type_counts.get(etype, 0) + 1
            dominant = max(sorted(type_counts.items()), key=lambda item: item[1])[0]
            label = _plural_label(dominant)
        clusters.append(GraphClusterDTO(id=str(key), label=label, x=cx, y=cy, size=len(ids)))
        for member_index, eid in enumerate(sorted(ids)):
            if len(ids) == 1:
                px, py = cx, cy
            else:
                # Golden-angle spiral keeps dense communities separated.
                radius = min(215.0, 14.0 * (member_index + 1) ** 0.5)
                theta = member_index * 2.399963229728653
                px = cx + radius * math.cos(theta)
                py = cy + radius * math.sin(theta)
            positions[eid] = (round(px, 2), round(py, 2))

    degree: Dict[str, int] = {eid: len(adjacency[eid]) for eid in entity_ids}
    cluster_for: Dict[str, str] = {}
    for key, ids in members.items():
        for eid in ids:
            cluster_for[eid] = key

    nodes: List[GraphNodeDTO] = []
    for eid in entity_ids:
        row = entity_by_id[eid]
        x, y = positions.get(eid, (500.0, 500.0))
        nodes.append(GraphNodeDTO(
            id=str(eid),
            title=row["name"],
            kind=row["entity_type"] or "concept",
            x=x,
            y=y,
            cluster_id=cluster_for.get(eid, ""),
            certainty=row["certainty"] if "certainty" in row.keys() and row["certainty"] else "confirmed",
            confidence=float(row["confidence"]) if "confidence" in row.keys() and row["confidence"] is not None else 0.5,
            degree=degree.get(eid, 0),
            is_self=bool(row["is_self"]) if "is_self" in row.keys() else False,
        ))

    edges: List[GraphEdgeDTO] = []
    for rel in valid_edges:
        rel_keys = rel.keys()
        edges.append(GraphEdgeDTO(
            id=str(rel["id"]),
            from_node=str(rel["from_id"]),
            to_node=str(rel["to_id"]),
            type=rel["relation_type"],
            status=rel["status"],
            certainty=rel["certainty"] if "certainty" in rel_keys and rel["certainty"] else "confirmed",
            confidence=float(rel["confidence"]) if "confidence" in rel_keys and rel["confidence"] is not None else 0.6,
            evidence=(rel["evidence_utterance"] or "") if "evidence_utterance" in rel_keys else "",
        ))
    return nodes, edges, clusters