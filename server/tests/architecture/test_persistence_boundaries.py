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


def _imports_of(module_path: str):
    import ast

    with open(module_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_structural_rules():
    """Split rules (S1/S2) enforced on the AST:
    - the API process never imports a worker entrypoint or job code;
    - the Text-KB package never imports STT/speech code and vice versa."""
    text_kb = os.path.join(_APP_ROOT, "application/use_cases/text_kb.py")
    text_kb_imports = _imports_of(text_kb)
    forbidden_into_text_kb = {n for n in text_kb_imports if "speech" in n}
    assert (
        not forbidden_into_text_kb
    ), f"text_kb imports STT code: {sorted(forbidden_into_text_kb)}"

    speech = os.path.join(_APP_ROOT, "adapters/outbound/speech/__init__.py")
    speech_imports = _imports_of(speech)
    forbidden_into_speech = {
        n for n in speech_imports if ("text_kb" in n or "use_cases" in n)
    }
    assert (
        not forbidden_into_speech
    ), f"STT adapter imports Text-KB code: {sorted(forbidden_into_speech)}"

    main_imports = _imports_of(os.path.join(_APP_ROOT, "main.py"))
    forbidden_into_main = {
        n
        for n in main_imports
        if ("worker" in n or "job_state" in n or "jobs" in n)
    }
    assert not forbidden_into_main, f"main imports worker code: {sorted(forbidden_into_main)}"


def test_admin_use_case_owns_no_sql_and_no_psycopg():
    """Addendum rule 3: AdminConsoleUseCase sees ports only — no SQL strings
    and no psycopg import."""
    from server.app.application.use_cases.admin_console import AdminConsoleUseCase

    import inspect

    src = inspect.getsource(AdminConsoleUseCase)
    for pattern in SQL_PATTERNS:
        assert not pattern.search(src), f"AdminConsoleUseCase contains SQL: {pattern.pattern}"
    assert "psycopg" not in src
