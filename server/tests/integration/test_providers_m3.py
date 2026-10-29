"""M3 provider transparency: only free, self-hosted components are offered (NET-01, NET-03)."""

from fastapi.testclient import TestClient

from server.app.main import app

client = TestClient(app)


def test_providers_endpoint_lists_only_free_local_components(user_factory):
    user = user_factory(client)
    response = client.get("/api/providers", headers=user.headers)
    assert response.status_code == 200
    providers = response.json()
    assert {p["kind"] for p in providers} == {
        "speech_to_text",
        "embeddings",
        "extraction",
        "question_answering",
    }
    serialized = str(providers).lower()
    for paid in ("openai", "anthropic", "deepgram", "assemblyai", "google_speech", "azure"):
        assert paid not in serialized
    assert all(p["trains_on_data"] is False for p in providers)
    assert all(isinstance(p["receives"], list) and p["receives"] for p in providers)


def test_providers_require_authentication_and_consent(user_factory):
    user = user_factory(client)
    assert client.get("/api/providers").status_code == 401

    unconsented = user_factory(client, consent=False)
    assert client.get("/api/providers", headers=unconsented.headers).status_code == 403
    assert client.get("/api/providers", headers=user.headers).status_code == 200
