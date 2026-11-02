import os
import json
import uuid
import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class KnowledgeRelationship(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_id: str
    to_id: str
    relation_type: str = "Related to"
    status: str = "suggested"
    certainty: str = "confirmed"
    confidence: float = 0.6
    source_capture_id: str = ""
    created_at: Optional[str] = None


class KnowledgeItem(BaseModel):
    """Admin-facing knowledge record. Includes the transcript."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capture_id: str
    title: str
    core_idea: str
    details: str = ""
    transcript: str = ""
    concepts: List[str] = []
    tags: List[str] = []
    open_questions: List[str] = []
    candidate_relations: List[str] = []
    provenance: str = "voice-capture"
    created_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


class PublicKnowledgeItem(BaseModel):
    """Client-facing knowledge record.

    Transcripts are deliberately absent. D5/C3 forbid exposing transcripts to
    ordinary users, so the field cannot be reintroduced by accident through a
    response model change in one route.
    """

    id: str
    capture_id: str
    title: str
    core_idea: str
    details: str = ""
    concepts: List[str] = []
    tags: List[str] = []
    open_questions: List[str] = []
    candidate_relations: List[str] = []
    provenance: str = "voice-capture"
    created_at: str
    updated_at: str


class GraphNode(BaseModel):
    id: str
    title: str
    kind: str
    x: float
    y: float
    cluster_id: str = ""
    certainty: str = "confirmed"
    confidence: float = 0.5
    degree: int = 0
    is_self: bool = False


class GraphEdge(BaseModel):
    id: str
    from_node: str
    to_node: str
    type: str
    status: str
    certainty: str = "confirmed"
    confidence: float = 0.6
    evidence: str = ""


class GraphCluster(BaseModel):
    id: str
    label: str
    x: float
    y: float
    size: int


class GraphData(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    clusters: List[GraphCluster] = []


class EntityResponse(BaseModel):
    id: str
    name: str
    entity_type: str
    description: str = ""
    confidence: float = 0.5
    certainty: str = "confirmed"
    provenance: str = "voice-capture"
    capture_id: str = ""
    created_at: str
    updated_at: str
    provider_id: str = ""
    model_version: str = ""
    is_self: bool = False


class EntityDetailRelationship(BaseModel):
    id: str
    from_id: str
    to_id: str
    from_name: str = ""
    to_name: str = ""
    relation_type: str
    status: str
    certainty: str = "confirmed"
    confidence: float = 0.6
    source_capture_id: str = ""
    created_at: str


class EntityDetailResponse(BaseModel):
    entity: EntityResponse
    relationships: List[EntityDetailRelationship] = []


class EntityUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ScoredEntity(BaseModel):
    entity: EntityResponse
    score: float


class GraphSearchResponse(BaseModel):
    entities: List[ScoredEntity] = []
    relationships: List[KnowledgeRelationship] = []


class ProviderInfoResponse(BaseModel):
    id: str
    name: str
    kind: str
    receives: List[str]
    trains_on_data: bool
    available: bool
    detail: str = ""
    model: str = ""
    retention: str = ""
    privacy_url: str = ""
    terms_url: str = ""


class DuplicateFlagResponse(BaseModel):
    entity_id: str
    candidate_id: str
    score: float
    decision: str


class CaptureUploadResponse(BaseModel):
    capture_id: str
    status: str
    knowledge_item: Optional[PublicKnowledgeItem] = None
    relationships: List[KnowledgeRelationship] = []


class EvalExportRecord(BaseModel):
    capture_id: str
    transcript: str
    structured_knowledge: dict
    user_corrected: bool = False
    pipeline_version: str = "v1.2"


class ScoredKnowledgeItem(BaseModel):
    item: PublicKnowledgeItem
    similarity_score: float


# ------------------------------------------------------------------ auth
class SignupRequest(BaseModel):
    email: str
    password: str


class SignupResponse(BaseModel):
    verification_required: bool = True
    email: str
    dev_verification_token: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    email_verified: bool
    created_at: str


class AuthSessionResponse(BaseModel):
    token: str
    user: UserResponse


class VerifyEmailRequest(BaseModel):
    token: str


class VerifyEmailResponse(BaseModel):
    verified: bool = True


class ResendVerificationRequest(BaseModel):
    email: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetRequestResponse(BaseModel):
    message: str
    dev_reset_token: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class GoogleSignInRequest(BaseModel):
    id_token: str


class AccountDeletionResponse(BaseModel):
    deleted: bool
    sessions_revoked: int = 0
    audio_files_removed: int = 0
    message: str = (
        "Your account and its data were deleted. Encrypted backups and any "
        "third-party copies already made may persist for the documented "
        "retention period."
    )


# --------------------------------------------------------------- consent
class ConsentStatusResponse(BaseModel):
    required: bool = True
    version: str
    providers: List[dict]
    granted: bool
    granted_at: Optional[str] = None
    recorded_version: Optional[str] = None


class ConsentUpdateRequest(BaseModel):
    granted: bool


# ------------------------------------------------------------ recordings
# Pipeline split (S2): no job rows. Capture truth only — created_at, whether
# the knowledge item was built, and the last ingest error (captures row).
class RecordingResponse(BaseModel):
    capture_id: str
    created_at: str
    has_knowledge_item: bool
    last_error: Optional[str] = None


# Admin Schemas
class SystemHealthResponse(BaseModel):
    status: str
    service: str
    pipeline_version: str
    database: str
    knowledge_count: int
    relationship_count: int
    embeddings_count: int
    audio_storage_bytes: int
    capture_counts: Dict[str, int] = Field(default_factory=dict)
    failed_captures: int = 0


class BackfillResponse(BaseModel):
    total_items: int
    newly_indexed: int
    failed: int


class ServerConfigResponse(BaseModel):
    environment: str
    pipeline_version: str
    stt_provider: str
    extraction_provider: str
    embedding_provider: str
    upload_dir: str
    max_voice_seconds: int
    consent_version: str
    google_sign_in_configured: bool
    email_delivery: str


class AIConfigRequest(BaseModel):
    provider: str
    model: str = ""


class AIConfigResponse(BaseModel):
    provider: str
    model: str
    provider_available: bool
    key_configured: bool
    local_only: bool
    limits: Dict[str, int]
    consent_version: str
    last_24h_calls: int
    last_24h_tokens: int
    recent_calls: List[Dict[str, Any]] = []
    providers: List[Dict[str, Any]] = []


class AITestResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    network_call: bool = False
    detail: str = ""
    error_class: str = ""
    retry_after: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class DetailedCaptureResponse(BaseModel):
    capture_id: str
    created_at: str
    duration_ms: int
    has_audio: bool
    audio_url: Optional[str] = None
    original_transcript: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    resolved_item: Optional[KnowledgeItem] = None


class AdminUserCreateRequest(BaseModel):
    email: str
    password: str


class AdminUserUpdateRequest(BaseModel):
    email: str


class AdminTranscriptUpdateRequest(BaseModel):
    transcript: str
