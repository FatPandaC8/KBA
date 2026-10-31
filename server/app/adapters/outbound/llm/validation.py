"""Strict JSON schemas and validators for both LLM stages.

The schema is sent to Groq in strict structured-output mode *and* checked again
locally. Provider-side constrained decoding is a strong guarantee, not a trust
boundary: persisted graph data is validated here regardless of provider.
"""

from typing import Any, Dict, List

from server.app.domain.errors import ProviderSchemaError
from server.app.domain.entities import canonical_relation_name
from server.app.domain.value_objects import EntityType

ENTITY_TYPES = [
    EntityType.PERSON,
    EntityType.PROJECT,
    EntityType.ORGANIZATION,
    EntityType.PLACE,
    EntityType.CONCEPT,
    EntityType.TOOL,
    EntityType.IDEA,
]
EXTRACTION_SCHEMA_NAME = "echo_graph_extraction"
EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "core_idea": {"type": "string"},
        "entities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 40,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ENTITY_TYPES},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["name", "type", "confidence"],
                "additionalProperties": False,
            },
        },
        "relationships": {
            "type": "array",
            "maxItems": 80,
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["source", "target", "relation_type", "evidence", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "core_idea", "entities", "relationships"],
    "additionalProperties": False,
}

TEST_SCHEMA_NAME = "echo_provider_test"
TEST_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _schema_error(message: str) -> ProviderSchemaError:
    return ProviderSchemaError(f"LLM output did not match the required schema: {message}")


def _confidence(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _schema_error(f"{field}.confidence must be a number")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise _schema_error(f"{field}.confidence must be between 0 and 1")
    return value


def _text(value: Any, field: str, max_len: int = 400) -> str:
    if not isinstance(value, str):
        raise _schema_error(f"{field} must be a string")
    clean = " ".join(value.split())
    if not clean:
        raise _schema_error(f"{field} cannot be empty")
    if len(clean) > max_len:
        raise _schema_error(f"{field} exceeds {max_len} characters")
    return clean


def _string_list(value: Any, field: str, max_items: int = 40) -> List[str]:
    if not isinstance(value, list):
        raise _schema_error(f"{field} must be an array")
    if len(value) > max_items:
        raise _schema_error(f"{field} has too many items")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _schema_error(f"{field} items must be strings")
        clean = item.strip()
        if clean:
            result.append(clean)
    return result


def normalize_relation_type(value: str) -> str:
    """Open-ended relation type from a free-text proposal (U1).

    Types are no longer restricted to an enum. The proposal must at least
    look like a human phrase, and it is returned in the deterministic
    canonical form used by the registry; the equivalence decision (reuse an
    existing canonical meaning vs. register a new one) is made later against
    the registry, never here.
    """
    if not isinstance(value, str):
        raise _schema_error("relation_type must be a string")
    canonical = canonical_relation_name(value)
    if not canonical or len(canonical) > 60:
        raise _schema_error(f"relation_type must be 1-60 characters: {value!r}")
    letters = sum(1 for ch in canonical if ch.isalpha())
    if letters < 2 or letters / max(1, len(canonical.replace(" ", ""))) < 0.6:
        raise _schema_error(f"relation_type must be a meaningful phrase: {value!r}")
    return canonical


def validate_extraction(data: Any) -> Dict[str, Any]:
    """Validate and normalise an extraction payload.

    Relationships must reference a declared entity by name. Self-links and
    duplicates are dropped rather than failing the whole extraction, because
    they cannot corrupt the graph.
    """
    if not isinstance(data, dict):
        raise _schema_error("root must be an object")

    title = _text(data.get("title"), "title", 160)
    core_idea = _text(data.get("core_idea"), "core_idea", 600)

    raw_entities = data.get("entities")
    if not isinstance(raw_entities, list) or not raw_entities:
        raise _schema_error("entities must be a non-empty array")
    if len(raw_entities) > 40:
        raise _schema_error("too many entities")

    entities: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(raw_entities):
        if not isinstance(item, dict):
            raise _schema_error(f"entities[{index}] must be an object")
        name = _text(item.get("name"), f"entities[{index}].name", 120)
        entity_type = item.get("type")
        if entity_type not in ENTITY_TYPES:
            raise _schema_error(f"entities[{index}].type is invalid")
        confidence = _confidence(item.get("confidence"), f"entities[{index}]")
        key = (name.lower(), entity_type)
        if key in seen:
            continue
        seen.add(key)
        entities.append({"name": name, "type": entity_type, "confidence": confidence})

    if not entities:
        raise _schema_error("no usable entities")

    names = {entity["name"].lower() for entity in entities}
    raw_relations = data.get("relationships", [])
    if not isinstance(raw_relations, list):
        raise _schema_error("relationships must be an array")
    if len(raw_relations) > 80:
        raise _schema_error("too many relationships")

    relationships: List[Dict[str, Any]] = []
    deduped = set()
    for index, item in enumerate(raw_relations):
        if not isinstance(item, dict):
            raise _schema_error(f"relationships[{index}] must be an object")
        source = _text(item.get("source"), f"relationships[{index}].source", 120)
        target = _text(item.get("target"), f"relationships[{index}].target", 120)
        relation_type = normalize_relation_type(item.get("relation_type"))
        evidence = _text(item.get("evidence"), f"relationships[{index}].evidence", 280)
        confidence = _confidence(item.get("confidence"), f"relationships[{index}]")
        if source.lower() not in names or target.lower() not in names:
            # A relationship to an undeclared node would dangle. Drop it.
            continue
        if source.lower() == target.lower():
            continue
        key = (source.lower(), target.lower(), relation_type)
        if key in deduped:
            continue
        deduped.add(key)
        relationships.append(
            {
                "source": source,
                "target": target,
                "relation_type": relation_type,
                "evidence": evidence,
                "confidence": confidence,
            }
        )

    return {
        "title": title,
        "core_idea": core_idea,
        "entities": entities,
        "relationships": relationships,
    }
