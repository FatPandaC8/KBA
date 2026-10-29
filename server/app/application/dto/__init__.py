from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class KnowledgeItemDTO:
    id: str
    capture_id: str
    title: str
    core_idea: str
    details: str
    transcript: str
    concepts: List[str]
    tags: List[str]
    open_questions: List[str]
    candidate_relations: List[str]
    provenance: str
    created_at: str
    updated_at: str

@dataclass
class RelationshipDTO:
    id: str
    from_id: str
    to_id: str
    relation_type: str
    status: str
    created_at: str

@dataclass
class GraphNodeDTO:
    id: str
    title: str
    kind: str
    x: float
    y: float

@dataclass
class GraphEdgeDTO:
    id: str
    from_node: str
    to_node: str
    type: str
    status: str

@dataclass
class GraphDataDTO:
    nodes: List[GraphNodeDTO]
    edges: List[GraphEdgeDTO]

@dataclass
class ScoredKnowledgeItemDTO:
    item: KnowledgeItemDTO
    similarity_score: float

@dataclass
class CaptureUploadResultDTO:
    capture_id: str
    status: str
    knowledge_item: Optional[KnowledgeItemDTO]
    relationships: List[RelationshipDTO]

@dataclass
class SystemHealthDTO:
    status: str
    service: str
    pipeline_version: str
    database: str
    knowledge_count: int
    relationship_count: int
    embeddings_count: int
    audio_storage_bytes: int
    active_jobs_count: int

@dataclass
class ProcessingJobDTO:
    id: str
    capture_id: str
    stage: str
    status: str
    duration_ms: int
    error_message: Optional[str]
    created_at: str
    updated_at: str
    user_id: str = ""
    attempt: int = 0
    error_class: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""
    stage_outputs: str = "{}"

@dataclass
class DetailedCaptureViewDTO:
    capture_id: str
    created_at: str
    duration_ms: int
    has_audio: bool
    audio_url: Optional[str]
    original_transcript: Optional[str]
    stage: str
    status: str
    error_message: Optional[str]
    resolved_item: Optional[KnowledgeItemDTO]

