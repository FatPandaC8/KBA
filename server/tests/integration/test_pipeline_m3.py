"""M3 pipeline tests: real job state, leases, retries, duplicates, deletion (PRC/KG/DEL)."""

import json
import time
import uuid

from fastapi.testclient import TestClient

from server.app.domain.errors import (
    InvalidInputAudioError,
    ProviderNetworkError,
    QuotaExhaustedError,
)
from server.app.main import app

from .m3_support import FakeTranscriber, container, ingest, process, upload

client = TestClient(app)


def _job(capture_id, user_id):
    return container().job_repo.get_by_capture_id(capture_id, user_id=user_id)


def _set_job(capture_id, user_id, *, status, stage, outputs):
    import psycopg

    from server.tests.postgres_testinfra import worker_database_url

    with psycopg.connect(worker_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE processing_jobs SET status = %s, stage = %s, "
                "stage_outputs = %s::jsonb, "
                "lease_owner = '', lease_expires_at = '2000-01-01 00:00:00+00', attempt = 0 "
                "WHERE capture_id = %s AND user_id = %s",
                (status, stage, json.dumps(outputs), capture_id, user_id),
            )


def _advance_retry_schedule(capture_id, user_id):
    """D7 schedules automatic retries with backoff; tests advance the schedule
    to the past instead of sleeping (sleeps are forbidden in this suite)."""
    import psycopg

    from server.tests.postgres_testinfra import worker_database_url

    with psycopg.connect(worker_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE processing_jobs SET next_attempt_at = '2000-01-01 00:00:00+00' "
                "WHERE capture_id = %s AND user_id = %s",
                (capture_id, user_id),
            )


def test_upload_queues_a_real_job_and_status_tracks_each_stage(user_factory):
    user = user_factory(client)
    capture_id = upload(client, user)

    queued = client.get(f"/api/recordings/{capture_id}/status", headers=user.headers)
    assert queued.status_code == 200
    body = queued.json()
    assert body["status"] == "queued"
    assert body["stage"] == "upload"
    assert body["attempt"] == 0

    use_case = container().process_capture_uc
    original = use_case.transcriber
    use_case.transcriber = FakeTranscriber()
    try:
        job = process(capture_id)
    finally:
        use_case.transcriber = original
    assert job.stage == "completed"
    assert job.status == "ready"

    ready = client.get(f"/api/recordings/{capture_id}/status", headers=user.headers).json()
    assert ready["stage"] == "completed"
    assert ready["status"] == "ready"

    recordings = client.get("/api/recordings", headers=user.headers).json()
    assert [r["capture_id"] for r in recordings] == [capture_id]
    assert recordings[0]["knowledge_item_id"]


def test_writing_to_a_ready_job_is_idempotent_and_not_duplicated(user_factory):
    user = user_factory(client)
    capture_id = ingest(client, user, "Echo depends on FastAPI.")

    # Reopening the app means repeated reads, never a new job.
    for _ in range(5):
        assert client.get(f"/api/recordings/{capture_id}/status", headers=user.headers).status_code == 200
        assert client.get("/api/recordings", headers=user.headers).status_code == 200
        assert client.get("/api/graph", headers=user.headers).status_code == 200

    jobs = container().job_repo.get_recent_jobs(limit=200, user_id=user.id)
    assert len(jobs) == 1
    assert jobs[0].capture_id == capture_id


def test_resume_reuses_completed_stage_outputs_without_reprocessing(user_factory, monkeypatch):
    user = user_factory(client)
    transcriber = FakeTranscriber("Echo depends on FastAPI.")
    monkeypatch.setattr(container().process_capture_uc, "transcriber", transcriber)

    capture_id = upload(client, user)
    first = process(capture_id)
    assert first.status == "ready"
    assert transcriber.calls == 1

    before = len(container().graph_query_uc.get_graph(user.id).nodes)
    job = _job(capture_id, user.id)
    stage_outputs = job.stage_outputs
    if isinstance(stage_outputs, str):
        outputs = json.loads(stage_outputs)
    else:
        outputs = stage_outputs
    outputs.pop("extraction", None)
    outputs.pop("saved", None)
    # Simulate a backend crash after transcription: work resumes at extraction.
    _set_job(capture_id, user.id, status="queued", stage="extract", outputs=outputs)
    print(f"[DEBUG test] Job status after _set_job: {_job(capture_id, user.id).status}")
    print(f"[DEBUG test] Job stage after _set_job: {_job(capture_id, user.id).stage}")
    print(f"[DEBUG test] Job lease_expires_at after _set_job: {_job(capture_id, user.id).lease_expires_at}")
    print(f"[DEBUG test] Job lease_owner after _set_job: {_job(capture_id, user.id).lease_owner}")
    print(f"[DEBUG test] Job attempt after _set_job: {_job(capture_id, user.id).attempt}")
    resumed = process(capture_id, worker_id="restarted-worker")
    print(f"[DEBUG test] Resumed job: {resumed}")
    if resumed:
        print(f"[DEBUG test] Resumed job status: {resumed.status}")
        print(f"[DEBUG test] Resumed job stage: {resumed.stage}")
    assert resumed.status == "ready"
    assert transcriber.calls == 1, "transcription must not run twice"
    assert len(container().graph_query_uc.get_graph(user.id).nodes) == before


def test_network_failure_is_retried_then_completes(user_factory, monkeypatch):
    user = user_factory(client)
    transcriber = FakeTranscriber(
        "Echo depends on FastAPI.",
        errors=[ProviderNetworkError("temporary network failure"), ProviderNetworkError("still offline")],
    )
    monkeypatch.setattr(container().process_capture_uc, "transcriber", transcriber)

    capture_id = upload(client, user)
    first = process(capture_id)
    assert first.status == "queued"
    assert first.attempt == 1
    assert first.error_class == "network_error"

    # D7 schedules the automatic retry ~30s out; advance the schedule instead
    # of sleeping in tests.
    _advance_retry_schedule(capture_id, user.id)

    second = process(capture_id)
    assert second.status == "queued"
    assert second.attempt == 2

    # The second failure schedules a 120s retry (D7); advance it again instead
    # of sleeping.
    _advance_retry_schedule(capture_id, user.id)

    third = process(capture_id)
    assert third.status == "ready"
    assert third.stage == "completed"
    assert transcriber.calls == 3


def test_quota_exhaustion_is_reported_once_and_allows_manual_retry(user_factory, monkeypatch):
    user = user_factory(client)
    monkeypatch.setattr(
        container().process_capture_uc,
        "transcriber",
        FakeTranscriber(errors=[QuotaExhaustedError("free quota exhausted")]),
    )
    capture_id = upload(client, user)
    failed = process(capture_id)

    # Quota is not automatically retried, but the user may retry manually.
    assert failed.status == "failed"
    assert failed.error_class == "quota_exhausted"
    retryable = client.get("/api/recordings", headers=user.headers).json()[0]
    assert retryable["retryable"] is True
    assert "quota" in (retryable["error_message"] or "").lower()

    monkeypatch.setattr(
        container().process_capture_uc, "transcriber", FakeTranscriber("Echo is local.")
    )
    retry = client.post(f"/api/recordings/{capture_id}/retry", headers=user.headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "queued"

    assert process(capture_id).status == "ready"


def test_invalid_audio_fails_permanently_and_never_loops(user_factory, monkeypatch):
    user = user_factory(client)
    monkeypatch.setattr(
        container().process_capture_uc,
        "transcriber",
        FakeTranscriber(errors=[InvalidInputAudioError("Recording is silent.")]),
    )
    capture_id = upload(client, user)
    failed = process(capture_id)

    assert failed.status == "failed"
    assert failed.error_class == "invalid_input"
    assert failed.attempt == 1

    # No automatic retry: a second worker pass finds nothing to claim.
    assert process(capture_id) is None


def test_duplicate_entities_auto_link_above_090_and_flag_between_075_and_090(user_factory):
    user = user_factory(client)
    # First capture WITH a relationship so entities are not orphans.
    # "Echo project depends on FastAPI" + "Acme Rocket supports FastAPI" → both have relationships
    c1 = upload(client, user)
    container_ = container()
    container_.process_capture_uc.transcriber = FakeTranscriber("the Echo project depends on FastAPI. Acme Rocket supports FastAPI.")
    process(c1)

    # Second capture: similar entities should auto-link (>=0.90) or be flagged (0.75-0.90)
    c2 = upload(client, user)
    container_ = container()
    container_.process_capture_uc.transcriber = FakeTranscriber("the Echo project matters. Acme Rocket Labs is promising.")
    process(c2)

    entities = container().entity_repo.get_all(user_id=user.id)
    echo_projects = [e for e in entities if e.normalized_name == "echo project"]
    assert len(echo_projects) == 1, ">= 0.90 must auto-link instead of duplicating"

    flagged = container().duplicate_repo.list_flagged(user.id)
    assert flagged, "0.75-0.90 must be recorded for the user to decide"
    scores = [entry["score"] for entry in flagged]
    assert all(0.75 <= score < 0.90 for score in scores)


def test_contradicting_edges_are_both_kept_and_marked(user_factory, monkeypatch):
    user = user_factory(client)
    monkeypatch.setattr(
        container().process_capture_uc, "transcriber", FakeTranscriber("Echo supports FastAPI.")
    )
    process(upload(client, user))
    monkeypatch.setattr(
        container().process_capture_uc, "transcriber", FakeTranscriber("Echo contradicts FastAPI.")
    )
    process(upload(client, user))

    graph = client.get("/api/graph", headers=user.headers).json()
    edges = graph["edges"]
    types = {edge["type"] for edge in edges}
    assert "Supports" in types and "Contradicts" in types
    assert any(edge["certainty"] == "conflicting" for edge in edges)


def test_deleting_one_record_keeps_entities_still_supported_by_another(user_factory, monkeypatch):
    user = user_factory(client)
    first = ingest(client, user, "Echo depends on FastAPI.", monkeypatch)
    second = ingest(client, user, "Echo supports Alice.", monkeypatch)

    names = {n.title for n in container().graph_query_uc.get_graph(user.id).nodes}
    assert {"Echo", "FastAPI", "Alice"} <= names

    assert client.delete(f"/api/captures/{first}", headers=user.headers).status_code == 200
    names = {n.title for n in container().graph_query_uc.get_graph(user.id).nodes}
    assert "Echo" in names, "shared entity must survive"
    assert "FastAPI" not in names

    assert client.delete(f"/api/captures/{second}", headers=user.headers).status_code == 200
    # After all captures deleted, only the self entity remains
    nodes = container().graph_query_uc.get_graph(user.id).nodes
    assert len(nodes) == 1
    assert nodes[0].title == "Me"
    assert nodes[0].kind == "self"


def test_client_responses_never_expose_transcripts_or_raw_audio(user_factory, monkeypatch):
    user = user_factory(client)
    transcript = "Echo depends on FastAPI."
    capture_id = ingest(client, user, transcript, monkeypatch)

    knowledge = client.get("/api/knowledge", headers=user.headers).json()
    recordings = client.get("/api/recordings", headers=user.headers).json()
    graph = client.get("/api/graph", headers=user.headers).json()
    entity_id = graph["nodes"][0]["id"]
    detail = client.get(f"/api/graph/entities/{entity_id}", headers=user.headers).json()

    for payload in (knowledge, recordings, graph, detail):
        assert "transcript" not in json.dumps(payload)

    audio = client.get(f"/api/recordings/{capture_id}/audio", headers=user.headers)
    assert audio.status_code == 200
    assert audio.content == b"\x00" * 512


def test_worker_processes_a_queued_job_without_a_client_trigger(user_factory, monkeypatch):
    """D8: the worker loop lives in its own process; here the same runner loop
    is exercised directly (`python -m app.worker` runs this class)."""
    from server.app.worker import WorkerRunner

    user = user_factory(client)
    monkeypatch.setattr(
        container().process_capture_uc, "transcriber", FakeTranscriber("Echo is local.")
    )
    runner = WorkerRunner(container(), poll_seconds=0.05)
    assert not runner.stopping
    capture_id = upload(client, user)
    deadline = time.time() + 15

    class OneShotLoop:
        calls = 0

        def run_once(self, original=runner.run_once, calls_box=None):
            return original()

    status = "queued"
    while time.time() < deadline:
        runner.run_once()
        status = client.get(
            f"/api/recordings/{capture_id}/status", headers=user.headers
        ).json()["status"]
        if status == "ready":
            break

    assert status == "ready"
