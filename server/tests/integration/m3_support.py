"""Shared helpers for M3 integration tests (pipeline split, S1/S2).

Ingest now runs synchronously: POST /api/text-kb creates the capture, the
knowledge item and the graph in ONE unit of work. There is no worker, no job
row and no polling — `ingest_text()` posts text directly.
"""

import uuid
from typing import Optional

from server.app.api.dependencies import get_container


def container():
    return get_container()


def new_capture_id() -> str:
    return str(uuid.uuid4())


def ingest_text(client, user, text: str, capture_id: Optional[str] = None) -> str:
    """POST /api/text-kb with a fresh capture_id; assert the contract and
    return the capture_id. Idempotent retries re-send the SAME id."""
    capture_id = capture_id or new_capture_id()
    response = client.post(
        "/api/text-kb",
        headers=user.headers,
        json={"capture_id": capture_id, "text": text},
    )
    assert response.status_code == 200, response.text
    assert response.json()["capture_id"] == capture_id
    return capture_id
