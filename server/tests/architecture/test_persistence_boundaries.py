"""Architecture rules (ADR R8/R10), enforced, not aspirational.

- domain/application may not import psycopg / psycopg_pool / any adapter or
  infrastructure module.
- No SQL-looking statements outside app/adapters/outbound/persistence/postgres
  and the two explicit exceptions (Alembic migrations, test database setup).
- No sqlite3 / PRAGMA / WAL / busy_timeout / INSERT OR ANYWHERE code.
"""

import glob
import os
import re

_APP_ROOT = os.path.join(os.path.dirname(__file__), "../../app")
POSTGRES_ADAPTER = os.path.join(_APP_ROOT, "adapters/outbound/persistence/postgres")

SQL_EXCEPTION_DIRS = (
    os.path.join(_APP_ROOT, "..", "migrations"),  # Alembic baseline + env
    # test database setup lives under tests/ (never scanned below)
)

SQL_PATTERNS = (
    re.compile(r"\bINSERT INTO\b"),
    re.compile(r"\bUPDATE \w+ SET\b"),
    re.compile(r"\bDELETE FROM\b"),
    re.compile(r"\bSELECT .+ FROM \w+"),
)

FORBIDDEN_TEXT = ("PRAGMA", "busy_timeout", "journal_mode", "sqlite3")


def _py_files(root):
    for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        if os.path.basename(path) == "__pycache__":
            continue
        yield path


def _domain_and_application_files():
    files = []
    for layer in ("domain", "application"):
        files.extend(_py_files(os.path.join(_APP_ROOT, layer)))
    return files


def test_domain_and_application_never_import_psycopg_adapters_or_infrastructure():
    forbidden_namespaces = (
        "psycopg",
        "psycopg_pool",
        "server.app.adapters",
        "server.app.infrastructure",
        "fastapi",
    )
    for fpath in _domain_and_application_files():
        with open(fpath, encoding="utf-8") as fh:
            content = fh.read()
        for name in forbidden_namespaces:
            assert f"import {name}" not in content, f"{fpath} imports {name}"
            assert f"from {name}" not in content, f"{fpath} imports from {name}"


def _is_sql_exception(path):
    normalized = os.path.abspath(path)
    migrations = os.path.abspath(os.path.join(_APP_ROOT, "..", "migrations"))
    return normalized.startswith(migrations)


def test_sql_statements_live_only_in_the_postgres_adapter_or_migrations():
    violations = []
    for fpath in _py_files(_APP_ROOT):
        normalized = os.path.abspath(fpath)
        in_adapter = normalized.startswith(os.path.abspath(POSTGRES_ADAPTER))
        if _is_sql_exception(fpath) or in_adapter:
            continue
        with open(fpath, encoding="utf-8") as fh:
            content = fh.read()
        for pattern in SQL_PATTERNS:
            match = pattern.search(content)
            if match:
                violations.append((fpath, pattern.pattern))
    assert not violations, f"SQL found outside the adapter: {violations}"


def test_no_sqlite_leftovers_anywhere_under_app():
    for fpath in _py_files(_APP_ROOT):
        with open(fpath, encoding="utf-8") as fh:
            content = fh.read()
        for token in FORBIDDEN_TEXT:
            assert token not in content, f"{fpath} contains {token}"


def test_structural_rules():
    """Split rules (S1/S2) enforced on source text:
    - the API process never imports or starts a worker entrypoint;
    - the Text-KB package never imports STT/speech code and vice versa."""
    text_kb = open(
        os.path.join(_APP_ROOT, "application/use_cases/text_kb.py"), encoding="utf-8"
    ).read()
    assert "speech" not in text_kb, "text_kb must not import STT/speech code"
    assert "AudioProcessing" not in text_kb
    for token in ("worker", "job_state", "JobQueue", "processing_jobs"):
        content = open(os.path.join(_APP_ROOT, "main.py"), encoding="utf-8").read()
        assert token not in content, f"app/main.py references {token} (worker era)"
    speech = open(
        os.path.join(_APP_ROOT, "adapters/outbound/speech/__init__.py"),
        encoding="utf-8",
    ).read()
    assert "text_kb" not in speech, "STT adapter must not know about Text-KB"


def test_admin_use_case_owns_no_sql_and_no_psycopg():
    """Addendum rule 3: AdminConsoleUseCase sees ports only — no SQL strings
    and no psycopg import."""
    from server.app.application.use_cases.admin_console import AdminConsoleUseCase

    import inspect

    src = inspect.getsource(AdminConsoleUseCase)
    for pattern in SQL_PATTERNS:
        assert not pattern.search(src), f"AdminConsoleUseCase contains SQL: {pattern.pattern}"
    assert "psycopg" not in src
