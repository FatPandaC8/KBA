import datetime
import json
import logging
import os
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel

from server.app.adapters.inbound.http.schemas import (
    EntityDetailResponse,
    EntityResponse,
    EntityUpdateRequest,
    GraphCluster,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphSearchResponse,
KnowledgeRelationship,
    ProviderInfoResponse,
    PublicKnowledgeItem,
    RecordingResponse,
    ScoredEntity,
    ScoredKnowledgeItem,
)
from server.app.api.dependencies import (
    Container,
    get_container,
    get_current_user,
    require_current_consent,
)
from server.app.domain.entities import CaptureEntity, UserEntity
from server.app.domain.errors import (
    AudioProcessingError,
    ConflictError,
    EntityNotFoundError,
    ProviderError,
    ValidationError,
)
from server.app.domain.value_objects import CaptureStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
protected_router = APIRouter(prefix="/api", dependencies=[Depends(require_current_consent)])

# ---------------------------------------------------------------------------
# Pipeline-split endpoints (S1/S2): two independent synchronous APIs.
# POST /api/stt    — stateless transcription; persists nothing.
# POST /api/text-kb — capture + knowledge item + graph in ONE UoW, idempotent
# on the client-side capture_id. No job table, no polling, no server retries.
# ---------------------------------------------------------------------------
stt_router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


def _typed_error(error_class: str, message: str) -> HTTPException:
    """Typed error body for the split endpoints."""
    return HTTPException(
        status_code=400, detail={"class": error_class, "message": message}
    )


@stt_router.post("/stt")
async def stt(
    request: Request,
    container: Container = Depends(get_container),
):
    """Stateless transcription of an audio body (persists NOTHING, S4b)."""
    settings = container.settings
    length = int(request.headers.get("content-length", "0"))
    if length > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "class": "too_large",
                "message": f"Audio exceeds the {settings.max_upload_bytes} byte limit.",
            },
        )
    audio = await request.body()
    if not audio:
        raise _typed_error("invalid_input", "Audio body is empty.")
    content_type = request.headers.get("content-type", "application/octet-stream")

    started = time.perf_counter()
    try:
        transcript = container.transcriber.transcribe(audio, content_type)
    except AudioProcessingError as exc:
        message = str(getattr(exc, "args", (exc,))[0] or exc)
        lowered = message.lower()
        if "language" in lowered and ("english" in lowered and "only" in lowered.split()[:3] or "detected language" in lowered):
            raise HTTPException(
                status_code=400,
                detail={"class": "unsupported_language", "message": message},
            )
        raise _typed_error("invalid_input", message)
    except ProviderError as exc:
        error_class = getattr(exc, "error_class", "")
        upstream = error_class.startswith(("provider", "network", "timeout"))
        raise HTTPException(
            status_code=502 if upstream else 400,
            detail={"class": error_class or "provider_failure", "message": str(exc)},
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "transcript": transcript.text,
        "language": transcript.language,
        "provider": transcript.provider,
        "elapsed_ms": elapsed_ms,
    }


class TextKBRequest(BaseModel):
    capture_id: str
    text: str


@protected_router.post("/text-kb")
def text_kb(
    payload: TextKBRequest,
    container: Container = Depends(get_container),
    user: UserEntity = Depends(require_current_consent),
):
    """Knowledge ingest from text. Idempotent on capture_id; one UoW."""
    try:
        parsed = uuid.UUID(payload.capture_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail={"class": "invalid_input",
                    "message": "capture_id must be a valid UUID."},
        )
    if str(parsed) != payload.capture_id:
        raise HTTPException(
            status_code=400,
            detail={"class": "invalid_input",
                    "message": "capture_id must be canonical."},
        )

    started = time.perf_counter()
    try:
        result = container.ingestor.ingest(user.id, payload.capture_id, payload.text)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422 if "too long" in str(exc) else 400,
            detail={"class": "invalid_input", "message": str(exc)},
        )
    except ConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"class": "conflict", "message": str(exc)},
        )
    except ProviderError as exc:
        logger.error(
            "text-kb ingest failed capture_id=%s error=%s",
            payload.capture_id, type(exc).__name__, exc_info=exc,
        )
        raise HTTPException(
            status_code=502,
            detail={"class": getattr(exc, "error_class", "provider_failure"),
                    "message": str(exc)},
        )
    except Exception as exc:  # real server fault: 5xx, original traceback logged
        logger.error(
            "text-kb ingest failed capture_id=%s error=%s",
            payload.capture_id, type(exc).__name__, exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail={"class": "server_error", "message": "Text-KB ingest failed."},
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "capture_id": result.capture_id,
        "knowledge_item_id": result.knowledge_item_id,
        "entities_added": result.entities_added,
        "relationships_added": result.relationships_added,
        "provider": result.provider,
        "elapsed_ms": elapsed_ms,
    }


def _to_public(k) -> PublicKnowledgeItem:
    return PublicKnowledgeItem(
        id=k.id,
        capture_id=k.capture_id,
        title=k.title,
        core_idea=k.core_idea,
        details=k.details,
        concepts=k.concepts,
        tags=k.tags,
        open_questions=k.open_questions,
        candidate_relations=k.candidate_relations,
        provenance=k.provenance,
        created_at=k.created_at,
        updated_at=k.updated_at,
    )


@router.get("/health")
def health(container: Container = Depends(get_container)):
    health_dto = container.admin_status_uc.get_health()
    return {
        "status": health_dto.status,
        "service": health_dto.service,
        "pipeline_version": health_dto.pipeline_version,
    }


@protected_router.get("/recordings", response_model=List[RecordingResponse])
def list_recordings(
    limit: int = Query(default=50, ge=1, le=200),
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    """Capture journal (pipeline split): created_at + knowledge-item presence
    + the last ingest error. There are no job rows/stages (S2)."""
    items = []
    for capture in container.capture_repo.list_recent(limit=limit, user_id=user.id):
        knowledge = container.knowledge_repo.get_by_capture_id(capture.id, user_id=user.id)
        items.append(
            RecordingResponse(
                capture_id=capture.id,
                created_at=capture.created_at,
                has_knowledge_item=knowledge is not None,
                last_error=capture.last_error,
            )
        )
    return items


@protected_router.delete("/captures/{capture_id}")
def delete_capture(
    capture_id: str,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    try:
        uuid.UUID(capture_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="capture_id must be a valid UUID")
    try:
        return container.delete_capture_uc.execute(capture_id, user_id=user.id)
    except Exception:
        logger.exception("Capture deletion failed for %s", capture_id)
        raise HTTPException(
            status_code=500,
            detail="Capture deletion failed. No success was reported.",
        )


@protected_router.get("/knowledge", response_model=List[PublicKnowledgeItem])
def list_knowledge(
    q: str = Query(default=""),
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    items = container.manage_knowledge_uc.list_knowledge(query=q, user_id=user.id)
    return [_to_public(i) for i in items]


@protected_router.get("/knowledge/semantic-search", response_model=List[ScoredKnowledgeItem])
def semantic_search(
    q: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    scored_dtos = container.semantic_recall_uc.execute(query=q, user_id=user.id, limit=limit)
    return [
        ScoredKnowledgeItem(item=_to_public(s.item), similarity_score=s.similarity_score)
        for s in scored_dtos
    ]


@protected_router.get("/knowledge/{item_id}", response_model=PublicKnowledgeItem)
def get_knowledge(
    item_id: str,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    try:
        return _to_public(container.manage_knowledge_uc.get_knowledge(item_id, user_id=user.id))
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Knowledge item not found")


@protected_router.delete("/knowledge/{item_id}")
def delete_knowledge(
    item_id: str,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    try:
        container.manage_knowledge_uc.get_knowledge(item_id, user_id=user.id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    container.manage_knowledge_uc.delete_knowledge(item_id, user_id=user.id)
    return {"deleted": True, "id": item_id}


@protected_router.get("/graph", response_model=GraphData)
def get_graph(
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    graph_dto = container.graph_query_uc.get_graph(user_id=user.id)
    return GraphData(
        nodes=[
            GraphNode(
                id=n.id,
                title=n.title,
                kind=n.kind,
                x=n.x,
                y=n.y,
                cluster_id=n.cluster_id,
                certainty=n.certainty,
                confidence=n.confidence,
                degree=n.degree,
                is_self=n.is_self,
            )
            for n in graph_dto.nodes
        ],
        edges=[
            GraphEdge(
                id=e.id,
                from_node=e.from_node,
                to_node=e.to_node,
                type=e.type,
                status=e.status,
                certainty=e.certainty,
                confidence=e.confidence,
                evidence=e.evidence,
            )
            for e in graph_dto.edges
        ],
        clusters=[
            GraphCluster(id=c.id, label=c.label, x=c.x, y=c.y, size=c.size)
            for c in graph_dto.clusters
        ],
    )


@protected_router.get("/graph/search", response_model=GraphSearchResponse)
def search_graph(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    result = container.graph_query_uc.search(user.id, q, limit=limit)
    return GraphSearchResponse(
        entities=[
            ScoredEntity(entity=EntityResponse(**scored.entity.__dict__), score=scored.score)
            for scored in result.entities
        ],
        relationships=[KnowledgeRelationship(**rel.__dict__) for rel in result.relationships],
    )


@protected_router.get("/graph/entities/{entity_id}", response_model=EntityDetailResponse)
def get_entity(
    entity_id: str,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    try:
        detail = container.graph_query_uc.get_entity_detail(user.id, entity_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityDetailResponse(**detail)


@protected_router.patch("/graph/entities/{entity_id}", response_model=EntityResponse)
def update_entity(
    entity_id: str,
    payload: EntityUpdateRequest,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    try:
        updated = container.graph_query_uc.update_entity(
            user.id, entity_id, payload.name, payload.description
        )
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Entity not found")
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EntityResponse(**updated.__dict__)


@protected_router.delete("/graph/entities/{entity_id}")
def delete_entity(
    entity_id: str,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    try:
        container.graph_query_uc.delete_entity(user.id, entity_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"deleted": True, "id": entity_id}


@protected_router.get("/providers", response_model=List[ProviderInfoResponse])
def list_providers(
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    return [
        ProviderInfoResponse(
            id=p.id,
            name=p.name,
            kind=p.kind,
            receives=p.receives,
            trains_on_data=p.trains_on_data,
            available=p.available,
            detail=p.detail,
            model=p.model,
            retention=p.retention,
            privacy_url=p.privacy_url,
            terms_url=p.terms_url,
        )
        for p in container.provider_registry.list_providers()
    ]


@protected_router.patch("/relationships/{rel_id}")
def update_relationship(
    rel_id: str,
    status: str = Query(...),
    relation_type: Optional[str] = Query(default=None),
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    updated = container.manage_relationships_uc.update_relationship(
        rel_id,
        status=status,
        user_id=user.id,
        relation_type=relation_type,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return {"updated": True, "id": rel_id, "status": status}


@protected_router.delete("/relationships/{rel_id}")
def remove_relationship(
    rel_id: str,
    user: UserEntity = Depends(require_current_consent),
    container: Container = Depends(get_container),
):
    deleted = container.manage_relationships_uc.delete_relationship(rel_id, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return {"deleted": True, "id": rel_id}
