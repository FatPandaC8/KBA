import logging
import os
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import FileResponse

from server.app.api.dependencies import Container, get_container, verify_admin_auth
from server.app.domain.errors import ValidationError
from server.app.adapters.inbound.http.schemas import (
    SystemHealthResponse,
    ProcessingJobResponse,
    BackfillResponse,
    ServerConfigResponse,
    KnowledgeItem,
    DetailedCaptureResponse,
    AIConfigRequest,
    AIConfigResponse,
    AITestResponse,
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    AdminTranscriptUpdateRequest,
)

logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/api/admin",
    dependencies=[Depends(verify_admin_auth)],
    tags=["admin"],
)


def _audit(
    request: Request,
    container: Container,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    user_id: str = "",
    outcome: str = "success",
    detail: str = "",
) -> None:
    """Append one admin audit row (U4). Audit failures never break the route.

    The actor is the shared admin token identity ("admin"); the request IP is
    stored when it is available and "unknown" otherwise. No token or other
    secret material is ever written to a row.
    """
    try:
        client_ip = request.client.host if (request and request.client) else "unknown"
        container.audit_repo.record(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            ip_address=client_ip,
            outcome=outcome,
            detail=detail,
            actor="admin",
        )
    except Exception:
        logger.warning("admin audit write failed for action=%s", action, exc_info=True)

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
    request: Request,
    container: Container = Depends(get_container),
):
    capture = container.capture_repo.get_by_id(capture_id)
    if not capture:
        _audit(request, container, "jobs.retry", "capture", capture_id, outcome="not_found")
        raise HTTPException(status_code=404, detail="Capture not found")
    if not capture.audio_path or not os.path.exists(capture.audio_path):
        _audit(request, container, "jobs.retry", "capture", capture_id, outcome="rejected", detail="audio purged")
        raise HTTPException(status_code=400, detail="Cannot retry: Audio was purged per privacy consent policy.")

    if not container.process_capture_uc.retry(capture.id, capture.user_id):
        job = container.job_repo.get_by_capture_id(capture.id, user_id=capture.user_id)
        _audit(request, container, "jobs.retry", "capture", capture_id, outcome="rejected", detail="job not retryable")
        if not job or job.status != "failed":
            raise HTTPException(status_code=409, detail="Job is already queued or running")
        raise HTTPException(status_code=409, detail="Job cannot be retried")
    container.worker.kick()
    _audit(request, container, "jobs.retry", "capture", capture_id, user_id=capture.user_id)
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
    request: Request,
    container: Container = Depends(get_container),
):
    container.manage_knowledge_uc.delete_knowledge(item_id, user_id=None)
    _audit(request, container, "knowledge.delete", "knowledge_item", item_id)
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
def trigger_backfill(request: Request, container: Container = Depends(get_container)):
    res = container.backfill_embeddings_uc.execute()
    _audit(
        request,
        container,
        "embeddings.backfill",
        "knowledge_item",
        "",
        detail=f"newly_indexed={res['newly_indexed']} failed={res['failed']}",
    )
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
        extraction_provider=(
            f"groq {s.llm_model}" if s.llm_provider == "groq" else "local rule-based extraction"
        ),
        embedding_provider="fastembed BAAI/bge-small-en-v1.5 (local)",
        upload_dir=s.upload_dir,
        max_voice_seconds=s.max_voice_seconds,
        consent_version=s.effective_consent_version,
        google_sign_in_configured=bool(s.google_client_id),
        email_delivery="local outbox (not a real mailbox)",
    )

@admin_router.get("/ai-config", response_model=AIConfigResponse)
def get_ai_config(container: Container = Depends(get_container)):
    """ADM-07: active provider/model, limits and usage. Never returns the key."""
    return AIConfigResponse(**container.ai_config())


@admin_router.put("/ai-config", response_model=AIConfigResponse)
def update_ai_config(
    payload: AIConfigRequest,
    request: Request,
    container: Container = Depends(get_container),
):
    """ADM-07: switch provider/model. Persisted and applied without restart.

    A provider switch changes the effective consent version, so every user is
    re-prompted before their next recording or answer.
    """
    from server.app.domain.errors import ValidationError

    try:
        config = container.configure_llm(payload.provider, payload.model)
    except (ValueError, ValidationError) as exc:
        _audit(request, container, "ai_config.update", "settings", "", outcome="rejected", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(
        request,
        container,
        "ai_config.update",
        "settings",
        "",
        detail=f"provider={config['provider']} model={config['model']}",
    )
    return AIConfigResponse(**config)


@admin_router.post("/ai-config/test", response_model=AITestResponse)
def test_ai_config(container: Container = Depends(get_container)):
    """ADM-07: minimal live call. Reports success/failure without the key."""
    return AITestResponse(**container.test_llm())


@admin_router.get("/audit-log")
def get_admin_audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    container: Container = Depends(get_container),
):
    """U4: recent admin audit rows, newest first. Never includes secrets."""
    rows = container.audit_repo.list_recent(limit=limit)
    return {"rows": rows, "count": len(rows)}


@admin_router.get("/logs")
def get_recent_logs(
    limit: int = Query(default=100, ge=1, le=500),
    level: Optional[str] = Query(default=None),
):
    # Reads recent operational log messages sanitized of secrets
    from server.app.infrastructure.logging import get_recent_memory_logs
    logs = get_recent_memory_logs(limit=limit, level=level)
    return {"logs": logs, "count": len(logs)}


# ---------------------------------------------------------------------------
# Admin console API. These endpoints are deliberately separate from the
# legacy operational endpoints above so the existing mobile/admin contracts
# remain stable while the React console gains pagination and ownership-aware
# views.

def _page_args(limit: int, offset: int):
    return max(1, min(limit, 100)), max(0, offset)


@admin_router.get("/overview")
def admin_overview(container: Container = Depends(get_container)):
    return container.admin_console_uc.overview()


@admin_router.get("/users")
def admin_users(q: str = Query(default=""), limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), container: Container = Depends(get_container)):
    limit, offset = _page_args(limit, offset)
    return container.admin_console_uc.users(q, limit, offset)


@admin_router.post("/users")
def admin_create_user(payload: AdminUserCreateRequest, request: Request, container: Container = Depends(get_container)):
    try:
        created = container.admin_console_uc.create_user(payload.email, payload.password)
    except (ValueError, ValidationError) as exc:
        _audit(request, container, "user.create", "user", outcome="rejected", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(request, container, "user.create", "user", created["id"])
    return created


@admin_router.get("/users/{user_id}")
def admin_user_detail(user_id: str, container: Container = Depends(get_container)):
    try:
        return container.admin_console_uc.user_detail(user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="User not found")


@admin_router.patch("/users/{user_id}")
def admin_update_user(user_id: str, payload: AdminUserUpdateRequest, request: Request, container: Container = Depends(get_container)):
    try:
        updated = container.admin_console_uc.update_user(user_id, payload.email)
    except KeyError:
        raise HTTPException(status_code=404, detail="User not found")
    except (ValueError, ValidationError) as exc:
        _audit(request, container, "user.update", "user", user_id, outcome="rejected", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(request, container, "user.update", "user", user_id)
    return updated


@admin_router.delete("/users/{user_id}")
def admin_delete_user(user_id: str, request: Request, container: Container = Depends(get_container)):
    try:
        result = container.admin_console_uc.delete_user(user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="User not found")
    # Do not include PII in the audit detail. AccountDeletionUseCase removes
    # user-scoped audit rows before the final user delete.
    _audit(request, container, "user.delete", "user", user_id)
    return result


@admin_router.get("/captures-page")
def admin_capture_page(q: str = Query(default=""), user_id: str = Query(default=""), status: str = Query(default=""), limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), container: Container = Depends(get_container)):
    limit, offset = _page_args(limit, offset)
    return container.admin_console_uc.captures(q, user_id, status, limit, offset)


@admin_router.get("/captures/{capture_id}/console")
def admin_capture_console(capture_id: str, container: Container = Depends(get_container)):
    capture = container.admin_console_uc.capture(capture_id)
    if not capture:
        raise HTTPException(status_code=404, detail="Capture not found")
    return capture


@admin_router.patch("/captures/{capture_id}/transcript")
def admin_update_transcript(capture_id: str, payload: AdminTranscriptUpdateRequest, request: Request, container: Container = Depends(get_container)):
    try:
        result = container.admin_console_uc.update_transcript(capture_id, payload.transcript)
    except KeyError:
        raise HTTPException(status_code=404, detail="Capture not found")
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(request, container, "capture.transcript.update", "capture", capture_id)
    return result


@admin_router.post("/captures/{capture_id}/rerun-extraction")
def admin_rerun_extraction(capture_id: str, request: Request, container: Container = Depends(get_container)):
    try:
        result = container.admin_console_uc.rerun_extraction(capture_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Capture not found")
    except (ValueError, ValidationError) as exc:
        _audit(request, container, "capture.extraction.rerun", "capture", capture_id, outcome="rejected", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        _audit(request, container, "capture.extraction.rerun", "capture", capture_id, outcome="failed", detail="pipeline failure")
        raise HTTPException(status_code=502, detail="Extraction failed; existing graph output was preserved.")
    _audit(request, container, "capture.extraction.rerun", "capture", capture_id)
    return result


@admin_router.delete("/captures/{capture_id}")
def admin_delete_capture(capture_id: str, request: Request, container: Container = Depends(get_container)):
    try:
        result = container.admin_console_uc.delete_capture(capture_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Capture not found")
    _audit(request, container, "capture.delete", "capture", capture_id)
    return result


@admin_router.get("/graph/entities")
def admin_entities(q: str = Query(default=""), user_id: str = Query(default=""), limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), container: Container = Depends(get_container)):
    limit, offset = _page_args(limit, offset)
    return container.admin_console_uc.graph_entities(q, user_id, limit, offset)


@admin_router.get("/graph/relationships")
def admin_relationships(q: str = Query(default=""), user_id: str = Query(default=""), limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), container: Container = Depends(get_container)):
    limit, offset = _page_args(limit, offset)
    return container.admin_console_uc.graph_relationships(q, user_id, limit, offset)


@admin_router.get("/audit-log/page")
def admin_audit_page(action: str = Query(default=""), user_id: str = Query(default=""), limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), container: Container = Depends(get_container)):
    limit, offset = _page_args(limit, offset)
    return container.admin_console_uc.audit(action, user_id, limit, offset)
