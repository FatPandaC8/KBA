import pytest
from server.app.domain.entities import KnowledgeItemEntity, RelationshipEntity
from server.app.domain.value_objects import RelationType, RelationStatus
from server.app.domain.errors import ValidationError

def test_knowledge_item_creation_validation():
    with pytest.raises(ValidationError):
        KnowledgeItemEntity.create(
            capture_id="cap-1",
            title="   ",
            core_idea="Idea",
        )

    item = KnowledgeItemEntity.create(
        capture_id="cap-valid",
        title="Valid Domain Title",
        core_idea="Core thought",
        concepts=["Domain", "Architecture"],
    )
    assert item.title == "Valid Domain Title"
    assert len(item.concepts) == 2
    assert item.created_at is not None

def test_relationship_entity_validation():
    with pytest.raises(ValidationError):
        RelationshipEntity.create(from_id="", to_id="to-1")

    with pytest.raises(ValidationError):
        RelationshipEntity.create(from_id="same-id", to_id="same-id")

    rel = RelationshipEntity.create(
        from_id="node-a",
        to_id="node-b",
        relation_type=RelationType.SUPPORT,
    )
    assert rel.relation_type == "Supports"
    assert rel.status == "suggested"
