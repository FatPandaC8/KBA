import os
import json
import uuid
import datetime
import logging
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Depends

from server.app.api.dependencies import Container, get_container, verify_client_auth
from server.app.domain.errors import AudioProcessingError, ValidationError
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
protected_router = APIRouter(prefix="/api", dependencies=[Depends(verify_client_auth)])

@router.get("/health")
def health(container: Container = Depends(get_container)):
    health_dto = container.admin_status_uc.get_health()
    return {
        "status": health_dto.status,
        "service": health_dto.service,
        "pipeline_version": health_dto.pipeline_version,
    }

def _to_knowledge_item(k) -> KnowledgeItem:
    return KnowledgeItem(
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


@protected_router.post("/captures/upload", response_model=CaptureUploadResponse)
async def upload_capture(
    file: UploadFile = File(...),
    capture_id: str = Form(...),
    idempotency_key: str = Form(...),
    duration_ms: int = Form(default=0),
    consent_given: bool = Form(default=False),
    container: Container = Depends(get_container),
):
    try:
        parsed_id = uuid.UUID(capture_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="capture_id must be a valid UUID")
    if str(parsed_id) != capture_id:
        raise HTTPException(status_code=400, detail="capture_id must be a canonical UUID")
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="idempotency_key is invalid")
    if duration_ms < 0 or duration_ms > container.settings.max_voice_seconds * 2000:
        raise HTTPException(status_code=400, detail="duration_ms is out of range")

    upload_dir = os.path.realpath(container.settings.upload_dir)
    os.makedirs(upload_dir, exist_ok=True)
    audio_path = os.path.join(upload_dir, f"{capture_id}.m4a")
    if not audio_path.startswith(upload_dir + os.sep):
        raise HTTPException(status_code=400, detail="Invalid capture identifier")

    total_bytes = 0
    try:
        with open(audio_path, "wb") as destination:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > container.settings.max_upload_bytes:
                    destination.close()
                    os.remove(audio_path)
                    raise HTTPException(
                        status_code=413,
                        detail="Audio upload exceeds the configured size limit",
                    )
                destination.write(chunk)
    except HTTPException:
        raise
    except Exception:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        logger.exception("Failed to store uploaded audio for capture %s", capture_id)
        raise HTTPException(status_code=500, detail="Failed to store audio upload")

    if total_bytes == 0:
        os.remove(audio_path)
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty")

    # Idempotent retry: return the already processed result instead of
    # re-running transcription and creating duplicate jobs.
    existing_item = container.knowledge_repo.get_by_capture_id(capture_id)
    existing_capture = container.capture_repo.get_by_id(capture_id)
    if existing_item and existing_capture and existing_capture.status == "ready":
        if os.path.exists(audio_path) and not consent_given:
            os.remove(audio_path)
        return CaptureUploadResponse(
            capture_id=capture_id,
            status="ready",
            knowledge_item=_to_knowledge_item(existing_item),
            relationships=[],
        )

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
            k_item = _to_knowledge_item(result.knowledge_item)

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
    except (ValidationError, AudioProcessingError):
        logger.warning("Rejected audio capture %s", capture_id)
        raise HTTPException(
            status_code=422,
            detail="Audio could not be processed. The recording may be silent or corrupted.",
        )
    except Exception:
        logger.exception("Audio capture processing failed for %s", capture_id)
        raise HTTPException(
            status_code=500,
            detail="Audio processing failed on the server.",
        )

@protected_router.delete("/captures/{capture_id}")
def delete_capture(capture_id: str, container: Container = Depends(get_container)):
    try:
        uuid.UUID(capture_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="capture_id must be a valid UUID")
    try:
        return container.delete_capture_uc.execute(capture_id)
    except Exception:
        logger.exception("Capture deletion failed for %s", capture_id)
        raise HTTPException(
            status_code=500,
            detail="Capture deletion failed. No success was reported.",
        )


@protected_router.get("/knowledge", response_model=List[KnowledgeItem])
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

@protected_router.get("/knowledge/semantic-search", response_model=List[ScoredKnowledgeItem])
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

@protected_router.get("/knowledge/{item_id}", response_model=KnowledgeItem)
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

@protected_router.post("/knowledge", response_model=KnowledgeItem)
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

@protected_router.delete("/knowledge/{item_id}")
def delete_knowledge(item_id: str, container: Container = Depends(get_container)):
    container.manage_knowledge_uc.delete_knowledge(item_id)
    return {"deleted": True, "id": item_id}

@protected_router.get("/graph", response_model=GraphData)
def get_graph(container: Container = Depends(get_container)):
    graph_dto = container.manage_relationships_uc.get_graph()
    return GraphData(
        nodes=[GraphNode(id=n.id, title=n.title, kind=n.kind, x=n.x, y=n.y) for n in graph_dto.nodes],
        edges=[GraphEdge(id=e.id, from_node=e.from_node, to_node=e.to_node, type=e.type, status=e.status) for e in graph_dto.edges],
    )

@protected_router.patch("/relationships/{rel_id}")
def update_relationship(
    rel_id: str,
    status: str = Query(...),
    relation_type: Optional[str] = Query(default=None),
    container: Container = Depends(get_container),
):
    container.manage_relationships_uc.update_relationship(rel_id, status=status, relation_type=relation_type)
    return {"updated": True, "id": rel_id, "status": status}

@protected_router.delete("/relationships/{rel_id}")
def remove_relationship(rel_id: str, container: Container = Depends(get_container)):
    container.manage_relationships_uc.delete_relationship(rel_id)
    return {"deleted": True, "id": rel_id}

@protected_router.post("/eval/record")
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

@protected_router.get("/eval/export")
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

@protected_router.post("/eval/consent")
def update_consent_withdrawal(
    req: ConsentUpdateRequest,
    container: Container = Depends(get_container),
):
    if not req.consent_given:
        purged_audio = 0
        try:
            purged_audio = container.purge_audio_uc.execute()
            purged_records = container.eval_repo.purge_all()
        except Exception:
            logger.exception("Consent withdrawal purge failed")
            raise HTTPException(
                status_code=500,
                detail="Consent withdrawal could not be completed.",
            )
        return {
            "status": "ok",
            "consent_given": False,
            "purged_audio_files": purged_audio,
            "purged_eval_records": purged_records,
        }
    return {"status": "ok", "consent_given": True}
