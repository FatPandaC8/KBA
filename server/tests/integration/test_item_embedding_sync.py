"""Regression: the capture pipeline must index the knowledge item itself.

Without item-level embeddings, /api/knowledge/semantic-search stays empty for
everything captured since deploy until an admin triggers the backfill endpoint
(found by the Playwright E2E suite, 2026-10-31).
"""

import uuid

from fastapi.testclient import TestClient

from server.app.main import app

from .m3_support import FakeTranscriber, container, ingest

client = TestClient(app)


def _embeddings(container_):
    repo = container_.embedding_repo
    return {item_id for item_id, _ in repo.get_all()}


def test_pipeline_indexes_the_knowledge_item_immediately(user_factory, monkeypatch):
    user = user_factory(client)
    capture_id = ingest(client, user, "Echo depends on FastAPI.", monkeypatch)

    item_id = container().knowledge_repo.get_by_capture_id(capture_id, user_id=user.id).id
    assert item_id in _embeddings(container()), (
        "capture pipeline must write the knowledge-item embedding, "
        "not only entity/relationship embeddings"
    )
