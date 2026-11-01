from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class RelationType:
    SUPPORT: str = "Supports"
    EXAMPLE_OF: str = "Example of"
    RELATED_TO: str = "Related to"
    DEPENDS_ON: str = "Depends on"
    CONSTRAINED_BY: str = "Constrained by"
    CONTRADICTS: str = "Contradicts"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {
            cls.SUPPORT,
            cls.EXAMPLE_OF,
            cls.RELATED_TO,
            cls.DEPENDS_ON,
            cls.CONSTRAINED_BY,
            cls.CONTRADICTS,
        }

@dataclass(frozen=True)
class RelationStatus:
    SUGGESTED: str = "suggested"
    CONFIRMED: str = "confirmed"
    CONFLICTING: str = "conflicting"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {cls.SUGGESTED, cls.CONFIRMED, cls.CONFLICTING}


@dataclass(frozen=True)
class Certainty:
    """How sure the extraction is about a node or edge (KG-03, KG-06)."""

    CONFIRMED: str = "confirmed"
    UNCERTAIN: str = "uncertain"
    CONFLICTING: str = "conflicting"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {cls.CONFIRMED, cls.UNCERTAIN, cls.CONFLICTING}


@dataclass(frozen=True)
class EntityType:
    PERSON: str = "person"
    PROJECT: str = "project"
    ORGANIZATION: str = "organization"
    PLACE: str = "place"
    CONCEPT: str = "concept"
    TOOL: str = "tool"
    IDEA: str = "idea"
    SELF: str = "self"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {
            cls.PERSON,
            cls.PROJECT,
            cls.ORGANIZATION,
            cls.PLACE,
            cls.CONCEPT,
            cls.TOOL,
            cls.IDEA,
            cls.SELF,
        }


@dataclass(frozen=True)
class CaptureStatus:
    RECEIVED: str = "received"
    TRANSCRIBING: str = "transcribing"
    EXTRACTING: str = "extracting"
    INDEXING: str = "indexing"
    READY: str = "ready"
    FAILED: str = "failed"


@dataclass(frozen=True)
class JobStage:
    """Ordered pipeline stages. Persisted, so a restart resumes at the stage."""

    UPLOAD: str = "upload"
    TRANSCRIBE: str = "transcribe"
    EXTRACT: str = "extract"
    SAVE: str = "save"
    COMPLETED: str = "completed"

    ORDER: tuple = ("upload", "transcribe", "extract", "save", "completed")

    @classmethod
    def rank(cls, stage: str) -> int:
        try:
            return cls.ORDER.index(stage)
        except ValueError:
            return -1


@dataclass(frozen=True)
class JobStatus:
    QUEUED: str = "queued"
    RUNNING: str = "running"
    PROCESSING: str = "processing"
    READY: str = "ready"
    COMPLETED: str = "completed"
    FAILED: str = "failed"

    @classmethod
    def is_terminal(cls, value: str) -> bool:
        return value in {cls.READY, cls.COMPLETED, cls.FAILED}


@dataclass(frozen=True)
class ErrorClass:
    """Label constants for failure classes (classification lives in
    ``server.app.domain.job_state`` — RETRYABLE_CLASSES/TERMINAL_CLASSES)."""

    QUOTA_EXHAUSTED: str = "quota_exhausted"
    NETWORK: str = "network_error"
    PROVIDER: str = "provider_failure"
    SCHEMA_INVALID: str = "schema_invalid"
    INVALID_INPUT: str = "invalid_input"
    UNKNOWN: str = "unknown"
    TIMEOUT: str = "timeout"
    UNSUPPORTED_LANGUAGE: str = "unsupported_language"

    @classmethod
    def is_recoverable(cls, value: str) -> bool:
        # Delegate to the single domain table (no duplicated policy here).
        from server.app.domain.job_state import is_retryable

        return is_retryable(value)
