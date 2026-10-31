"""Groq HTTP client behavior without any real network call."""

import io
import json
import urllib.error

import pytest

from server.app.adapters.outbound.llm.budget import TokenBudget
from server.app.adapters.outbound.llm.client import GroqChatClient
from server.app.adapters.outbound.llm.validation import TEST_SCHEMA, TEST_SCHEMA_NAME
from server.app.domain.errors import (
    ProviderNetworkError,
    ProviderOutageError,
    ProviderSchemaError,
    QuotaExhaustedError,
)


@pytest.fixture(autouse=True)
def _allow_transport_in_this_unit_file(monkeypatch):
    """The transport is always monkeypatched here; no socket is ever opened."""
    monkeypatch.setenv("ECHO_ALLOW_REAL_LLM", "1")


class _Usage:
    def __init__(self):
        self.rows = []

    def record(self, **kwargs):
        self.rows.append(kwargs)

    def usage_since(self, since_iso, user_id=None):
        return {"calls": 0, "total_tokens": 0}

    def last_calls(self, limit=20):
        return []


def _client(**kwargs):
    usage = _Usage()
    budget = TokenBudget(
        usage,
        provider="groq",
        model="test-model",
        rpm=30,
        rpd=1000,
        tpm=8000,
        tpd=200000,
    )
    return GroqChatClient(
        "test-key-not-real",
        "test-model",
        timeout_seconds=1,
        max_retries=3,
        max_retry_wait_seconds=0,
        budget=budget,
        **kwargs,
    )


def _call(client):
    return client.complete_json(
        operation="test",
        system="system",
        user="user",
        schema=TEST_SCHEMA,
        schema_name=TEST_SCHEMA_NAME,
        max_tokens=16,
    )


def test_post_sends_an_explicit_product_user_agent(monkeypatch):
    """Cloudflare rejects the default Python-urllib signature with HTTP 403."""
    client = _client()
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        captured["user_agent"] = request.get_header("User-agent")
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert client._post({"model": "test"}) == {"ok": True}
    assert captured["user_agent"].startswith("Echo/")


def test_valid_json_response_reports_usage(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_post",
        lambda payload: {
            "choices": [
                {
                    "message": {"content": json.dumps({"ok": True})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        },
    )
    response = _call(client)
    assert response.content == {"ok": True}
    assert response.total_tokens == 14
    assert response.attempts == 1


def test_http_429_honors_retry_after(monkeypatch):
    client = _client()
    calls = []

    def boom(payload):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://api.groq.com",
            429,
            "Too Many Requests",
            {"Retry-After": "17"},
            io.BytesIO(b'{"error":"rate"}'),
        )

    monkeypatch.setattr(client, "_post", boom)
    with pytest.raises(QuotaExhaustedError) as excinfo:
        _call(client)
    assert excinfo.value.retry_after == 17
    assert len(calls) == 1, "a long Retry-After is surfaced, not slept through"


def test_429_with_short_retry_after_retries_at_most_three_times(monkeypatch):
    client = _client()
    calls = []

    def boom(payload):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://api.groq.com",
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            io.BytesIO(b"{}"),
        )

    monkeypatch.setattr(client, "_post", boom)
    with pytest.raises(QuotaExhaustedError):
        _call(client)
    assert len(calls) == 3, "the client must cap automatic retries at three"


def test_outage_is_retried_then_typed(monkeypatch):
    client = _client()
    calls = []

    def boom(payload):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://api.groq.com", 503, "Unavailable", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(client, "_post", boom)
    with pytest.raises(ProviderOutageError):
        _call(client)
    assert len(calls) == 3


def test_timeout_is_retried_then_typed(monkeypatch):
    client = _client()
    calls = []

    def boom(payload):
        calls.append(1)
        raise TimeoutError("slow")

    monkeypatch.setattr(client, "_post", boom)
    with pytest.raises(ProviderNetworkError):
        _call(client)
    assert len(calls) == 3


def test_400_is_a_schema_error_without_transport_retry(monkeypatch):
    client = _client()
    calls = []

    def boom(payload):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://api.groq.com", 400, "Bad Request", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(client, "_post", boom)
    with pytest.raises(ProviderSchemaError):
        _call(client)
    assert len(calls) == 1


def test_test_environment_refuses_real_calls(monkeypatch):
    monkeypatch.setenv("ECHO_ENV", "test")
    monkeypatch.delenv("ECHO_ALLOW_REAL_LLM", raising=False)
    client = _client()
    called = []
    monkeypatch.setattr(client, "_post", lambda payload: called.append(1))
    with pytest.raises(Exception) as excinfo:
        _call(client)
    assert "test environment" in str(excinfo.value).lower()
    assert called == []
