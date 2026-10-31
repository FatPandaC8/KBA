from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from server.app.domain.entities import ExtractedEntity, KnowledgeItemEntity, RelationshipEntity


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
    provider_id: str = ""
    model_version: str = ""


@dataclass
class EntityDTO:
    id: str
    name: str
    entity_type: str
    description: str
    confidence: float
    certainty: str
    provenance: str
    capture_id: str
    created_at: str
    updated_at: str
    provider_id: str = ""
    model_version: str = ""


@dataclass
class RelationshipDTO:
    id: str
    from_id: str
    to_id: str
    relation_type: str
    status: str
    created_at: str
    certainty: str = "confirmed"
    confidence: float = 0.6
    source_capture_id: str = ""


@dataclass
class GraphNodeDTO:
    id: str
    title: str
    kind: str
    x: float
    y: float
    cluster_id: str = ""
    certainty: str = "confirmed"
    confidence: float = 0.5
    degree: int = 0


@dataclass
class GraphEdgeDTO:
    id: str
    from_node: str
    to_node: str
    type: str
    status: str
    certainty: str = "confirmed"
    confidence: float = 0.6
    evidence: str = ""


@dataclass
class GraphClusterDTO:
    id: str
    label: str
    x: float
    y: float
    size: int


@dataclass
class GraphDataDTO:
    nodes: List[GraphNodeDTO]
    edges: List[GraphEdgeDTO]
    clusters: List[GraphClusterDTO] = field(default_factory=list)


@dataclass
class ScoredKnowledgeItemDTO:
    item: KnowledgeItemDTO
    similarity_score: float


@dataclass
class ScoredEntityDTO:
    entity: EntityDTO
    score: float


@dataclass
class GraphSearchDTO:
    entities: List[ScoredEntityDTO]
    relationships: List[RelationshipDTO]


@dataclass
class CaptureUploadResultDTO:
    capture_id: str
    status: str
    knowledge_item: Optional[KnowledgeItemDTO]
    relationships: List[RelationshipDTO]
    entities: List[EntityDTO] = field(default_factory=list)


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
    entity_count: int = 0


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


@dataclass
class ExtractionResult:
    """Everything one transcription produces, with provenance (KG-01)."""

    knowledge_item: KnowledgeItemEntity
    entities: List[ExtractedEntity] = field(default_factory=list)
    relationships: List[RelationshipEntity] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderInfoDTO:
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


@dataclass
class LLMResponse:
    """One validated JSON response from a provider.

    ``content`` is already parsed JSON. ``usage`` carries the provider's token
    accounting so the pipeline can budget against TPM/TPD without trusting an
    estimate.
    """

    content: Dict[str, Any]
    raw_text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    attempts: int = 1
    latency_ms: int = 0
    finish_reason: str = ""
