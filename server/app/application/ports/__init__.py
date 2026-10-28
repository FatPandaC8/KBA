from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Dict, Any
from server.app.domain.entities import (
    KnowledgeItemEntity,
    RelationshipEntity,
    CaptureEntity,
    EvalRecordEntity,
)
from ..dto import GraphDataDTO, ProcessingJobDTO

class KnowledgeRepositoryPort(ABC):
    @abstractmethod
    def save(self, item: KnowledgeItemEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, item_id: str) -> Optional[KnowledgeItemEntity]:
        pass

    @abstractmethod
    def get_by_capture_id(self, capture_id: str) -> Optional[KnowledgeItemEntity]:
        pass

    @abstractmethod
    def get_all(self, query: str = "", limit: Optional[int] = None, offset: int = 0) -> List[KnowledgeItemEntity]:
        pass

    @abstractmethod
    def count(self, query: str = "") -> int:
        pass

    @abstractmethod
    def delete(self, item_id: str) -> None:
        pass

class RelationshipRepositoryPort(ABC):
    @abstractmethod
    def save(self, rel: RelationshipEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, rel_id: str) -> Optional[RelationshipEntity]:
        pass

    @abstractmethod
    def get_all(self) -> List[RelationshipEntity]:
        pass

    @abstractmethod
    def update_status(self, rel_id: str, status: str, relation_type: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def delete(self, rel_id: str) -> None:
        pass

    @abstractmethod
    def get_graph(self) -> GraphDataDTO:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

    @abstractmethod
    def count_orphans(self) -> int:
        pass

class EmbeddingRepositoryPort(ABC):
    @abstractmethod
    def save(self, item_id: str, vector_bytes: bytes) -> None:
        pass

    @abstractmethod
    def get_by_item_id(self, item_id: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def get_all(self) -> List[Tuple[str, bytes]]:
        pass

    @abstractmethod
    def delete(self, item_id: str) -> None:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

class CaptureRepositoryPort(ABC):
    @abstractmethod
    def save(self, capture: CaptureEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, capture_id: str) -> Optional[CaptureEntity]:
        pass

    @abstractmethod
    def get_by_idempotency_key(self, key: str) -> Optional[CaptureEntity]:
        pass

    @abstractmethod
    def list_recent(self, limit: int = 50) -> List[CaptureEntity]:
        pass

    @abstractmethod
    def list_all(self) -> List[CaptureEntity]:
        pass

    @abstractmethod
    def delete(self, capture_id: str) -> None:
        pass

    @abstractmethod
    def clear_audio_path(self, capture_id: str) -> None:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

class EvalRecordRepositoryPort(ABC):
    @abstractmethod
    def save(self, record: EvalRecordEntity) -> None:
        pass

    @abstractmethod
    def get_all_consented(self) -> List[EvalRecordEntity]:
        pass

    @abstractmethod
    def purge_unconsented(self) -> int:
        pass

    @abstractmethod
    def purge_all(self) -> int:
        pass

    @abstractmethod
    def delete_by_capture_id(self, capture_id: str) -> int:
        pass

class AudioTranscriptionPort(ABC):
    @abstractmethod
    def transcribe(self, audio_file_path: str) -> str:
        pass

class KnowledgeExtractionPort(ABC):
    @abstractmethod
    def extract(self, transcript: str, capture_id: str) -> KnowledgeItemEntity:
        pass

    @abstractmethod
    def connect(self, new_item: KnowledgeItemEntity, existing_items: List[KnowledgeItemEntity]) -> List[RelationshipEntity]:
        pass

class EmbeddingProviderPort(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> bytes:
        pass

    @abstractmethod
    def embed_item(self, item: KnowledgeItemEntity) -> bytes:
        pass

    @abstractmethod
    def calculate_similarity(self, query_bytes: bytes, target_bytes: bytes) -> float:
        pass

class JobStatusRepositoryPort(ABC):
    @abstractmethod
    def record_job(self, job: ProcessingJobDTO) -> None:
        pass

    @abstractmethod
    def update_job_status(self, capture_id: str, stage: str, status: str, error_message: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def get_recent_jobs(self, limit: int = 50) -> List[ProcessingJobDTO]:
        pass

    @abstractmethod
    def get_by_capture_id(self, capture_id: str) -> Optional[ProcessingJobDTO]:
        pass

    @abstractmethod
    def delete_by_capture_id(self, capture_id: str) -> int:
        pass

