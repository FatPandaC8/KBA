from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Dict, Any

from server.app.domain.entities import (
    KnowledgeItemEntity,
    ExtractedEntity,
    RelationshipEntity,
    RelationshipTypeRegistryEntry,
    CaptureEntity,
    EvalRecordEntity,
    UserEntity,
    ConsentEntity,
)
from ..dto import (
    GraphDataDTO,
    ProcessingJobDTO,
    ProviderInfoDTO,
    ExtractionResult,
    LLMResponse,
)


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


class EntityRepositoryPort(ABC):
    @abstractmethod
    def save(self, entity: ExtractedEntity) -> None:
        pass

    @abstractmethod
    def get_by_id(self, entity_id: str, user_id: Optional[str] = None) -> Optional[ExtractedEntity]:
        pass

    @abstractmethod
    def get_all(self, user_id: Optional[str] = None, limit: Optional[int] = None) -> List[ExtractedEntity]:
        pass

    @abstractmethod
    def list_by_capture(self, capture_id: str, user_id: Optional[str] = None) -> List[ExtractedEntity]:
        pass

    @abstractmethod
    def find_by_normalized(self, user_id: str, normalized_name: str) -> List[ExtractedEntity]:
        pass

    @abstractmethod
    def count(self, user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def delete(self, entity_id: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def update_fields(self, entity_id: str, user_id: str, name: Optional[str], description: Optional[str]) -> bool:
        pass


class DuplicateCandidateRepositoryPort(ABC):
    @abstractmethod
    def record(self, user_id: str, entity_id: str, candidate_id: str, score: float, decision: str) -> None:
        """Persist a compared pair. ``decision`` is auto_linked or flagged."""

    @abstractmethod
    def list_flagged(self, user_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
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
    def get_between(self, user_id: str, from_id: str, to_id: str) -> List[RelationshipEntity]:
        pass

    @abstractmethod
    def list_for_entity(self, user_id: str, entity_id: str) -> List[RelationshipEntity]:
        pass

    @abstractmethod
    def update_status(self, rel_id: str, status: str, relation_type: Optional[str] = None, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def delete(self, rel_id: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> int:
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
    def extract_graph(
        self,
        transcript: str,
        capture_id: str,
        user_id: str = "",
        registry_snapshot: Optional[List[Dict[str, Any]]] = None,
    ) -> ExtractionResult:
        """Extract the summary record, entities and relationships in one pass.

        ``registry_snapshot`` carries the user's relationship registry (U1) so
        the extractor can reuse canonical meanings instead of proposing
        variants. The result is deterministic for the same transcript and
        snapshot, so a retried stage produces identical identifiers (PRC-04).
        """


class LLMChatPort(ABC):
    """Provider-agnostic, JSON-only chat completion.

    Adapters receive text only (never audio) and return parsed JSON plus token
    usage. Implementations must raise typed domain errors, never fall back to
    another provider, and never log prompts, responses or credentials.
    """

    provider: str = ""
    model: str = ""

    @abstractmethod
    def complete_json(
        self,
        *,
        operation: str,
        system: str,
        user: str,
        schema: Dict[str, Any],
        schema_name: str,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> "LLMResponse":
        pass


class LLMUsageRepositoryPort(ABC):
    @abstractmethod
    def record(
        self,
        *,
        user_id: str,
        provider: str,
        model: str,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        status: str = "success",
    ) -> None:
        pass

    @abstractmethod
    def usage_since(self, since_iso: str, user_id: Optional[str] = None) -> Dict[str, int]:
        """Return {calls, total_tokens} recorded since ``since_iso``."""

    @abstractmethod
    def last_calls(self, limit: int = 20) -> List[Dict[str, Any]]:
        pass


class RelationshipTypeRegistryPort(ABC):
    """Open-ended relationship registry (U1) backing store."""

    @abstractmethod
    def list_for_user(self, user_id: Optional[str] = None) -> List[RelationshipTypeRegistryEntry]:
        """Registry entries visible to the user (plus persisted entries shared
        by all users with an empty ``user_id``)."""

    @abstractmethod
    def find_equivalent(
        self, user_id: Optional[str], names: List[str]
    ) -> Optional[RelationshipTypeRegistryEntry]:
        """Deterministically match a proposed meaning against registered
        canonical names and aliases, returning the first equivalent entry."""

    @abstractmethod
    def ensure(
        self,
        user_id: Optional[str],
        canonical_name: str,
        semantic_description: str = "",
        aliases: Optional[List[str]] = None,
        provenance: str = "extraction",
        user_edited: bool = False,
    ) -> RelationshipTypeRegistryEntry:
        """Return the equivalent existing entry or persist a new one."""

    @abstractmethod
    def update(
        self,
        entry_id: str,
        *,
        semantic_description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> bool:
        """Refine an entry's description/aliases (never the canonical key)."""


class AppSettingsRepositoryPort(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        pass

    @abstractmethod
    def all(self) -> Dict[str, str]:
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

    @property
    def model_name(self) -> str:
        return ""


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

    @abstractmethod
    def claim(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None, retry_limit: int = 3) -> Optional[ProcessingJobDTO]:
        """Atomically take the job lease. Returns None when already leased."""

    @abstractmethod
    def renew_lease(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None) -> bool:
        """Extend a live lease without releasing it (long provider calls)."""

    @abstractmethod
    def complete(self, capture_id: str, user_id: Optional[str] = None) -> None:
        """Mark the job ready and release the lease atomically."""

    @abstractmethod
    def release(self, capture_id: str, lease_owner: str, user_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def save_stage_output(self, capture_id: str, stage: str, outputs: Dict[str, Any], user_id: Optional[str] = None) -> None:
        """Persist stage output and advance the stage idempotently."""

    @abstractmethod
    def record_attempt(self, capture_id: str, attempt: int, error_class: str, error_message: str, user_id: Optional[str] = None, retry_limit: int = 3) -> None:
        pass

    @abstractmethod
    def list_resumable(self, now_iso: str, limit: int = 20, retry_limit: int = 3) -> List[ProcessingJobDTO]:
        """Jobs whose lease expired or which failed recoverably."""


class ProviderRegistryPort(ABC):
    @abstractmethod
    def list_providers(self) -> List[ProviderInfoDTO]:
        pass


class AdminAuditLogPort(ABC):
    """Append-only audit trail for administrative operations (U4)."""

    @abstractmethod
    def record(
        self,
        action: str,
        resource_type: str = "",
        resource_id: str = "",
        user_id: str = "",
        ip_address: str = "unknown",
        outcome: str = "success",
        detail: str = "",
        actor: str = "admin",
    ) -> None:
        """Write one audit row. Never log raw credentials or tokens."""

    @abstractmethod
    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Newest audit rows first."""

    @abstractmethod
    def delete_for_user(self, user_id: str) -> int:
        """Purge rows attributable to one user's data on account deletion."""


class EmailPort(ABC):
    @abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> None:
        pass


class GoogleTokenVerifierPort(ABC):
    @abstractmethod
    def verify(self, id_token: str) -> Dict[str, object]:
        """Return {sub, email, email_verified} or raise a domain error."""
