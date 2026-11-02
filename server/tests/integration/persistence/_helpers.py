from server.app.domain.entities import (
    CaptureEntity,
    ExtractedEntity,
    KnowledgeItemEntity,
)


def make_entity(user_id: str, name: str = "Alpha", **kwargs) -> ExtractedEntity:
    import uuid

    defaults = dict(
        id=str(uuid.uuid4()),
        user_id=user_id,
        capture_id=None,
        name=name,
        entity_type="tool",
        description="",
        confidence=0.5,
        certainty="confirmed",
        provenance="test",
        provider_id="test",
        model_version="t",
        user_edited=False,
        is_self=False,
    )
    defaults.update(kwargs)
    return ExtractedEntity(**defaults)


def make_item(user_id: str, item_id: str = None, **kwargs) -> KnowledgeItemEntity:
    import uuid

    defaults = dict(
        id=item_id or str(uuid.uuid4()),
        capture_id=None,
        user_id=user_id,
        title="Contract title",
        core_idea="Contract idea",
        details="",
        transcript="alpha beta",
        concepts=["alpha"],
        tags=["tools"],
        open_questions=[],
        candidate_relations=[],
        provenance="test",
        provider_id="test",
        model_version="t",
        user_edited=False,
    )
    defaults.update(kwargs)
    return KnowledgeItemEntity(**defaults)


def make_capture(user_id: str, **kwargs) -> CaptureEntity:
    import uuid

    now = "2026-01-01T00:00:00+00:00"
    defaults = dict(
        id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        user_id=user_id,
        audio_path=None,
        duration_ms=1,
        status="received",
        user_edited_title=False,
        user_edited_summary=False,
        knowledge_item_id=None,
        has_audio=False,
        audio_on_server=False,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return CaptureEntity(**defaults)
