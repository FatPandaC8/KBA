"""Shared fixtures for per-port contract tests (ADR Part 3).

The suite runs against the REAL Postgres adapter only — the same functions any
future adapter must satisfy. No SQLite and no database mocks.
"""

import pytest

from server.app.api.dependencies import get_container
from server.app.domain.entities import (
    CaptureEntity,
    ExtractedEntity,
    KnowledgeItemEntity,
    UserEntity,
)


@pytest.fixture
def container_():
    return get_container()


@pytest.fixture
def user(container_) -> UserEntity:
    """A verified user created through the real auth flow."""
    import uuid

    from fastapi.testclient import TestClient

    from server.app.main import app

    client = TestClient(app)
    email = f"contract-{uuid.uuid4().hex}@example.com"
    signup = client.post("/api/auth/signup", json={"email": email, "password": "EchoTest1234"})
    assert signup.status_code == 200, signup.text
    token = signup.json()["dev_verification_token"]
    verify = client.post("/api/auth/verify-email", json={"token": token})
    assert verify.status_code == 200, verify.text
    login = client.post("/api/auth/login", json={"email": email, "password": "EchoTest1234"})
    user = container_.user_repo.get_by_email(email)
    assert user is not None
    return user


