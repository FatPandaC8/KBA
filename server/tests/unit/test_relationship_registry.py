"""U3/U6 (partially): registry entry domain validation.

Database-backed registry semantics are covered by the shared contract suite
(tests/integration/persistence/test_contract_registry.py against the real
Postgres adapter).
"""

import pytest

from server.app.domain.entities import RelationshipTypeRegistryEntry
from server.app.domain.errors import ValidationError


def test_invalid_canonical_names_are_refused():
    with pytest.raises(ValidationError):
        RelationshipTypeRegistryEntry.create("", "")
    with pytest.raises(ValidationError):
        RelationshipTypeRegistryEntry.create("   ", "")
    with pytest.raises(ValidationError):
        RelationshipTypeRegistryEntry.create(None, "")  # type: ignore[arg-type]
