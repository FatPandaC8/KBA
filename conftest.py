"""Test-only configuration.

Tests must never touch the developer's production database or uploads.
Tokens are test values and are intentionally not usable in production.
"""

import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="echo-tests-")
os.environ["ECHO_ENV"] = "test"
os.environ["ECHO_DB_PATH"] = os.path.join(_TEST_DIR, "echo.db")
os.environ["ECHO_UPLOAD_DIR"] = os.path.join(_TEST_DIR, "uploads")
os.environ["ECHO_ADMIN_TOKEN"] = "test-admin-token"
os.environ["ECHO_CLIENT_TOKEN"] = "test-client-token"
