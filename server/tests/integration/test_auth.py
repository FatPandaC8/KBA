"""M2 authentication, consent and account-lifecycle tests (AUTH-01..07, GATE-01/02)."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from server.app.api.dependencies import get_container
from server.app.domain.entities import CaptureEntity, KnowledgeItemEntity
from server.app.main import app

client = TestClient(app)


def _container():
    return get_container()


def test_signup_verify_login_and_me(user_factory):
    email = f"signup-{uuid.uuid4().hex}@example.com"
    signup = client.post(
        "/api/auth/signup", json={"email": email, "password": "EchoTest1234"}
    )
    assert signup.status_code == 200, signup.text
    token = signup.json()["dev_verification_token"]
    assert token

    verified = client.post("/api/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["verified"] is True

    login = client.post(
        "/api/auth/login", json={"email": email, "password": "EchoTest1234"}
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["user"]["email"] == email
    assert body["user"]["email_verified"] is True

    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_duplicate_signup_is_generic_and_creates_no_second_account():
    email = f"duplicate-{uuid.uuid4().hex}@example.com"
    first = client.post(
        "/api/auth/signup", json={"email": email, "password": "EchoTest1234"}
    )
    assert first.status_code == 200
    count_before = _container().user_repo.count()

    second = client.post(
        "/api/auth/signup", json={"email": email, "password": "EchoTest1234"}
    )
    assert second.status_code == 200
    assert second.json()["email"] == email
    assert second.json()["dev_verification_token"] is None
    assert _container().user_repo.count() == count_before


def test_signup_validation_rejects_bad_email_and_weak_password():
    assert client.post(
        "/api/auth/signup", json={"email": "not-an-email", "password": "EchoTest1234"}
    ).status_code == 400
    assert client.post(
        "/api/auth/signup",
        json={"email": f"weak-{uuid.uuid4().hex}@example.com", "password": "short"},
    ).status_code == 400


def test_failed_login_is_generic_for_unknown_email_and_wrong_password(user_factory):
    user = user_factory(client, consent=False)
    unknown = client.post(
        "/api/auth/login",
        json={"email": f"absent-{uuid.uuid4().hex}@example.com", "password": "EchoTest1234"},
    )
    wrong = client.post(
        "/api/auth/login", json={"email": user.email, "password": "WrongPass1234"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]
    assert "incorrect" in unknown.json()["detail"].lower()


def test_verification_token_is_single_use():
    email = f"verify-once-{uuid.uuid4().hex}@example.com"
    signup = client.post(
        "/api/auth/signup", json={"email": email, "password": "EchoTest1234"}
    )
    token = signup.json()["dev_verification_token"]
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 401


def test_request_verification_is_generic_and_issues_new_token():
    unknown = client.post(
        "/api/auth/request-verification",
        json={"email": f"absent-{uuid.uuid4().hex}@example.com"},
    )
    assert unknown.status_code == 200
    assert unknown.json()["dev_verification_token"] is None

    email = f"resend-{uuid.uuid4().hex}@example.com"
    client.post("/api/auth/signup", json={"email": email, "password": "EchoTest1234"})
    resend = client.post("/api/auth/request-verification", json={"email": email})
    assert resend.status_code == 200
    new_token = resend.json()["dev_verification_token"]
    assert new_token
    assert client.post("/api/auth/verify-email", json={"token": new_token}).status_code == 200


def test_login_rate_limit_returns_429_with_retry_after():
    email = f"limit-{uuid.uuid4().hex}@example.com"
    responses = [
        client.post("/api/auth/login", json={"email": email, "password": "WrongPass1234"})
        for _ in range(21)
    ]
    assert [r.status_code for r in responses[:20]] == [401] * 20
    assert responses[20].status_code == 429
    assert int(responses[20].headers["Retry-After"]) >= 1


def test_logout_revokes_the_session(user_factory):
    user = user_factory(client)
    assert client.get("/api/auth/me", headers=user.headers).status_code == 200
    assert client.post("/api/auth/logout", headers=user.headers).status_code == 200
    assert client.get("/api/auth/me", headers=user.headers).status_code == 401
    assert client.get("/api/knowledge", headers=user.headers).status_code == 401


def test_password_reset_revokes_sessions_and_rejects_token_reuse(user_factory):
    user = user_factory(client)
    reset = client.post(
        "/api/auth/request-password-reset", json={"email": user.email}
    )
    assert reset.status_code == 200
    reset_token = reset.json()["dev_reset_token"]
    assert reset_token
    assert client.get("/api/auth/me", headers=user.headers).status_code == 200

    changed = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "EchoReset1234"},
    )
    assert changed.status_code == 200, changed.text

    assert client.get("/api/auth/me", headers=user.headers).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": user.password}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": "EchoReset1234"}
    ).status_code == 200

    # The reset token is single use and cannot revoke the new session again.
    reused = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "EchoReset5678"},
    )
    assert reused.status_code == 401


def test_password_reset_request_for_unknown_email_is_generic():
    response = client.post(
        "/api/auth/request-password-reset",
        json={"email": f"absent-{uuid.uuid4().hex}@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["dev_reset_token"] is None


def test_google_sign_in_fails_closed_when_not_configured():
    response = client.post("/api/auth/google", json={"id_token": "forged-token"})
    assert response.status_code == 503


def test_consent_withdrawal_blocks_the_app_without_deleting_existing_data(user_factory):
    user = user_factory(client)
    container = _container()
    capture = CaptureEntity(
        id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        audio_path="",
        user_id=user.id,
        duration_ms=1000,
        status="ready",
    )
    container.capture_repo.save(capture)

    status = client.get("/api/consent", headers=user.headers)
    assert status.status_code == 200
    assert status.json()["granted"] is True
    assert status.json()["providers"]

    withdrawn = client.post(
        "/api/consent", json={"granted": False}, headers=user.headers
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["granted"] is False
    assert client.get("/api/knowledge", headers=user.headers).status_code == 403
    # GATE-02: withdrawal blocks use; it does not silently delete data.
    assert container.capture_repo.get_by_id(capture.id, user_id=user.id) is not None

    regranted = client.post("/api/consent", json={"granted": True}, headers=user.headers)
    assert regranted.json()["granted"] is True
    assert client.get("/api/knowledge", headers=user.headers).status_code == 200


def test_changing_the_provider_list_forces_a_new_consent(user_factory, monkeypatch):
    user = user_factory(client)
    settings = _container().settings
    assert client.get("/api/consent", headers=user.headers).json()["granted"] is True

    changed = [
        {
            "id": "stt_new_free_provider",
            "name": "New free STT provider",
            "receives": ["audio recording"],
            "trains_on_data": True,
        }
    ]
    monkeypatch.setattr(settings, "ai_providers_json", json.dumps(changed))

    status = client.get("/api/consent", headers=user.headers)
    assert status.status_code == 200
    assert status.json()["granted"] is False
    assert status.json()["providers"] == changed
    assert client.get("/api/knowledge", headers=user.headers).status_code == 403

    regranted = client.post("/api/consent", json={"granted": True}, headers=user.headers)
    assert regranted.json()["granted"] is True
    assert client.get("/api/knowledge", headers=user.headers).status_code == 200


def test_account_deletion_requires_confirmation_and_auth(user_factory):
    user = user_factory(client)
    assert client.delete("/api/account").status_code == 401
    assert client.delete("/api/account?confirm=DELETE").status_code == 401
    assert client.delete("/api/account", headers=user.headers).status_code == 400
    assert client.get("/api/auth/me", headers=user.headers).status_code == 200


def test_account_deletion_removes_all_data_and_revokes_access(user_factory):
    user = user_factory(client)
    container = _container()
    capture_id = str(uuid.uuid4())
    container.capture_repo.save(
        CaptureEntity(
            id=capture_id,
            idempotency_key=capture_id,
            audio_path="",
            user_id=user.id,
            duration_ms=1000,
            status="ready",
        )
    )
    item = KnowledgeItemEntity.create(
        capture_id=capture_id,
        title="Delete with account",
        core_idea="idea",
        user_id=user.id,
        transcript="private",
    )
    container.knowledge_repo.save(item)
    container.embedding_repo.save(item.id, b"\x00" * 16, user_id=user.id)

    response = client.delete("/api/account?confirm=DELETE", headers=user.headers)
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    assert response.json()["sessions_revoked"] >= 1

    assert client.get("/api/auth/me", headers=user.headers).status_code == 401
    assert client.get("/api/knowledge", headers=user.headers).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": user.password}
    ).status_code == 401

    assert container.user_repo.get_by_id(user.id) is None
    assert container.capture_repo.count(user_id=user.id) == 0
    assert container.knowledge_repo.count(user_id=user.id) == 0
    assert container.embedding_repo.count(user_id=user.id) == 0
