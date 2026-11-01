"""Real-Postgres test infrastructure.

No SQLite and no DB mocks. One template database carries the migrated schema;
each pytest session (each xdist worker) clones the template into its own
database and TRUNCATEs the schema between tests.

Uses worker process detection (pytest-xdist workerinput) so `pytest -n 4` gets
four isolated databases.
"""

import os
from typing import Dict

import psycopg
from psycopg import sql

MAINTENANCE_DSN = os.environ.get(
    "ECHO_PG_MAINTENANCE_DSN",
    "postgresql://echo:echo_dev_password@127.0.0.1:5432/echo_kb",
)

TEMPLATE_DB = "echo_test_template"
_DB_NAME_BY_WORKER: Dict[str, str] = {}

ALL_TABLES_SQL = """
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public'
    ORDER BY tablename
"""


def _admin_connect(dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        MAINTENANCE_DSN,
        dbname=dbname,
        autocommit=True,
        connect_timeout=10,
    )


def _database_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    return cur.fetchone() is not None


def ensure_template_database() -> None:
    """Create (or refresh) the template database via Alembic.

    Cheap in practice for tests: template creation happens once per process.
    """
    from alembic import command
    from alembic.config import Config

    module_dir = os.path.dirname(os.path.abspath(__file__))  # server/tests
    repo_root = os.path.abspath(os.path.join(module_dir, ".."))  # server/
    alembic_ini = os.path.join(repo_root, "alembic.ini")

    with _admin_connect("postgres") as conn:
        with conn.cursor() as cur:
            if _database_exists(cur, TEMPLATE_DB):
                cur.execute(f"DROP DATABASE {TEMPLATE_DB} WITH (FORCE)")
            cur.execute(f"CREATE DATABASE {TEMPLATE_DB}")

    cfg = Config(alembic_ini)
    cfg.set_main_option("script_location", os.path.join(repo_root, "migrations"))
    os.environ["DATABASE_URL"] = (
        f"postgresql://echo:echo_dev_password@127.0.0.1:5432/{TEMPLATE_DB}"
    )
    command.upgrade(cfg, "head")


def worker_database_url() -> str:
    """DATABASE_URL pointing at this worker's own database."""
    wid = os.environ.get("PYTEST_XDIST_WORKER", "main")
    name = _DB_NAME_BY_WORKER.get(wid)
    if not name:
        name = f"echo_test_{wid}"
        _DB_NAME_BY_WORKER[wid] = name
        with _admin_connect("postgres") as conn:
            with conn.cursor() as cur:
                if _database_exists(cur, name):
                    cur.execute(f"DROP DATABASE {name} WITH (FORCE)")
                cur.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}")
                    .format(sql.Identifier(name), sql.Identifier(TEMPLATE_DB))
                    .as_string(conn)
                )
    parsed = MAINTENANCE_DSN.rsplit("/", 1)[0]
    url = f"{parsed}/{name}"
    os.environ["DATABASE_URL"] = url
    return url


def truncate_schema() -> None:
    """Remove test rows without dropping the migrated schema."""
    with psycopg.connect(
        worker_database_url(), autocommit=True, connect_timeout=10
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(ALL_TABLES_SQL)
            tables = [row[0] for row in cur.fetchall()]
            if not tables:
                return
            cur.execute(
                sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(t) for t in tables)
                )
            )
