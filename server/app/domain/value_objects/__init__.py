from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class RelationType:
    SUPPORT: str = "Supports"
    EXAMPLE_OF: str = "Example of"
    RELATED_TO: str = "Related to"
    DEPENDS_ON: str = "Depends on"
    CONSTRAINED_BY: str = "Constrained by"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {
            cls.SUPPORT,
            cls.EXAMPLE_OF,
            cls.RELATED_TO,
            cls.DEPENDS_ON,
            cls.CONSTRAINED_BY,
        }

@dataclass(frozen=True)
class RelationStatus:
    SUGGESTED: str = "suggested"
    CONFIRMED: str = "confirmed"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {cls.SUGGESTED, cls.CONFIRMED}

@dataclass(frozen=True)
class CaptureStatus:
    RECEIVED: str = "received"
    TRANSCRIBING: str = "transcribing"
    EXTRACTING: str = "extracting"
    INDEXING: str = "indexing"
    READY: str = "ready"
    FAILED: str = "failed"
