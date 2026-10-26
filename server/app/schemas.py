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
    relation_type: str = "Related to"  # Supports, Example of, Related to, Depends on, Constrained by
    status: str = "suggested"  # suggested, confirmed

class KnowledgeItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capture_id: str
    title: str
    core_idea: str
    details: str = ""
    transcript: str
    concepts: List[str] = []
    tags: List[str] = []
    open_questions: List[str] = []
    candidate_relations: List[str] = []
    provenance: str = "voice-capture"
    created_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

class GraphNode(BaseModel):
    id: str
    title: str
    kind: str  # 'capture' or 'idea'
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
    pipeline_version: str = "v1.0"

class ScoredKnowledgeItem(BaseModel):
    item: KnowledgeItem
    similarity_score: float

class ConsentUpdateRequest(BaseModel):
    consent_given: bool

