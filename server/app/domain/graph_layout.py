"""Deterministic graph layout (pure domain module, ADR R6).

Input is plain rows from the persistence read path; output is plain dicts.
NO DTO imports and no persistence imports: the application
``GraphQueryService`` maps the result onto the API response shape. Label
propagation runs over the entity graph, unconnected nodes group by entity
type, and output is stable for the same data set so client caches stay valid.
"""

import math
from typing import Any, Dict, List, Tuple

_TYPE_PLURALS = {
    "person": "People",
    "project": "Projects",
    "organization": "Organizations",
    "place": "Places",
    "concept": "Concepts",
    "tool": "Tools",
    "idea": "Ideas",
    "event": "Events",
    "self": "Self",
}


def _plural_label(entity_type: str) -> str:
    low = (entity_type or "concept").lower()
    return _TYPE_PLURALS.get(low, low.capitalize() + "s")


def compute_layout(
    entity_rows: List[Dict[str, Any]],
    rel_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deterministic community detection and layout for the graph canvas."""
    entity_ids = [str(row["id"]) for row in entity_rows]
    entity_by_id = {str(row["id"]): row for row in entity_rows}

    adjacency: Dict[str, set] = {eid: set() for eid in entity_ids}
    valid_edges: List[Dict[str, Any]] = []
    for rel in rel_rows:
        source, target = str(rel["from_id"]), str(rel["to_id"])
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
            members.setdefault(
                f"type:{(row.get('entity_type') or 'concept').lower()}", []
            ).append(eid)

    ordered = sorted(members.items(), key=lambda item: (-len(item[1]), item[0]))
    total = max(1, len(ordered))
    clusters: List[Dict[str, Any]] = []
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
                etype = (entity_by_id[eid].get("entity_type") or "concept").lower()
                type_counts[etype] = type_counts.get(etype, 0) + 1
            dominant = max(sorted(type_counts.items()), key=lambda item: item[1])[0]
            label = _plural_label(dominant)
        clusters.append({"id": key, "label": label, "x": cx, "y": cy, "size": len(ids)})
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

    nodes: List[Dict[str, Any]] = []
    for eid in entity_ids:
        row = entity_by_id[eid]
        x, y = positions.get(eid, (500.0, 500.0))
        nodes.append(
            {
                "id": eid,
                "title": row.get("name") or "",
                "kind": row.get("entity_type") or "concept",
                "x": x,
                "y": y,
                "cluster_id": cluster_for.get(eid, ""),
                "certainty": row.get("certainty") or "confirmed",
                "confidence": float(row["confidence"]) if row.get("confidence") is not None else 0.5,
                "degree": degree.get(eid, 0),
                "is_self": bool(row.get("is_self", False)),
            }
        )

    edges: List[Dict[str, Any]] = []
    for rel in valid_edges:
        confidence = rel.get("confidence")
        edges.append(
            {
                "id": str(rel["id"]),
                "from_node": str(rel["from_id"]),
                "to_node": str(rel["to_id"]),
                "type": rel.get("relation_type"),
                "status": rel.get("status"),
                "certainty": rel.get("certainty") or "confirmed",
                "confidence": float(confidence) if confidence is not None else 0.6,
                "evidence": rel.get("evidence_utterance") or "",
            }
        )

    return nodes, edges, clusters
