"""Shared first-person reference mapping to self entity.

Both local and Groq extractors produce entities from first-person pronouns.
This module provides a single post-processing step to map those to the
user's self entity, avoiding duplication across extractors.
"""

import re
from typing import List, Optional

from server.app.domain.entities import ExtractedEntity, EntityType
from server.app.domain.value_objects import EntityType as EntityTypeVO

_FIRST_PERSON_PATTERN = re.compile(
    r"\b(?:i|me|my|myself|mine|I'm|I've|we|our|ours|ourselves)\b", re.IGNORECASE
)

# Patterns that indicate first-person references in extracted entity names
# Note: "minh" is a common name, not just a first-person pronoun in Vietnamese
_FIRST_PERSON_ENTITY_PATTERNS = {
    "i", "me", "my", "myself", "mine", "I'm", "I've", "we", "our", "ours", "ourselves",
}


def map_first_person_to_self(
    entities: List[ExtractedEntity],
    user_id: str,
    capture_id: str,
    self_entity: Optional[ExtractedEntity],
    transcript: Optional[str] = None,
    provider_id: str = "extraction_post_process",
) -> List[ExtractedEntity]:
    """Map first-person entity references to the self entity.

    Replaces all first-person entity references with a SINGLE canonical
    self-entity placeholder (marked is_self=True). The real self entity
    from the database will be substituted in _save_extraction.
    """
    if not entities:
        return entities

    # Check if transcript contains first-person references
    has_first_person = transcript is not None and has_first_person_reference(transcript)

    # Check if there's already a self entity in the input (from LLM)
    existing_self = next((e for e in entities if e.is_self), None)

    # Create a SINGLE canonical self-entity placeholder for this capture
    # This will be replaced by the real self entity in _save_extraction
    placeholder_self = ExtractedEntity(
        id=_stable_self_id(user_id, capture_id),
        capture_id=capture_id,
        name="Me",
        user_id=user_id,
        entity_type=EntityTypeVO.SELF,
        description="",
        confidence=1.0,
        certainty="confirmed",
        provenance="system-self-reference",
        provider_id=provider_id,
        model_version="v2.0",
        is_self=True,
    )

    result = []
    self_added = False

    for entity in entities:
        normalized = entity.normalized_name.lower().strip()
        is_first_person = normalized in _FIRST_PERSON_ENTITY_PATTERNS or _FIRST_PERSON_PATTERN.fullmatch(normalized)

        if is_first_person:
            # Replace ALL first-person references with the SAME canonical placeholder
            if not self_added:
                result.append(entity.__class__(
                    id=entity.id,
                    user_id=entity.user_id,
                    capture_id=entity.capture_id,
                    name=entity.name,
                    entity_type=EntityTypeVO.SELF,
                    description=entity.description,
                    confidence=entity.confidence,
                    certainty=entity.certainty,
                    provenance=entity.provenance,
                    provider_id=entity.provider_id,
                    model_version=entity.model_version,
                    user_edited=entity.user_edited,
                    is_self=True,
                    created_at=entity.created_at,
                    updated_at=entity.updated_at,
                ))
                self_added = True
            continue
        result.append(entity)

    # If transcript has first-person but no first-person entities were found,
    # add the canonical placeholder
    if has_first_person and not self_added:
        result.append(ExtractedEntity(
            id=_stable_self_id(user_id, capture_id),
            capture_id=capture_id,
            name="Me",
            user_id=user_id,
            entity_type=EntityTypeVO.SELF,
            description="",
            confidence=1.0,
            certainty="confirmed",
            provenance="system-self-reference",
            provider_id=provider_id,
            model_version="v2.0",
            is_self=True,
        ))

    return result


def _stable_self_id(user_id: str, capture_id: str) -> str:
    """Generate a stable ID for the self entity reference.

    Uses uuid5 with a namespace so the same user+capture always produces
    the same ID.
    """
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"echo:self_ref:{user_id}:{capture_id}"))


def find_self_entity(entities: List[ExtractedEntity]) -> Optional[ExtractedEntity]:
    """Find the self entity in a list of entities."""
    for e in entities:
        if e.is_self:
            return e
    return None


def has_first_person_reference(transcript: str) -> bool:
    """Check if transcript contains first-person pronouns."""
    return bool(_FIRST_PERSON_PATTERN.search(transcript))