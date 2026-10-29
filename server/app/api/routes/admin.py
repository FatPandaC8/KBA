import os
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse

from server.app.api.dependencies import Container, get_container, verify_admin_auth
from server.app.adapters.inbound.http.schemas import (
    SystemHealthResponse,
    ProcessingJobResponse,
    BackfillResponse,
    ServerConfigResponse,
    KnowledgeItem,
    DetailedCaptureResponse,
)

admin_router = APIRouter(
    prefix="/api/admin",
    dependencies=[Depends(verify_admin_auth)],
    tags=["admin"],
)

@admin_router.get("/status", response_model=SystemHealthResponse)
def get_system_status(container: Container = Depends(get_container)):
    h = container.admin_status_uc.get_health()
    return SystemHealthResponse(
        status=h.status,
        service=h.service,
        pipeline_version=h.pipeline_version,
        database=h.database,
        knowledge_count=h.knowledge_count,
        relationship_count=h.relationship_count,
        embeddings_count=h.embeddings_count,
        audio_storage_bytes=h.audio_storage_bytes,
        active_jobs_count=h.active_jobs_count,
    )

@admin_router.get("/jobs", response_model=List[ProcessingJobResponse])
def get_recent_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    container: Container = Depends(get_container),
):
    jobs = container.admin_status_uc.get_recent_jobs(limit=limit)
    return [
        ProcessingJobResponse(
            id=j.id,
            capture_id=j.capture_id,
            stage=j.stage,
            status=j.status,
            duration_ms=j.duration_ms,
            error_message=j.error_message,
            created_at=j.created_at,
            updated_at=j.updated_at,
        )
        for j in jobs
    ]

@admin_router.post("/jobs/{capture_id}/retry", response_model=Dict[str, Any])
def retry_job(
    capture_id: str,
    container: Container = Depends(get_container),
):
    capture = container.capture_repo.get_by_id(capture_id)
    if not capture:
        raise HTTPException(status_code=404, detail="Capture not found")
    if not capture.audio_path or not os.path.exists(capture.audio_path):
        raise HTTPException(status_code=400, detail="Cannot retry: Audio was purged per privacy consent policy.")

    if not container.process_capture_uc.retry(capture.id, capture.user_id):
        job = container.job_repo.get_by_capture_id(capture.id, user_id=capture.user_id)
        if not job or job.status != "failed":
            raise HTTPException(status_code=409, detail="Job is already queued or running")
        raise HTTPException(status_code=409, detail="Job cannot be retried")
    container.worker.kick()
    return {"status": "queued", "capture_id": capture.id}

@admin_router.get("/captures", response_model=List[DetailedCaptureResponse])
def list_detailed_captures(
    limit: int = Query(default=50, ge=1, le=200),
    container: Container = Depends(get_container),
):
    dtos = container.admin_status_uc.get_detailed_captures(limit=limit)
    res = []
    for d in dtos:
        resolved = None
        if d.resolved_item:
            resolved = KnowledgeItem(
                id=d.resolved_item.id,
                capture_id=d.resolved_item.capture_id,
                title=d.resolved_item.title,
                core_idea=d.resolved_item.core_idea,
                details=d.resolved_item.details,
                transcript=d.resolved_item.transcript,
                concepts=d.resolved_item.concepts,
                tags=d.resolved_item.tags,
                open_questions=d.resolved_item.open_questions,
                candidate_relations=d.resolved_item.candidate_relations,
                provenance=d.resolved_item.provenance,
                created_at=d.resolved_item.created_at,
                updated_at=d.resolved_item.updated_at,
            )
        res.append(DetailedCaptureResponse(
            capture_id=d.capture_id,
            created_at=d.created_at,
            duration_ms=d.duration_ms,
            has_audio=d.has_audio,
            audio_url=d.audio_url,
            original_transcript=d.original_transcript,
            stage=d.stage,
            status=d.status,
            error_message=d.error_message,
            resolved_item=resolved,
        ))
    return res

@admin_router.get("/captures/{capture_id}", response_model=DetailedCaptureResponse)
def get_detailed_capture(
    capture_id: str,
    container: Container = Depends(get_container),
):
    d = container.admin_status_uc.get_detailed_capture_by_id(capture_id)
    if not d:
        raise HTTPException(status_code=404, detail="Capture not found")
    resolved = None
    if d.resolved_item:
        resolved = KnowledgeItem(
            id=d.resolved_item.id,
            capture_id=d.resolved_item.capture_id,
            title=d.resolved_item.title,
            core_idea=d.resolved_item.core_idea,
            details=d.resolved_item.details,
            transcript=d.resolved_item.transcript,
            concepts=d.resolved_item.concepts,
            tags=d.resolved_item.tags,
            open_questions=d.resolved_item.open_questions,
            candidate_relations=d.resolved_item.candidate_relations,
            provenance=d.resolved_item.provenance,
            created_at=d.resolved_item.created_at,
            updated_at=d.resolved_item.updated_at,
        )
    return DetailedCaptureResponse(
        capture_id=d.capture_id,
        created_at=d.created_at,
        duration_ms=d.duration_ms,
        has_audio=d.has_audio,
        audio_url=d.audio_url,
        original_transcript=d.original_transcript,
        stage=d.stage,
        status=d.status,
        error_message=d.error_message,
        resolved_item=resolved,
    )

@admin_router.get("/captures/{capture_id}/audio")
def get_capture_audio(
    capture_id: str,
    container: Container = Depends(get_container),
):
    capture = container.capture_repo.get_by_id(capture_id)
    if not capture or not capture.audio_path:
        raise HTTPException(status_code=404, detail="Audio recording not found or purged per consent policy")
    
    # Path traversal protection: the audio file must live inside the configured
    # upload directory, not merely share a string prefix with it.
    real_path = os.path.realpath(capture.audio_path)
    allowed_dir = os.path.realpath(container.settings.upload_dir)
    if (
        not (real_path == allowed_dir or real_path.startswith(allowed_dir + os.sep))
        or not os.path.exists(real_path)
    ):
        raise HTTPException(status_code=404, detail="Audio file not accessible on server")

    return FileResponse(
        path=real_path,
        media_type="audio/mp4",
        filename=f"capture-{capture_id}.m4a"
    )


@admin_router.delete("/knowledge/{item_id}")
def admin_delete_knowledge(
    item_id: str,
    container: Container = Depends(get_container),
):
    container.manage_knowledge_uc.delete_knowledge(item_id, user_id=None)
    return {"deleted": True, "id": item_id}


@admin_router.get("/knowledge", response_model=List[KnowledgeItem])
def list_admin_knowledge(
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    container: Container = Depends(get_container),
):
    items = container.manage_knowledge_uc.list_knowledge(user_id=None, query=q, limit=limit, offset=offset)
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

@admin_router.post("/embeddings/backfill", response_model=BackfillResponse)
def trigger_backfill(container: Container = Depends(get_container)):
    res = container.backfill_embeddings_uc.execute()
    return BackfillResponse(
        total_items=res["total_items"],
        newly_indexed=res["newly_indexed"],
        failed=res["failed"],
    )

@admin_router.get("/config", response_model=ServerConfigResponse)
def get_config(container: Container = Depends(get_container)):
    s = container.settings
    return ServerConfigResponse(
        environment=s.app_env,
        pipeline_version=s.pipeline_version,
        stt_provider="faster-whisper (local)",
        extraction_provider="local rule-based extraction",
        embedding_provider="fastembed BAAI/bge-small-en-v1.5 (local)",
        upload_dir=s.upload_dir,
        max_voice_seconds=s.max_voice_seconds,
        consent_version=s.consent_version,
        google_sign_in_configured=bool(s.google_client_id),
        email_delivery="local outbox (not a real mailbox)",
    )

@admin_router.get("/logs")
def get_recent_logs(
    limit: int = Query(default=100, ge=1, le=500),
    level: Optional[str] = Query(default=None),
):
    # Reads recent operational log messages sanitized of secrets
    from server.app.infrastructure.logging import get_recent_memory_logs
    logs = get_recent_memory_logs(limit=limit, level=level)
    return {"logs": logs, "count": len(logs)}
