"""Upload durability: a 202 response licenses the client to delete its copy.

REC-04/REC-06 (owner decision 2026-10-29): the mobile client deletes the local
audio as soon as the server answers 202, so that answer must be returned only
after the audio file is stored and the capture/job rows are committed. These
tests read the database through a fresh, independent SQLite connection to prove
commit durability rather than visibility only through the request connection.
"""

import os
import sqlite3
import uuid

from fastapi.testclient import TestClient

from server.app.main import app

from .m3_support import container, upload

client = TestClient(app)

AUDIO = b"\x00" * 512


def _post_upload(user, capture_id: str):
    return client.post(
        "/api/captures/upload",
        headers=user.headers,
        files={"file": ("capture.m4a", AUDIO, "audio/mp4")},
        data={
            "capture_id": capture_id,
            "idempotency_key": capture_id,
            "duration_ms": "2000",
        },
    )


def test_202_returns_only_after_file_and_rows_are_durable(user_factory):
    user = user_factory(client)
    capture_id = upload(client, user, audio=AUDIO)
    c = container()
    real_upload_dir = os.path.realpath(c.settings.upload_dir)

    # 1. The audio file is fully written on disk before the response.
    audio_path = os.path.join(real_upload_dir, user.id, f"{capture_id}.m4a")
    assert os.path.isfile(audio_path)
    with open(audio_path, "rb") as fh:
        assert fh.read() == AUDIO

    # 2. Capture and job rows are committed: a connection the route does not
    # own must already see them, or a 202 could leave no durable record.
    conn = sqlite3.connect(f"file:{c.settings.db_path}?mode=ro", uri=True)
    try:
        capture_row = conn.execute(
            "SELECT user_id, status FROM captures WHERE id = ?", (capture_id,)
        ).fetchone()
        assert capture_row is not None, "capture row must be committed before 202"
        assert capture_row[0] == user.id
        assert capture_row[1] == "received"

        job_row = conn.execute(
            "SELECT capture_id, user_id FROM processing_jobs "
            "WHERE capture_id = ? AND user_id = ?",
            (capture_id, user.id),
        ).fetchone()
        assert job_row is not None, "processing job row must be committed before 202"
    finally:
        conn.close()


def test_202_is_never_sent_when_the_queueing_fails(user_factory, monkeypatch):
    user = user_factory(client)
    c = container()
    capture_id = str(uuid.uuid4())

    def broken_save(capture):
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(c.capture_repo, "save", broken_save)
    response = _post_upload(user, capture_id)

    # No 202: the client keeps its local audio because the server never
    # confirmed storage. The server keeps its file for the retry path too.
    assert response.status_code == 500, response.text
    assert "kept for retry" in response.json()["detail"]

    audio_path = os.path.join(
        os.path.realpath(c.settings.upload_dir), user.id, f"{capture_id}.m4a"
    )
    assert os.path.isfile(audio_path)
