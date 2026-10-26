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
    knowledge_item: Optional[KnowledgeItem] = None
    relationships: List[KnowledgeRelationship] = []

class EvalExportRecord(BaseModel):
    capture_id: str
    transcript: str
    structured_knowledge: dict
    user_corrected: bool = False
    pipeline_version: str = "v1.2"

class ScoredKnowledgeItem(BaseModel):
    item: KnowledgeItem
    similarity_score: float

class ConsentUpdateRequest(BaseModel):
    consent_given: bool

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
    model: str
    base_url: str
    has_api_key: bool
    upload_dir: str
    max_voice_seconds: int

class ServerConfigUpdateRequest(BaseModel):
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None

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

