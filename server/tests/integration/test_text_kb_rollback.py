"""Rollback + retry integration (pipeline split, S4/S2): a failure in the
middle of the Text-KB unit of work must leave NOTHING — no capture, no
knowledge item, no entities/relationships, no support rows — and a retry with
the SAME capture_id must succeed cleanly.

Real Postgres, real UoW, rule-based extractor (no LLM needed).
"""

import uuid

from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.main import app

client = TestClient(app)


def _auth(event, capture_id: str, text: str) -> object:
    return client.post(
        "/api/text-kb",
        json={"capture_id": capture_id, "text": text},
        headers=event,
    )


def test_mid_uow_failure_rolls_back_everything_and_retry_succeeds(user_factory):
    container = get_container()
    user = user_factory(client)
    capture_id = str(uuid.uuid4())
    text = "I met Rhea at the market yesterday."

    # Fail INSIDE the unit of work: every relationship write blows up after
    # the capture and knowledge item were saved.
    real_save = container.rel_repo.save

    class Boom(Exception):
        pass

    calls = {"n": 0}

    def failing_save(rel, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Boom("injected relationship failure")
        return real_save(rel, *args, **kwargs)

    container.rel_repo.save = failing_save
    try:
        first = _auth(user.headers, capture_id, text)
    finally:
        container.rel_repo.save = real_save

    assert first.status_code == 500, first.text
    assert first.json()["detail"]["class"] == "server_error", first.text
    assert calls["n"] == 1

    # NOTHING persisted: the UoW rolled back capture + item + entities.
    assert container.capture_repo.get_by_id(capture_id, user_id=None) is None
    assert container.knowledge_repo.get_by_capture_id(capture_id) is None
    names = {
        e.normalized_name
        for e in container.entity_repo.get_all(user_id=user.id)
        if not e.is_self
    }
    assert "rhea" not in names, f"partial ingest leaked: {sorted(names)}"
    # No support rows survived either.
    assert container.support_repo.list_for_record(user.id, capture_id) == []

    # No transaction leaked open: a fresh write on the same pool succeeds.
    container.tombstone_repo.add(user.id, "entity", "rollback-probe")
    assert container.tombstone_repo.is_tombstoned(user.id, "entity", "rollback-probe")

    # A retry with the SAME capture_id succeeds end to end (no 409, no
    # leftovers from the failed attempt).
    second = _auth(user.headers, capture_id, text)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["capture_id"] == capture_id

    graph = client.get("/api/graph", headers=user.headers).json()
    titles = {n["title"] for n in graph["nodes"]}
    assert "Rhea" in titles
    # Exactly one Rhea despite the failed first attempt.
    assert len([t for t in titles if t == "Rhea"]) == 1
    item = container.knowledge_repo.get_by_capture_id(capture_id)
    assert item is not None
