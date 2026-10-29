"""M3 Ask AI tests: grounded answers, citations, refusals and provider failures (QA)."""

from fastapi.testclient import TestClient

from server.app.domain.errors import ProviderError, ProviderNetworkError, QuotaExhaustedError
from server.app.main import app

from .m3_support import container, ingest

client = TestClient(app)


class FailingAnswerer:
    def __init__(self, exc):
        self.exc = exc

    def answer(self, question, evidence, contradictions):
        raise self.exc


def test_ask_refuses_instead_of_inventing_when_graph_is_empty(user_factory):
    user = user_factory(client)
    response = client.post(
        "/api/ask",
        json={"question": "What did I decide about the launch?"},
        headers=user.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["refusal_reason"] == "insufficient_evidence"
    assert body["message"]["status"] == "ready"
    assert body["message"]["citations"] == []
    assert "not enough evidence" in body["message"]["content"].lower()


def test_ask_refuses_an_unrelated_question_when_notes_exist(user_factory, monkeypatch):
    """A non-empty graph must not become an excuse to answer anything (QA-02)."""
    user = user_factory(client)
    ingest(client, user, "I met Alice about the Echo project. Echo depends on FastAPI.", monkeypatch)

    response = client.post(
        "/api/ask",
        json={"question": "What is my blood type?"},
        headers=user.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["refusal_reason"] == "insufficient_evidence"
    assert body["message"]["citations"] == []
    assert "not enough evidence" in body["message"]["content"].lower()


def test_grounded_answer_carries_display_only_citations(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI.", monkeypatch)

    response = client.post(
        "/api/ask", json={"question": "What depends on FastAPI?"}, headers=user.headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["message"]["status"] == "ready"
    assert body["facts"]
    assert body["message"]["citations"]

    for citation in body["message"]["citations"]:
        assert set(citation) == {"id", "kind", "target_id", "name", "deleted"}
        assert "url" not in citation
        assert citation["deleted"] is False

    conversation = client.get(
        f"/api/conversations/{body['conversation_id']}", headers=user.headers
    ).json()
    roles = [message["role"] for message in conversation["messages"]]
    assert roles == ["user", "assistant"]


def test_conversation_continues_with_the_same_thread(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI.", monkeypatch)

    first = client.post("/api/ask", json={"question": "What depends on FastAPI?"}, headers=user.headers).json()
    conversation_id = first["conversation_id"]
    second = client.post(
        "/api/ask",
        json={"question": "What do you know about Echo?", "conversation_id": conversation_id},
        headers=user.headers,
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id

    conversation = client.get(f"/api/conversations/{conversation_id}", headers=user.headers).json()
    assert [m["role"] for m in conversation["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]

    summaries = client.get("/api/conversations", headers=user.headers).json()
    assert [s["id"] for s in summaries] == [conversation_id]


def test_quota_network_and_provider_failures_are_distinct_and_retryable(user_factory, monkeypatch):
    user = user_factory(client)
    expected = [
        (QuotaExhaustedError("free quota exhausted"), "quota_exhausted", "quota"),
        (ProviderNetworkError("offline"), "network_error", "connection"),
        (ProviderError("provider crashed"), "provider_failure", "failed"),
    ]
    asked = set()
    for exc, error_class, message_hint in expected:
        monkeypatch.setattr(container().ask_uc, "answerer", FailingAnswerer(exc))
        response = client.post(
            "/api/ask", json={"question": "What depends on FastAPI?"}, headers=user.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["refused"] is True
        assert body["message"]["status"] == "failed"
        assert body["message"]["error_class"] == error_class
        assert message_hint in body["refusal_reason"].lower()
        asked.add(body["refusal_reason"])

    assert len(asked) == 3, "each failure class must show a different message"


def test_deleted_entity_citation_is_marked_but_keeps_its_name(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI.", monkeypatch)
    answer = client.post(
        "/api/ask", json={"question": "What depends on FastAPI?"}, headers=user.headers
    ).json()

    entity_citation = next(
        citation for citation in answer["message"]["citations"] if citation["kind"] == "entity"
    )
    original_name = entity_citation["name"]
    assert client.delete(
        f"/api/graph/entities/{entity_citation['target_id']}", headers=user.headers
    ).status_code == 200

    conversation = client.get(
        f"/api/conversations/{answer['conversation_id']}", headers=user.headers
    ).json()
    assistant = next(m for m in conversation["messages"] if m["role"] == "assistant")
    citation = next(
        c for c in assistant["citations"] if c["id"] == entity_citation["id"]
    )
    assert citation["deleted"] is True
    assert citation["name"] == original_name


def test_deleting_a_record_removes_only_answers_that_cited_it(user_factory, monkeypatch):
    user = user_factory(client)
    capture_id = ingest(client, user, "Echo depends on FastAPI.", monkeypatch)
    answer = client.post(
        "/api/ask", json={"question": "What depends on FastAPI?"}, headers=user.headers
    ).json()

    assert client.delete(f"/api/captures/{capture_id}", headers=user.headers).status_code == 200

    conversation = client.get(
        f"/api/conversations/{answer['conversation_id']}", headers=user.headers
    )
    assert conversation.status_code == 200, "the conversation itself is kept"
    roles = [message["role"] for message in conversation.json()["messages"]]
    assert "assistant" not in roles
    assert roles == ["user"]


def test_conversation_deletion_removes_messages_and_citations(user_factory, monkeypatch):
    user = user_factory(client)
    ingest(client, user, "Echo depends on FastAPI.", monkeypatch)
    answer = client.post(
        "/api/ask", json={"question": "What depends on FastAPI?"}, headers=user.headers
    ).json()
    conversation_id = answer["conversation_id"]
    message_id = answer["message"]["id"]

    assert client.delete(f"/api/conversations/{conversation_id}", headers=user.headers).status_code == 200
    assert client.get(f"/api/conversations/{conversation_id}", headers=user.headers).status_code == 404
    assert container().message_repo.get_by_id(message_id, user.id) is None
    assert container().citation_repo.list_for_message(message_id, user.id) == []


def test_conversations_and_ask_are_owner_scoped(user_factory, monkeypatch):
    alice = user_factory(client)
    bob = user_factory(client)
    ingest(client, alice, "Echo depends on FastAPI.", monkeypatch)
    answer = client.post(
        "/api/ask", json={"question": "What depends on FastAPI?"}, headers=alice.headers
    ).json()

    assert client.get("/api/conversations", headers=bob.headers).json() == []
    assert (
        client.get(f"/api/conversations/{answer['conversation_id']}", headers=bob.headers).status_code
        == 404
    )
    assert (
        client.delete(f"/api/conversations/{answer['conversation_id']}", headers=bob.headers).status_code
        == 404
    )
    hijack = client.post(
        "/api/ask",
        json={"question": "Read Alice's notes", "conversation_id": answer["conversation_id"]},
        headers=bob.headers,
    )
    assert hijack.status_code == 404
    assert "Alice" not in hijack.text
