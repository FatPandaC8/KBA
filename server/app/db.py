import sqlite3
import json
import os
from typing import List, Optional, Dict, Any
from .schemas import KnowledgeItem, KnowledgeRelationship, GraphData, GraphNode, GraphEdge

DB_PATH = os.environ.get("ECHO_DB_PATH", "server/echo_backend.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS captures (
        id TEXT PRIMARY KEY,
        idempotency_key TEXT UNIQUE,
        audio_path TEXT,
        duration_ms INTEGER,
        status TEXT,
        created_at TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_items (
        id TEXT PRIMARY KEY,
        capture_id TEXT UNIQUE,
        title TEXT,
        core_idea TEXT,
        details TEXT DEFAULT '',
        transcript TEXT,
        concepts TEXT,
        tags TEXT,
        open_questions TEXT,
        candidate_relations TEXT DEFAULT '[]',
        provenance TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    # Migration if columns don't exist
    try:
        c.execute("ALTER TABLE knowledge_items ADD COLUMN details TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE knowledge_items ADD COLUMN candidate_relations TEXT DEFAULT '[]'")
    except Exception:
        pass
    c.execute("""
    CREATE TABLE IF NOT EXISTS relationships (
        id TEXT PRIMARY KEY,
        from_id TEXT,
        to_id TEXT,
        relation_type TEXT,
        status TEXT,
        created_at TEXT,
        UNIQUE(from_id, to_id, relation_type)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS model_eval_records (
        id TEXT PRIMARY KEY,
        capture_id TEXT,
        transcript TEXT,
        structured_json TEXT,
        user_corrected INTEGER DEFAULT 0,
        consent_given INTEGER DEFAULT 0,
        pipeline_version TEXT,
        created_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def save_capture(capture_id: str, idempotency_key: str, audio_path: str, duration_ms: int, status: str = "received"):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT OR IGNORE INTO captures (id, idempotency_key, audio_path, duration_ms, status, created_at)
    VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (capture_id, idempotency_key, audio_path, duration_ms, status))
    conn.commit()
    conn.close()

def save_knowledge_item(item: KnowledgeItem):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO knowledge_items
    (id, capture_id, title, core_idea, details, transcript, concepts, tags, open_questions, candidate_relations, provenance, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item.id,
        item.capture_id,
        item.title,
        item.core_idea,
        item.details,
        item.transcript,
        json.dumps(item.concepts),
        json.dumps(item.tags),
        json.dumps(item.open_questions),
        json.dumps(item.candidate_relations),
        item.provenance,
        item.created_at,
        item.updated_at
    ))
    conn.commit()
    conn.close()

def save_relationship(rel: KnowledgeRelationship):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT OR IGNORE INTO relationships (id, from_id, to_id, relation_type, status, created_at)
    VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (rel.id, rel.from_id, rel.to_id, rel.relation_type, rel.status))
    conn.commit()
    conn.close()

def update_relationship_status(rel_id: str, status: str, relation_type: Optional[str] = None):
    conn = get_connection()
    c = conn.cursor()
    if relation_type:
        c.execute("UPDATE relationships SET status = ?, relation_type = ? WHERE id = ?", (status, relation_type, rel_id))
    else:
        c.execute("UPDATE relationships SET status = ? WHERE id = ?", (status, rel_id))
    conn.commit()
    conn.close()

def delete_relationship(rel_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))
    conn.commit()
    conn.close()

def get_all_knowledge_items(query: str = "") -> List[KnowledgeItem]:
    conn = get_connection()
    c = conn.cursor()
    if query:
        pattern = f"%{query}%"
        rows = c.execute("""
        SELECT * FROM knowledge_items
        WHERE title LIKE ? OR core_idea LIKE ? OR transcript LIKE ? OR concepts LIKE ? OR tags LIKE ?
        ORDER BY created_at DESC
        """, (pattern, pattern, pattern, pattern, pattern)).fetchall()
    else:
        rows = c.execute("SELECT * FROM knowledge_items ORDER BY created_at DESC").fetchall()
    
    items = []
    for r in rows:
        items.append(KnowledgeItem(
            id=r["id"],
            capture_id=r["capture_id"],
            title=r["title"],
            core_idea=r["core_idea"],
            details=r["details"] if "details" in r.keys() and r["details"] else "",
            transcript=r["transcript"],
            concepts=json.loads(r["concepts"] or "[]"),
            tags=json.loads(r["tags"] or "[]"),
            open_questions=json.loads(r["open_questions"] or "[]"),
            candidate_relations=json.loads(r["candidate_relations"] or "[]") if "candidate_relations" in r.keys() and r["candidate_relations"] else [],
            provenance=r["provenance"],
            created_at=r["created_at"],
            updated_at=r["updated_at"]
        ))
    conn.close()
    return items

def get_knowledge_item_by_id(item_id: str) -> Optional[KnowledgeItem]:
    conn = get_connection()
    c = conn.cursor()
    r = c.execute("SELECT * FROM knowledge_items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not r:
        return None
    return KnowledgeItem(
        id=r["id"],
        capture_id=r["capture_id"],
        title=r["title"],
        core_idea=r["core_idea"],
        details=r["details"] if "details" in r.keys() and r["details"] else "",
        transcript=r["transcript"],
        concepts=json.loads(r["concepts"] or "[]"),
        tags=json.loads(r["tags"] or "[]"),
        open_questions=json.loads(r["open_questions"] or "[]"),
        candidate_relations=json.loads(r["candidate_relations"] or "[]") if "candidate_relations" in r.keys() and r["candidate_relations"] else [],
        provenance=r["provenance"],
        created_at=r["created_at"],
        updated_at=r["updated_at"]
    )

def delete_knowledge_item(item_id: str):
    conn = get_connection()
    c = conn.cursor()
    # Find matching items to get their IDs for relationship cleanup
    rows = c.execute("SELECT id FROM knowledge_items WHERE id = ? OR capture_id = ?", (item_id, item_id)).fetchall()
    target_ids = [r["id"] for r in rows]
    if item_id not in target_ids:
        target_ids.append(item_id)

    for tid in target_ids:
        c.execute("DELETE FROM knowledge_items WHERE id = ?", (tid,))
        c.execute("DELETE FROM relationships WHERE from_id = ? OR to_id = ?", (tid, tid))
    conn.commit()
    conn.close()

def get_graph_data() -> GraphData:
    items = get_all_knowledge_items()
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM relationships").fetchall()
    conn.close()

    nodes: List[GraphNode] = []
    # Fixed coordinate map layout inspired by Figma
    coord_presets = [
        (155.0, 128.0),
        (45.0, 50.0),
        (242.0, 48.0),
        (250.0, 212.0),
        (35.0, 220.0),
        (145.0, 278.0),
        (80.0, 150.0),
        (210.0, 160.0),
    ]

    for idx, item in enumerate(items):
        coord = coord_presets[idx % len(coord_presets)]
        nodes.append(GraphNode(
            id=item.id,
            title=item.title,
            kind="capture" if idx % 2 == 0 else "idea",
            x=coord[0],
            y=coord[1]
        ))

    node_ids = {n.id for n in nodes}
    edges: List[GraphEdge] = []
    for r in rows:
        if r["from_id"] in node_ids and r["to_id"] in node_ids:
            edges.append(GraphEdge(
                id=r["id"],
                from_node=r["from_id"],
                to_node=r["to_id"],
                type=r["relation_type"],
                status=r["status"]
            ))

    return GraphData(nodes=nodes, edges=edges)
