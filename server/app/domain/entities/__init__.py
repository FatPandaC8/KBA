import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from ..value_objects import (
    RelationType,
    RelationStatus,
    Certainty,
    EntityType,
    CaptureStatus,
)
from ..errors import ValidationError


def current_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_key(value: str) -> str:
    """Stable key for duplicate detection and tombstones."""
    return " ".join((value or "").strip().lower().split())


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
    provider_id: str = ""
    model_version: str = ""
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
        provider_id: str = "",
        model_version: str = "",
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
            provider_id=provider_id,
            model_version=model_version,
            created_at=current_utc_iso(),
            updated_at=current_utc_iso(),
        )


@dataclass
class ExtractedEntity:
    """A named entity in the user's knowledge graph (KG-01).

    Provenance is mandatory: every node traces back to the record that
    introduced it, the provider that produced it and a confidence score.
    """

    id: str
    user_id: str
    capture_id: str
    name: str
    entity_type: str = EntityType.CONCEPT
    description: str = ""
    confidence: float = 0.5
    certainty: str = Certainty.CONFIRMED
    provenance: str = "voice-capture"
    provider_id: str = ""
    model_version: str = ""
    user_edited: bool = False
    is_self: bool = False
    created_at: str = field(default_factory=current_utc_iso)
    updated_at: str = field(default_factory=current_utc_iso)

    @property
    def normalized_name(self) -> str:
        return normalize_key(self.name)

    @classmethod
    def create(
        cls,
        capture_id: str,
        name: str,
        user_id: str = "",
        entity_type: str = EntityType.CONCEPT,
        description: str = "",
        confidence: float = 0.5,
        certainty: str = Certainty.CONFIRMED,
        provenance: str = "voice-capture",
        provider_id: str = "",
        model_version: str = "",
        id: Optional[str] = None,
        is_self: bool = False,
    ) -> "ExtractedEntity":
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValidationError("Entity name cannot be empty")
        if not EntityType.is_valid(entity_type):
            raise ValidationError(f"Unsupported entity type: {entity_type}")
        if not Certainty.is_valid(certainty):
            raise ValidationError(f"Unsupported certainty: {certainty}")
        return cls(
            id=id or str(uuid.uuid4()),
            user_id=user_id,
            capture_id=capture_id,
            name=clean_name,
            entity_type=entity_type,
            description=(description or "").strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
            certainty=certainty,
            provenance=provenance,
            provider_id=provider_id,
            model_version=model_version,
            is_self=is_self,
        )


@dataclass
class RelationshipEntity:
    id: str
    from_id: str
    to_id: str
    user_id: str = ""
    relation_type: str = RelationType.RELATED_TO
    status: str = RelationStatus.SUGGESTED
    certainty: str = Certainty.CONFIRMED
    confidence: float = 0.6
    source_capture_id: str = ""
    provenance: str = "voice-capture"
    user_edited: bool = False
    evidence_utterance: str = ""
    created_at: str = field(default_factory=current_utc_iso)

    @classmethod
    def create(
        cls,
        from_id: str,
        to_id: str,
        user_id: str = "",
        relation_type: str = RelationType.RELATED_TO,
        status: str = RelationStatus.SUGGESTED,
        certainty: str = Certainty.CONFIRMED,
        confidence: float = 0.6,
        source_capture_id: str = "",
        provenance: str = "voice-capture",
        id: Optional[str] = None,
        evidence_utterance: str = "",
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
            certainty=certainty,
            confidence=max(0.0, min(1.0, float(confidence))),
            source_capture_id=source_capture_id,
            provenance=provenance,
            evidence_utterance=" ".join((evidence_utterance or "").split()),
            created_at=current_utc_iso(),
        )


@dataclass
class RelationshipTypeRegistryEntry:
    """One canonical relationship meaning in the open-ended registry (U1).

    The registry is not an enum: extractors (and users) may propose new
    canonical meanings, and semantically equivalent proposals must reuse the
    existing entry instead of creating a duplicate.
    """

    id: str
    user_id: str = ""
    canonical_name: str = ""
    semantic_description: str = ""
    aliases: List[str] = field(default_factory=list)
    provenance: str = "registry-seed"
    user_edited: bool = False
    created_at: str = field(default_factory=current_utc_iso)
    updated_at: str = field(default_factory=current_utc_iso)

    @property
    def normalized_key(self) -> str:
        return normalize_key(self.canonical_name)

    @property
    def normalized_aliases(self) -> List[str]:
        return [normalize_key(alias) for alias in self.aliases if normalize_key(alias)]

    @classmethod
    def create(
        cls,
        canonical_name: str,
        user_id: str = "",
        semantic_description: str = "",
        aliases: Optional[List[str]] = None,
        provenance: str = "registry-seed",
        user_edited: bool = False,
    ) -> "RelationshipTypeRegistryEntry":
        canonical = canonical_relation_name(canonical_name)
        if not canonical:
            raise ValidationError("A canonical relationship name is required")
        return cls(
            id=_registry_id(user_id, canonical),
            user_id=user_id,
            canonical_name=canonical,
            semantic_description=" ".join((semantic_description or "").split()),
            aliases=_clean_aliases(aliases),
            provenance=provenance,
            user_edited=user_edited,
        )


def canonical_relation_name(value: str) -> str:
    """Deterministic canonical form: underscores become spaces, whitespace is
    collapsed and the first letter is capitalised (matching the historical
    relation labels such as "Depends on"), so an extraction proposal like
    "works at" becomes "Works at" and "works_at" becomes "Works at" too.
    """
    collapsed = " ".join((value or "").replace("_", " ").split())
    if not collapsed:
        return ""
    return collapsed[0].upper() + collapsed[1:]


def _clean_aliases(aliases: Optional[List[str]]) -> List[str]:
    cleaned: List[str] = []
    for alias in aliases or []:
        collapsed = " ".join((alias or "").split())
        if collapsed and collapsed.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(collapsed)
        if len(cleaned) >= 10:
            break
    return cleaned


def _registry_id(user_id: str, canonical: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "echo:relationship_type:" + user_id + ":" + normalize_key(canonical)))


def _seed(canonical: str, description: str, aliases: List[str]) -> RelationshipTypeRegistryEntry:
    return RelationshipTypeRegistryEntry.create(
        canonical_name=canonical,
        user_id="",
        semantic_description=description,
        aliases=aliases,
        provenance="registry-seed",
    )


# Seed meanings that existed before the registry became open-ended. New
# canonical meanings come from extraction proposals or user edits and are
# persisted in the ``relationship_types`` table instead of here.
DEFAULT_RELATIONSHIP_TYPES: List[RelationshipTypeRegistryEntry] = [
    _seed(
        "Depends on",
        "The source needs, relies on, requires, or is blocked by the target "
        "(direction: source depends on target).",
        ["depends on", "relies on", "requires", "needs", "prerequisite of", "waiting for", "waiting on"],
    ),
    _seed(
        "Supports",
        "The source endorses, helps, enables, backs or improves the target "
        "(direction: source supports target).",
        ["supports", "backs", "endorses", "helps", "enables", "improves", "advocates", "is behind", "champions"],
    ),
    _seed(
        "Example of",
        "The source is an example, instance, sample or special case of the target.",
        ["example of", "such as", "for instance", "instance of", "sample of"],
    ),
    _seed(
        "Constrained by",
        "The source is limited, bound, restricted or governed by the target.",
        ["constrained by", "limited by", "bound by", "restricted by", "governed by", "must comply with"],
    ),
    _seed(
        "Contradicts",
        "The source states or expresses a fact that conflicts with the target.",
        ["contradicts", "conflicts with", "disagrees with", "opposes", "is wrong about"],
    ),
    _seed(
        "Related to",
        "The source and target are explicitly stated together but the utterance "
        "does not determine a more specific meaning. This is a last resort, "
        "never inferred from mere co-occurrence.",
        ["related to", "connected to", "associated with", "linked to", "about"],
    ),
]


@dataclass
class CaptureEntity:
    id: str
    idempotency_key: str
    audio_path: str
    user_id: str = ""
    duration_ms: int = 0
    status: str = CaptureStatus.RECEIVED
    stage: str = "uploaded"
    error_class: str = ""
    error_message: str = ""
    retry_count: int = 0
    user_edited_title: bool = False
    user_edited_summary: bool = False
    knowledge_item_id: Optional[str] = None
    has_audio: bool = False
    audio_on_server: bool = False
    created_at: str = field(default_factory=current_utc_iso)
    updated_at: str = field(default_factory=current_utc_iso)


@dataclass
class EmailTokenEntity:
    id: str
    token_hash: str
    user_id: str
    purpose: str
    expires_at: str
    consumed_at: Optional[str] = None
    created_at: str = field(default_factory=current_utc_iso)


@dataclass
class SessionEntity:
    id: str
    user_id: str
    token_hash: str
    created_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


@dataclass
class ProcessingJobDTO:
    id: str
    user_id: str
    capture_id: Optional[str]
    stage: str
    status: str
    attempt: int
    error_class: str
    lease_owner: str
    lease_expires_at: Optional[str]
    stage_outputs: Dict[str, Any]
    duration_ms: Optional[int]
    error_message: Optional[str]
    created_at: str
    updated_at: str


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
