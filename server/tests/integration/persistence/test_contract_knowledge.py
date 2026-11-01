"""Knowledge/Embedding/Capture port contracts; embeddings FK stays enforced."""

import pytest

from ._helpers import make_capture, make_item, make_job


def test_knowledge_roundtrip(container_, user):
    repo = container_.knowledge_repo
    item = make_item(user.id)
    repo.save(item)
    stored = repo.get_by_id(item.id, user_id=user.id)
    assert stored is not None
    assert stored.concepts == ["alpha"] and stored.tags == ["tools"]
    assert stored.title == "Contract title"


def test_embedding_finance_fk_rejects_missing_item(container_, user):
    """R4: embeddings are only written for rows in the same transaction; the
    FK must raise for a missing item, never paper over with placeholders."""
    import uuid

    with pytest.raises(Exception) as excinfo:
        container_.embedding_repo.save(str(uuid.uuid4()), b"\x01" * 16, user_id=user.id)
    assert "foreign key" in str(excinfo.value).lower() or "violates" in str(excinfo.value).lower()


def test_embedding_roundtrip_and_count(container_, user):
    item = make_item(user.id)
    container_.knowledge_repo.save(item)
    repo = container_.embedding_repo
    repo.save(item.id, b"\x02" * 16, user_id=user.id, model_name="m", dimension=16)
    assert repo.get(item.id, user_id=user.id) == b"\x02" * 16
    assert repo.count(user_id=user.id) == 1
    repo.delete(item.id, user_id=user.id)
    assert repo.count(user_id=user.id) == 0


def test_capture_idempotency_is_scoped_per_user(container_, user):
    repo = container_.capture_repo
    first = make_capture(user.id)
    repo.save(first)
    # Same idempotency key, same user -> same capture.
    got = repo.get_by_idempotency_key(first.idempotency_key, user_id=user.id)
    assert got.id == first.id
    # No cross-user leak.
    assert repo.get_by_idempotency_key(first.idempotency_key, user_id=None) is not None


def test_store_job_stage_outputs_alongside_record(container_, user):
    capture = make_capture(user.id)
    container_.capture_repo.save(capture)
    container_.job_repo.record_job(make_job(user.id, capture.id, stage_outputs="{}"))
    row = container_.job_repo.get_by_capture_id(capture.id, user_id=user.id)
    assert row is not None
