import os
import json
import uuid
import datetime
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Depends

from server.app.api.dependencies import Container, get_container
from server.app.adapters.inbound.http.schemas import (
    KnowledgeItem,
    KnowledgeRelationship,
    GraphData,
    GraphNode,
    GraphEdge,
    CaptureUploadResponse,
    ScoredKnowledgeItem,
    ConsentUpdateRequest,
)
from server.app.application.dto import KnowledgeItemDTO, RelationshipDTO
from server.app.domain.entities import EvalRecordEntity

router = APIRouter(prefix="/api")

@router.get("/health")
def health(container: Container = Depends(get_container)):
    health_dto = container.admin_status_uc.get_health()
    return {
        "status": health_dto.status,
        "service": health_dto.service,
        "pipeline_version": health_dto.pipeline_version,
    }

@router.post("/captures/upload", response_model=CaptureUploadResponse)
async def upload_capture(
    file: UploadFile = File(...),
    capture_id: str = Form(...),
    idempotency_key: str = Form(...),
    duration_ms: int = Form(default=0),
    consent_given: bool = Form(default=False),
    container: Container = Depends(get_container),
):
    upload_dir = container.settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{capture_id}.m4a"
    audio_path = os.path.join(upload_dir, filename)

    contents = await file.read()
    with open(audio_path, "wb") as f:
        f.write(contents)

    try:
        result = container.process_audio_uc.execute(
            capture_id=capture_id,
            idempotency_key=idempotency_key,
            audio_file_path=audio_path,
            duration_ms=duration_ms,
            consent_given=consent_given,
        )

        k_item = None
        if result.knowledge_item:
            k = result.knowledge_item
            k_item = KnowledgeItem(
                id=k.id,
                capture_id=k.capture_id,
                title=k.title,
                core_idea=k.core_idea,
                details=k.details,
                transcript=k.transcript,
                concepts=k.concepts,
                tags=k.tags,
                open_questions=k.open_questions,
                candidate_relations=k.candidate_relations,
                provenance=k.provenance,
                created_at=k.created_at,
                updated_at=k.updated_at,
            )

        rels = [
            KnowledgeRelationship(
                id=r.id,
                from_id=r.from_id,
                to_id=r.to_id,
                relation_type=r.relation_type,
                status=r.status,
            )
            for r in result.relationships
        ]

        return CaptureUploadResponse(
            capture_id=result.capture_id,
            status=result.status,
            knowledge_item=k_item,
            relationships=rels,
        )
    except Exception as e:
        raise HTTPException(
            status_code=422 if isinstance(e, ValueError) else 500,
            detail=str(e),
        )

@router.get("/knowledge", response_model=List[KnowledgeItem])
def list_knowledge(q: str = Query(default=""), container: Container = Depends(get_container)):
    items = container.manage_knowledge_uc.list_knowledge(query=q)
    return [
        KnowledgeItem(
            id=i.id,
            capture_id=i.capture_id,
            title=i.title,
            core_idea=i.core_idea,
            details=i.details,
            transcript=i.transcript,
            concepts=i.concepts,
            tags=i.tags,
            open_questions=i.open_questions,
            candidate_relations=i.candidate_relations,
            provenance=i.provenance,
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
        for i in items
    ]

@router.get("/knowledge/semantic-search", response_model=List[ScoredKnowledgeItem])
def semantic_search(
    q: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    container: Container = Depends(get_container),
):
    scored_dtos = container.semantic_recall_uc.execute(query=q, limit=limit)
    return [
        ScoredKnowledgeItem(
            item=KnowledgeItem(
                id=s.item.id,
                capture_id=s.item.capture_id,
                title=s.item.title,
                core_idea=s.item.core_idea,
                details=s.item.details,
                transcript=s.item.transcript,
                concepts=s.item.concepts,
                tags=s.item.tags,
                open_questions=s.item.open_questions,
                candidate_relations=s.item.candidate_relations,
                provenance=s.item.provenance,
                created_at=s.item.created_at,
                updated_at=s.item.updated_at,
            ),
            similarity_score=s.similarity_score,
        )
        for s in scored_dtos
    ]

@router.get("/knowledge/{item_id}", response_model=KnowledgeItem)
def get_knowledge(item_id: str, container: Container = Depends(get_container)):
    try:
        i = container.manage_knowledge_uc.get_knowledge(item_id)
        return KnowledgeItem(
            id=i.id,
            capture_id=i.capture_id,
            title=i.title,
            core_idea=i.core_idea,
            details=i.details,
            transcript=i.transcript,
            concepts=i.concepts,
            tags=i.tags,
            open_questions=i.open_questions,
            candidate_relations=i.candidate_relations,
            provenance=i.provenance,
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

@router.post("/knowledge", response_model=KnowledgeItem)
def create_or_sync_knowledge(item: KnowledgeItem, container: Container = Depends(get_container)):
    dto = KnowledgeItemDTO(
        id=item.id,
        capture_id=item.capture_id,
        title=item.title,
        core_idea=item.core_idea,
        details=item.details,
        transcript=item.transcript,
        concepts=item.concepts,
        tags=item.tags,
        open_questions=item.open_questions,
        candidate_relations=item.candidate_relations,
        provenance=item.provenance,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
    saved = container.manage_knowledge_uc.save_or_sync_knowledge(dto)
    return KnowledgeItem(
        id=saved.id,
        capture_id=saved.capture_id,
        title=saved.title,
        core_idea=saved.core_idea,
        details=saved.details,
        transcript=saved.transcript,
        concepts=saved.concepts,
        tags=saved.tags,
        open_questions=saved.open_questions,
        candidate_relations=saved.candidate_relations,
        provenance=saved.provenance,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
    )

@router.delete("/api/knowledge/{item_id}")
@router.delete("/knowledge/{item_id}")
def delete_knowledge(item_id: str, container: Container = Depends(get_container)):
    container.manage_knowledge_uc.delete_knowledge(item_id)
    return {"deleted": True, "id": item_id}

@router.get("/graph", response_model=GraphData)
def get_graph(container: Container = Depends(get_container)):
    graph_dto = container.manage_relationships_uc.get_graph()
    return GraphData(
        nodes=[GraphNode(id=n.id, title=n.title, kind=n.kind, x=n.x, y=n.y) for n in graph_dto.nodes],
        edges=[GraphEdge(id=e.id, from_node=e.from_node, to_node=e.to_node, type=e.type, status=e.status) for e in graph_dto.edges],
    )

@router.patch("/relationships/{rel_id}")
def update_relationship(
    rel_id: str,
    status: str = Query(...),
    relation_type: Optional[str] = Query(default=None),
    container: Container = Depends(get_container),
):
    container.manage_relationships_uc.update_relationship(rel_id, status=status, relation_type=relation_type)
    return {"updated": True, "id": rel_id, "status": status}

@router.delete("/relationships/{rel_id}")
def remove_relationship(rel_id: str, container: Container = Depends(get_container)):
    container.manage_relationships_uc.delete_relationship(rel_id)
    return {"deleted": True, "id": rel_id}

@router.post("/eval/record")
def record_evaluation(
    capture_id: str = Form(...),
    transcript: str = Form(...),
    structured_json: str = Form(...),
    user_corrected: bool = Form(default=False),
    consent_given: bool = Form(default=False),
    container: Container = Depends(get_container),
):
    if not consent_given:
        return {"recorded": False, "reason": "User consent not provided"}

    record = EvalRecordEntity(
        id=str(uuid.uuid4()),
        capture_id=capture_id,
        transcript=transcript,
        structured_json=structured_json,
        user_corrected=user_corrected,
        consent_given=consent_given,
        pipeline_version=container.settings.pipeline_version,
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    container.eval_repo.save(record)
    return {"recorded": True}

@router.get("/eval/export")
def export_evaluation_dataset(container: Container = Depends(get_container)):
    records = container.eval_repo.get_all_consented()
    dataset = []
    for r in records:
        dataset.append({
            "id": r.id,
            "capture_id": r.capture_id,
            "transcript": r.transcript,
            "structured_knowledge": json.loads(r.structured_json or "{}"),
            "user_corrected": r.user_corrected,
            "pipeline_version": r.pipeline_version,
            "created_at": r.created_at,
        })
    return {"version": container.settings.pipeline_version, "count": len(dataset), "data": dataset}

@router.post("/eval/consent")
def update_consent_withdrawal(
    req: ConsentUpdateRequest,
    container: Container = Depends(get_container),
):
    if not req.consent_given:
        container.eval_repo.purge_unconsented()
    return {"status": "ok", "consent_given": req.consent_given}
