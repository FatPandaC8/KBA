import os
import json
import uuid
import datetime
from typing import List, Optional
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from .schemas import (
    KnowledgeItem, KnowledgeRelationship, GraphData,
    CaptureUploadResponse, EvalExportRecord, ScoredKnowledgeItem,
    ConsentUpdateRequest
)
from .db import (
    init_db, save_capture, save_knowledge_item, save_relationship,
    update_relationship_status, delete_relationship,
    get_all_knowledge_items, get_knowledge_item_by_id, delete_knowledge_item,
    get_graph_data, get_connection, save_embedding, get_all_embeddings, delete_embedding
)
from .pipeline import ExtractionPipeline, PIPELINE_VERSION

app = FastAPI(title="Echo Knowledge API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = ExtractionPipeline()

def backfill_embeddings_if_needed():
    """Generates embeddings for any knowledge items that do not yet have one stored."""
    items = get_all_knowledge_items()
    stored = {item_id for item_id, _ in get_all_embeddings()}
    for item in items:
        if item.id not in stored:
            try:
                vec = pipeline.embed_knowledge_item(item)
                save_embedding(item.id, vec.tobytes())
            except Exception as e:
                print(f"[Embedding Backfill Error] {e}")

@app.on_event("startup")
def startup():
    init_db()
    backfill_embeddings_if_needed()

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Echo Knowledge Backend", "pipeline_version": PIPELINE_VERSION}

@app.post("/api/captures/upload", response_model=CaptureUploadResponse)
async def upload_capture(
    file: UploadFile = File(...),
    capture_id: str = Form(...),
    idempotency_key: str = Form(...),
    duration_ms: int = Form(default=0),
    consent_given: bool = Form(default=False)
):
    upload_dir = "server/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{capture_id}.m4a"
    audio_path = os.path.join(upload_dir, filename)

    contents = await file.read()
    with open(audio_path, "wb") as f:
        f.write(contents)

    save_capture(capture_id, idempotency_key, audio_path if consent_given else "", duration_ms, status="received")

    try:
        # Step 2: Transcribe
        transcript = pipeline.transcribe(audio_path)
        if not transcript or not transcript.strip():
            raise ValueError("No intelligible speech detected in recording.")

        # Step 3: Extract structured knowledge
        knowledge_item, _ = pipeline.extract_knowledge(transcript, capture_id)

        # Step 4: Connect to existing knowledge
        existing_items = get_all_knowledge_items()
        relationships = pipeline.connect_knowledge(knowledge_item, existing_items)

        # Step 5: Persist knowledge and relationships
        save_knowledge_item(knowledge_item)
        for rel in relationships:
            save_relationship(rel)

        # Step 6: Generate and persist dense embedding
        try:
            vec = pipeline.embed_knowledge_item(knowledge_item)
            save_embedding(knowledge_item.id, vec.tobytes())
        except Exception as embed_err:
            print(f"[Embedding Error] {embed_err}")

        # Step 7: Consent-Gated Audio Retention Policy
        # If user did NOT explicitly consent to evaluation retention, delete the audio file immediately.
        if not consent_given:
            if os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception as del_err:
                    print(f"[Audio Retention Cleanup Error] {del_err}")

        return CaptureUploadResponse(
            capture_id=capture_id,
            status="ready",
            knowledge_item=knowledge_item,
            relationships=relationships
        )
    except Exception as e:
        print(f"[Upload Pipeline Error] {e}")
        # Always purge audio on failure if consent is not given
        if not consent_given and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass
        raise HTTPException(
            status_code=422 if isinstance(e, ValueError) else 500,
            detail=str(e)
        )

@app.get("/api/knowledge", response_model=List[KnowledgeItem])
def list_knowledge(q: str = Query(default="")):
    return get_all_knowledge_items(query=q)

@app.get("/api/knowledge/semantic-search", response_model=List[ScoredKnowledgeItem])
def semantic_search(q: str = Query(...), limit: int = Query(default=20, ge=1, le=100)):
    """
    Performs cosine similarity search using dense embeddings across all knowledge items.
    """
    query_text = q.strip()
    if not query_text:
        return []

    try:
        q_vec = pipeline.embed_text(query_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding error: {e}")

    stored_embeddings = get_all_embeddings()
    if not stored_embeddings:
        return []

    # Map item_id to KnowledgeItem
    all_items = {item.id: item for item in get_all_knowledge_items()}

    scored_results = []
    for item_id, vec_bytes in stored_embeddings:
        if item_id not in all_items:
            continue
        item_vec = np.frombuffer(vec_bytes, dtype=np.float32)
        # Cosine similarity between normalized vectors is dot product
        similarity = float(np.dot(q_vec, item_vec))
        scored_results.append(ScoredKnowledgeItem(
            item=all_items[item_id],
            similarity_score=round(similarity, 4)
        ))

    # Rank highest similarity first
    scored_results.sort(key=lambda x: x.similarity_score, reverse=True)
    return scored_results[:limit]

@app.get("/api/knowledge/{item_id}", response_model=KnowledgeItem)
def get_knowledge(item_id: str):
    item = get_knowledge_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return item

@app.post("/api/knowledge", response_model=KnowledgeItem)
def create_or_sync_knowledge(item: KnowledgeItem):
    # Check if exists
    existing = get_knowledge_item_by_id(item.id)
    if not existing and item.capture_id:
        # Check by capture_id
        items_by_capture = [i for i in get_all_knowledge_items() if i.capture_id == item.capture_id]
        if items_by_capture:
            existing = items_by_capture[0]

    if existing:
        # Update existing
        item.id = existing.id
        save_knowledge_item(item)
    else:
        save_knowledge_item(item)
        # Connect to existing items
        all_items = get_all_knowledge_items()
        new_rels = pipeline.connect_knowledge(item, all_items)
        for rel in new_rels:
            save_relationship(rel)

    # Refresh embedding
    try:
        vec = pipeline.embed_knowledge_item(item)
        save_embedding(item.id, vec.tobytes())
    except Exception as e:
        print(f"[Embedding Sync Error] {e}")

    return item

@app.delete("/api/knowledge/{item_id}")
def delete_knowledge(item_id: str):
    delete_knowledge_item(item_id)
    return {"deleted": True, "id": item_id}

@app.get("/api/graph", response_model=GraphData)
def get_graph():
    return get_graph_data()

@app.patch("/api/relationships/{rel_id}")
def update_relationship(rel_id: str, status: str = Query(...), relation_type: Optional[str] = Query(default=None)):
    update_relationship_status(rel_id, status=status, relation_type=relation_type)
    return {"updated": True, "id": rel_id, "status": status}

@app.delete("/api/relationships/{rel_id}")
def remove_relationship(rel_id: str):
    delete_relationship(rel_id)
    return {"deleted": True, "id": rel_id}

# Model-improvement workflow endpoint
@app.post("/api/eval/record")
def record_evaluation(
    capture_id: str = Form(...),
    transcript: str = Form(...),
    structured_json: str = Form(...),
    user_corrected: bool = Form(default=False),
    consent_given: bool = Form(default=False)
):
    if not consent_given:
        return {"recorded": False, "reason": "User consent not provided"}

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO model_eval_records (id, capture_id, transcript, structured_json, user_corrected, consent_given, pipeline_version, created_at)
    VALUES (?, ?, ?, ?, ?, 1, ?, datetime('now'))
    """, (str(uuid.uuid4()), capture_id, transcript, structured_json, 1 if user_corrected else 0, PIPELINE_VERSION))
    conn.commit()
    conn.close()
    return {"recorded": True}

@app.get("/api/eval/export")
def export_evaluation_dataset():
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM model_eval_records WHERE consent_given = 1").fetchall()
    conn.close()

    dataset = []
    for r in rows:
        dataset.append({
            "id": r["id"],
            "capture_id": r["capture_id"],
            "transcript": r["transcript"],
            "structured_knowledge": json.loads(r["structured_json"] or "{}"),
            "user_corrected": bool(r["user_corrected"]),
            "pipeline_version": r["pipeline_version"],
            "created_at": r["created_at"]
        })
    return {"version": PIPELINE_VERSION, "count": len(dataset), "data": dataset}

@app.post("/api/eval/consent")
def update_consent_withdrawal(req: ConsentUpdateRequest):
    """
    Handles consent withdrawal. When user withdraws consent, unconsented eval records
    are purged to guarantee compliance with the default-deny policy.
    """
    if not req.consent_given:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM model_eval_records WHERE consent_given = 0")
        conn.commit()
        conn.close()
    return {"status": "ok", "consent_given": req.consent_given}

