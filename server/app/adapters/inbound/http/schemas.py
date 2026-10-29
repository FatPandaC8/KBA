import os
import json
import uuid
import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class KnowledgeRelationship(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_id: str
    to_id: str
    relation_type: str = "Related to"
    status: str = "suggested"


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


class GraphEdge(BaseModel):
    id: str
    from_node: str
    to_node: str
    type: str
    status: str


class GraphData(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


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
class RecordingResponse(BaseModel):
    capture_id: str
    created_at: str
    duration_ms: int
    status: str
    stage: str
    has_audio: bool
    knowledge_item_id: Optional[str] = None
    error_message: Optional[str] = None
    error_class: str = ""
    retryable: bool = False


class JobStatusResponse(BaseModel):
    capture_id: str
    stage: str
    status: str
    attempt: int = 0
    error_class: str = ""
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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
    active_jobs_count: int


class ProcessingJobResponse(BaseModel):
    id: str
    capture_id: str
    stage: str
    status: str
    duration_ms: int
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


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


class DetailedCaptureResponse(BaseModel):
    capture_id: str
    created_at: str
    duration_ms: int
    has_audio: bool
    audio_url: Optional[str] = None
    original_transcript: Optional[str] = None
    stage: str
    status: str
    error_message: Optional[str] = None
    resolved_item: Optional[KnowledgeItem] = None
