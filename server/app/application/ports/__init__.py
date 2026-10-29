from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Dict, Any

from server.app.domain.entities import (
    KnowledgeItemEntity,
    RelationshipEntity,
    CaptureEntity,
    EvalRecordEntity,
    UserEntity,
    ConsentEntity,
)
from ..dto import GraphDataDTO, ProcessingJobDTO


class UserRepositoryPort(ABC):
    @abstractmethod
    def save(self, user: UserEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, user_id: str) -> Optional[UserEntity]:
        pass

    @abstractmethod
    def get_by_email(self, email_normalized: str) -> Optional[UserEntity]:
        pass

    @abstractmethod
    def get_by_google_sub(self, google_sub: str) -> Optional[UserEntity]:
        pass

    @abstractmethod
    def update(self, user: UserEntity) -> None:
        pass

    @abstractmethod
    def delete(self, user_id: str) -> None:
        pass

    @abstractmethod
    def count(self) -> int:
        pass


class SessionRepositoryPort(ABC):
    @abstractmethod
    def create(self, user_id: str, token_hash: str, expires_at: str) -> None:
        pass

    @abstractmethod
    def get_user_by_token_hash(self, token_hash: str) -> Optional[UserEntity]:
        pass

    @abstractmethod
    def touch(self, token_hash: str) -> None:
        pass

    @abstractmethod
    def revoke(self, token_hash: str) -> None:
        pass

    @abstractmethod
    def revoke_all_for_user(self, user_id: str) -> int:
        pass

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        pass


class EmailTokenRepositoryPort(ABC):
    @abstractmethod
    def create(self, user_id: str, purpose: str, token_hash: str, expires_at: str) -> None:
        pass

    @abstractmethod
    def consume(self, token_hash: str, purpose: str) -> Optional[str]:
        """Atomically mark the token used and return its user id."""

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        pass


class ConsentRepositoryPort(ABC):
    @abstractmethod
    def save(self, consent: ConsentEntity) -> None:
        pass

    @abstractmethod
    def get_latest(self, user_id: str) -> Optional[ConsentEntity]:
        pass

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        pass


class TombstoneRepositoryPort(ABC):
    @abstractmethod
    def add(self, user_id: str, kind: str, normalized_key: str) -> None:
        pass

    @abstractmethod
    def is_tombstoned(self, user_id: str, kind: str, normalized_key: str) -> bool:
        pass

    @abstractmethod
    def list_for_user(self, user_id: str) -> List[Dict[str, str]]:
        pass

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        pass


class RecordSupportRepositoryPort(ABC):
    @abstractmethod
    def add(self, user_id: str, record_id: str, target_kind: str, target_id: str) -> None:
        pass

    @abstractmethod
    def list_for_record(self, user_id: str, record_id: str) -> List[Dict[str, str]]:
        pass

    @abstractmethod
    def list_for_target(self, user_id: str, target_kind: str, target_id: str) -> List[Dict[str, str]]:
        pass

    @abstractmethod
    def delete_for_record(self, user_id: str, record_id: str) -> int:
        pass

    @abstractmethod
    def delete_for_target(self, user_id: str, target_kind: str, target_id: str) -> int:
        pass

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        pass


class KnowledgeRepositoryPort(ABC):
    @abstractmethod
    def save(self, item: KnowledgeItemEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[KnowledgeItemEntity]:
        pass

    @abstractmethod
    def get_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[KnowledgeItemEntity]:
        pass

    @abstractmethod
    def get_all(self, query: str = "", limit: Optional[int] = None, offset: int = 0, user_id: Optional[str] = None) -> List[KnowledgeItemEntity]:
        pass

    @abstractmethod
    def count(self, query: str = "", user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        pass


class RelationshipRepositoryPort(ABC):
    @abstractmethod
    def save(self, rel: RelationshipEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, rel_id: str, user_id: Optional[str] = None) -> Optional[RelationshipEntity]:
        pass

    @abstractmethod
    def get_all(self, user_id: Optional[str] = None) -> List[RelationshipEntity]:
        pass

    @abstractmethod
    def update_status(self, rel_id: str, status: str, relation_type: Optional[str] = None, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def delete(self, rel_id: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def get_graph(self, user_id: Optional[str] = None) -> GraphDataDTO:
        pass

    @abstractmethod
    def count(self, user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def count_orphans(self, user_id: Optional[str] = None) -> int:
        pass


class EmbeddingRepositoryPort(ABC):
    @abstractmethod
    def save(self, item_id: str, vector_bytes: bytes, user_id: str = "", model_name: str = "", dimension: int = 0) -> None:
        pass

    @abstractmethod
    def get_by_item_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[bytes]:
        pass

    @abstractmethod
    def get_all(self, user_id: Optional[str] = None) -> List[Tuple[str, bytes]]:
        pass

    @abstractmethod
    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def count(self, user_id: Optional[str] = None) -> int:
        pass


class CaptureRepositoryPort(ABC):
    @abstractmethod
    def save(self, capture: CaptureEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[CaptureEntity]:
        pass

    @abstractmethod
    def get_by_idempotency_key(self, key: str, user_id: Optional[str] = None) -> Optional[CaptureEntity]:
        pass

    @abstractmethod
    def list_recent(self, limit: int = 50, user_id: Optional[str] = None) -> List[CaptureEntity]:
        pass

    @abstractmethod
    def list_all(self, user_id: Optional[str] = None) -> List[CaptureEntity]:
        pass

    @abstractmethod
    def delete(self, capture_id: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def clear_audio_path(self, capture_id: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def count(self, user_id: Optional[str] = None) -> int:
        pass


class EvalRecordRepositoryPort(ABC):
    @abstractmethod
    def save(self, record: EvalRecordEntity) -> None:
        pass

    @abstractmethod
    def get_all_consented(self, user_id: Optional[str] = None) -> List[EvalRecordEntity]:
        pass

    @abstractmethod
    def purge_unconsented(self, user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def purge_all(self) -> int:
        pass

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        pass


class AudioTranscriptionPort(ABC):
    @abstractmethod
    def transcribe(self, audio_file_path: str) -> str:
        pass


class KnowledgeExtractionPort(ABC):
    @abstractmethod
    def extract(self, transcript: str, capture_id: str, user_id: str = "") -> KnowledgeItemEntity:
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
    def update_job_status(self, capture_id: str, stage: str, status: str, error_message: Optional[str] = None, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def get_recent_jobs(self, limit: int = 50, user_id: Optional[str] = None) -> List[ProcessingJobDTO]:
        pass

    @abstractmethod
    def get_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[ProcessingJobDTO]:
        pass

    @abstractmethod
    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        pass


class EmailPort(ABC):
    @abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> None:
        pass


class GoogleTokenVerifierPort(ABC):
    @abstractmethod
    def verify(self, id_token: str) -> Dict[str, object]:
        """Return {sub, email, email_verified} or raise a domain error."""
