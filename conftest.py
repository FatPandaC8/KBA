"""Test-only configuration.

Tests must never touch developer data. Postgres (via Docker) is the only
database: the template database is cloned once per pytest session/xdist worker
and the schema is truncated between tests.
Tokens below are test values and are intentionally unusable in production.
"""

import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="echo-tests-")
os.environ["ECHO_ENV"] = "test"
os.environ["ECHO_UPLOAD_DIR"] = os.path.join(_TEST_DIR, "uploads")
os.environ["ECHO_ADMIN_TOKEN"] = "test-admin-token"
os.environ["ECHO_CLIENT_TOKEN"] = "test-client-token"
# Automated tests never call a real provider. Tests that need an LLM use the
# deterministic fake port explicitly.
os.environ["ECHO_LLM_PROVIDER"] = "rule_based"
os.environ["ECHO_ALLOW_REAL_LLM"] = "0"
# SQLite is gone; DATABASE_URL is provisioned below from the template database.

import pytest

from server.tests.postgres_testinfra import ensure_template_database, worker_database_url, truncate_schema


@pytest.fixture(scope="session", autouse=True)
def postgres_database():
    """Provision this session's (or this xdist worker's) database."""
    ensure_template_database()
    url = worker_database_url()  # also exports DATABASE_URL
    # Settings dataclass reads env at import; point the singleton at this
    # worker's database and drop any previously built container.
    from server.app.infrastructure.config import get_settings
    from server.app.api.dependencies import reset_container, _CONTAINER

    get_settings().database_url = url


@pytest.fixture(autouse=True)
def clean_database():
    """Every test starts with an empty schema (no database mocks)."""
    truncate_schema()
    yield


@pytest.fixture(scope="session", autouse=True)
def _close_pool():
    yield
    import gc

    gc.collect()
    # Close the process pool so psycopg_pool does not warn at interpreter exit.
    try:
        from server.app.api.dependencies import _CONTAINER

        if _CONTAINER is not None:
            _CONTAINER.close_database()
    except Exception:
        pass
