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
class CitationDTO:
    id: str
    kind: str
    target_id: str
    name: str
    deleted: bool = False


@dataclass
class MessageDTO:
    id: str
    role: str
    content: str
    status: str
    error_class: str
    error_message: str
    created_at: str
    citations: List[CitationDTO] = field(default_factory=list)


@dataclass
class ConversationDTO:
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[MessageDTO] = field(default_factory=list)


@dataclass
class AnswerDTO:
    conversation_id: str
    message: MessageDTO
    facts: List[str] = field(default_factory=list)
    inferences: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str = ""


@dataclass
class ExtractionResult:
    """Everything one transcription produces, with provenance (KG-01)."""

    knowledge_item: KnowledgeItemEntity
    entities: List[ExtractedEntity] = field(default_factory=list)
    relationships: List[RelationshipEntity] = field(default_factory=list)


@dataclass
class EvidenceItem:
    """One retrieval hit passed to the answer provider.

    ``text`` is a summary/description derived from extracted knowledge, never
    the raw transcript.
    """

    kind: str
    target_id: str
    name: str
    entity_type: str = ""
    description: str = ""
    certainty: str = "confirmed"
    confidence: float = 0.0
    score: float = 0.0
    relation_type: str = ""
    related_name: str = ""
    source_capture_id: str = ""


@dataclass
class AnswerDraft:
    text: str
    facts: List[str] = field(default_factory=list)
    inferences: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    citations: List["CitationDTO"] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str = ""


@dataclass
class ProviderInfoDTO:
    id: str
    name: str
    kind: str
    receives: List[str]
    trains_on_data: bool
    available: bool
    detail: str = ""
