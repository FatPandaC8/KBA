"""Upload durability: a 202 response licenses the client to delete its copy.

REC-04/REC-06 (owner decision 2026-10-29): the mobile client deletes the local
audio as soon as the server answers 202, so that answer must be returned only
after the audio file is stored and the capture/job rows are committed. These
tests read the database through a fresh, independent connection to prove
commit durability rather than visibility only through the request connection.
"""

import os
import uuid

from fastapi.testclient import TestClient

from fastapi.testclient import TestClient

from psycopg.rows import dict_row

import psycopg

from server.app.main import app
from server.tests.postgres_testinfra import worker_database_url

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
    with psycopg.connect(
        worker_database_url(), autocommit=True, row_factory=dict_row
    ) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, status FROM captures WHERE id = %s", (capture_id,)
        )
        capture_row = cur.fetchone()
        assert capture_row is not None, "capture row must be committed before 202"
        assert str(capture_row["user_id"]) == user.id
        assert capture_row["status"] == "received"

        cur.execute(
            "SELECT capture_id, user_id FROM processing_jobs "
            "WHERE capture_id = %s AND user_id = %s",
            (capture_id, str(user.id)),
        )
        job_row = cur.fetchone()
        assert job_row is not None, "processing job row must be committed before 202"
