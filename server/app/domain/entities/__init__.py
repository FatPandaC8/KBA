import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from ..value_objects import RelationType, RelationStatus, CaptureStatus
from ..errors import ValidationError


def current_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UserEntity:
    id: str
    email: str
    email_normalized: str
    password_hash: Optional[str] = None
    google_sub: Optional[str] = None
    email_verified_at: Optional[str] = None
    is_locked: bool = False
    created_at: str = field(default_factory=current_utc_iso)
    updated_at: str = field(default_factory=current_utc_iso)

    @property
    def email_verified(self) -> bool:
        return bool(self.email_verified_at)

    @classmethod
    def create(cls, email: str, password_hash: Optional[str] = None) -> "UserEntity":
        normalized = (email or "").strip().lower()
        if not normalized:
            raise ValidationError("Email cannot be empty")
        return cls(
            id=str(uuid.uuid4()),
            email=email.strip(),
            email_normalized=normalized,
            password_hash=password_hash,
        )


@dataclass
class ConsentEntity:
    id: str
    user_id: str
    version: str
    providers_hash: str
    providers: List[Dict[str, object]]
    granted: bool
    created_at: str = field(default_factory=current_utc_iso)


@dataclass
class KnowledgeItemEntity:
    id: str
    capture_id: str
    title: str
    core_idea: str
    user_id: str = ""
    details: str = ""
    transcript: str = ""
    concepts: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    candidate_relations: List[str] = field(default_factory=list)
    provenance: str = "voice-capture"
    user_edited: bool = False
    created_at: str = field(default_factory=current_utc_iso)
    updated_at: str = field(default_factory=current_utc_iso)

    @classmethod
    def create(
        cls,
        capture_id: str,
        title: str,
        core_idea: str,
        user_id: str = "",
        details: str = "",
        transcript: str = "",
        concepts: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        open_questions: Optional[List[str]] = None,
        candidate_relations: Optional[List[str]] = None,
        provenance: str = "voice-capture",
        id: Optional[str] = None,
    ) -> "KnowledgeItemEntity":
        clean_title = title.strip()
        if not clean_title:
            raise ValidationError("Title cannot be empty")
        return cls(
            id=id or str(uuid.uuid4()),
            capture_id=capture_id,
            title=clean_title,
            core_idea=core_idea.strip(),
            user_id=user_id,
            details=details.strip(),
            transcript=transcript.strip(),
            concepts=concepts or [],
            tags=tags or [],
            open_questions=open_questions or [],
            candidate_relations=candidate_relations or [],
            provenance=provenance,
            created_at=current_utc_iso(),
            updated_at=current_utc_iso(),
        )


@dataclass
class RelationshipEntity:
    id: str
    from_id: str
    to_id: str
    user_id: str = ""
    relation_type: str = RelationType.RELATED_TO
    status: str = RelationStatus.SUGGESTED
    user_edited: bool = False
    created_at: str = field(default_factory=current_utc_iso)

    @classmethod
    def create(
        cls,
        from_id: str,
        to_id: str,
        user_id: str = "",
        relation_type: str = RelationType.RELATED_TO,
        status: str = RelationStatus.SUGGESTED,
        id: Optional[str] = None,
    ) -> "RelationshipEntity":
        if not from_id or not to_id:
            raise ValidationError("Both from_id and to_id must be provided")
        if from_id == to_id:
            raise ValidationError("Self-referential relationships are not permitted")
        return cls(
            id=id or str(uuid.uuid4()),
            from_id=from_id,
            to_id=to_id,
            user_id=user_id,
            relation_type=relation_type,
            status=status,
            created_at=current_utc_iso(),
        )


@dataclass
class CaptureEntity:
    id: str
    idempotency_key: str
    audio_path: str
    user_id: str = ""
    duration_ms: int = 0
    status: str = CaptureStatus.RECEIVED
    created_at: str = field(default_factory=current_utc_iso)


@dataclass
class EvalRecordEntity:
    id: str
    capture_id: str
    transcript: str
    structured_json: str
    user_id: str = ""
    user_corrected: bool = False
    consent_given: bool = False
    pipeline_version: str = "v1.2"
    created_at: str = field(default_factory=current_utc_iso)
