"""Shared fixtures for the M2 authentication/ownership test suite.

The application container is a process-wide singleton, so every test uses a
unique email address and the in-process rate limiter is cleared between tests.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

import pytest

from server.app.security import rate_limiter

PASSWORD = "EchoTest1234"


@dataclass
class TestUser:
    id: str
    email: str
    password: str
    token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def user_factory():
    """Create an account through the public HTTP flow.

    ``verified=False`` leaves the account usable for login but blocked from
    creating or reading records. ``consent=False`` leaves consent ungranted.
    """

    def create(
        client,
        *,
        verified: bool = True,
        consent: bool = True,
        email: Optional[str] = None,
        password: str = PASSWORD,
    ) -> TestUser:
        email = email or f"user-{uuid.uuid4().hex}@example.com"
        signup = client.post(
            "/api/auth/signup", json={"email": email, "password": password}
        )
        assert signup.status_code == 200, signup.text
        if verified:
            token = signup.json()["dev_verification_token"]
            assert token, "test environment must expose the verification token"
            verify = client.post("/api/auth/verify-email", json={"token": token})
            assert verify.status_code == 200, verify.text

        login = client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert login.status_code == 200, login.text
        body = login.json()
        user = TestUser(
            id=body["user"]["id"],
            email=email,
            password=password,
            token=body["token"],
        )
        if consent:
            granted = client.post(
                "/api/consent", json={"granted": True}, headers=user.headers
            )
            assert granted.status_code == 200, granted.text
            assert granted.json()["granted"] is True
        return user

    return create
