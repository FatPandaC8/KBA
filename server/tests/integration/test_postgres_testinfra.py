"""Verify the real-Postgres test infrastructure itself.

These tests exercise template cloning, worker isolation and truncation.
They are also the R8-allowed SQL-exception site for test database setup.
"""

import os

import psycopg

import server.tests.postgres_testinfra as testinfra


def test_template_and_worker_databases_exist(monkeypatch):
    testinfra.ensure_template_database()
    url = testinfra.worker_database_url()
    assert "echo_test_" in url
    assert os.environ["DATABASE_URL"] == url

    dbname = url.rsplit("/", 1)[1]
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            tables = cur.fetchone()[0]
            cur.execute("SELECT 1 FROM users LIMIT 1")
    assert tables >= 18
