"""Graph-render metrics (pinned definitions; commit before any fix run).

Usage:
  python e2e/graph_metrics.py http://127.0.0.1:8000 EMAIL PASSWORD [--json PATH]

Logs the EXISTING user in (no signup) and calls GET /api/graph; prints one
JSON object with these pinned definitions:
- nodes_n, edges_n                - raw response counts
- edges_ok / edges_missing_n      - edge endpoint match BY STRING ID only
                                    (node.id vs junction id, no casting)
- endpoint_examples               - up to 3 mismatching junction ids, raw
                                    repr + python type
- node_id_types                   - python types of node ids in this payload
- nearest_pair min/median/max     - Euclidean nearest-PAIR distance across
                                    all node pairs on the server (x, y)
- identical_coord_nodes           - nodes sharing EXACT (x == x, y == y)
- bbox                            - min/max of server x and y
Never mutates: GET and auth only.
"""

import json
import statistics
import sys
import urllib.request

API = sys.argv[1]
EMAIL = sys.argv[2]
PASSWORD = sys.argv[3]
OUT = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None


def call(path, *, method="POST", payload=None, headers=None, body=None):
    data = body if body is not None else (
        json.dumps(payload).encode() if payload is not None else None
    )
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=60) as res:
        raw = res.read()
        return json.loads(raw.decode()) if raw else {}


login = call("/api/auth/login", payload={"email": EMAIL, "password": PASSWORD})
token = login["token"]

call("/api/consent", payload={"granted": True}, headers={"Authorization": f"Bearer {token}"})
graph = call("/api/graph", method="GET", headers={"Authorization": f"Bearer {token}"})

nodes = graph.get("nodes") or []
edges = graph.get("edges") or []
node_ids = {n["id"] for n in nodes}
node_ids_repr = {repr(n["id"]): type(n["id"]).__name__ for n in nodes[:20]}

missing = [e for e in edges if e.get("from_node") not in node_ids or e.get("to_node") not in node_ids]
examples = []
for e in missing[:3]:
    for key in ("from_node", "to_node"):
        if e.get(key) not in node_ids:
            examples.append(
                {
                    "edge_id": e.get("id"),
                    "junction": key,
                    "value_repr": repr(e.get(key)),
                    "value_type": type(e.get(key)).__name__,
                }
            )

# nearest-pair distances (symmetric; each unordered pair once)
dists = []
for i in range(len(nodes)):
    for j in range(i + 1, len(nodes)):
        dx = nodes[i]["x"] - nodes[j]["x"]
        dy = nodes[i]["y"] - nodes[j]["y"]
        dists.append((dx * dx + dy * dy) ** 0.5)

coords = [(n["x"], n["y"]) for n in nodes]
identical = 0
seen = {}
for c in coords:
    seen[c] = seen.get(c, 0) + 1
identical = sum(v for v in seen.values() if v > 1)

metrics = {
    "user": EMAIL,
    "nodes_n": len(nodes),
    "edges_n": len(edges),
    "edges_ok": len(edges) - len(missing),
    "edges_missing_n": len(missing),
    "endpoint_examples": examples,
    "node_id_types": sorted(set(node_ids_repr.values())),
    "nearest_pair_min": round(min(dists), 2) if dists else None,
    "nearest_pair_median": round(statistics.median(dists), 2) if dists else None,
    "nearest_pair_max": round(max(dists), 2) if dists else None,
    "identical_coord_nodes": identical,
    "bbox": {
        "min_x": min((n["x"] for n in nodes), default=None),
        "max_x": max((n["x"] for n in nodes), default=None),
        "min_y": min((n["y"] for n in nodes), default=None),
        "max_y": max((n["y"] for n in nodes), default=None),
    },
}
if OUT:
    with open(OUT, "w") as fh:
        json.dump(metrics, fh, indent=2)
print(json.dumps(metrics, indent=2))
