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
    """Capture truth (pipeline split, S2): the two synchronous APIs persist a
    capture only in one UoW (received -> ready). Worker stage names are gone."""
    RECEIVED: str = "received"
    READY: str = "ready"
    FAILED: str = "failed"


@dataclass(frozen=True)
class ErrorClass:
    """Label constants for failure classes reported by the STT/Text-KB ports."""

    QUOTA_EXHAUSTED: str = "quota_exhausted"
    NETWORK: str = "network_error"
    PROVIDER: str = "provider_failure"
    SCHEMA_INVALID: str = "schema_invalid"
    INVALID_INPUT: str = "invalid_input"
    UNKNOWN: str = "unknown"
    TIMEOUT: str = "timeout"
    UNSUPPORTED_LANGUAGE: str = "unsupported_language"
