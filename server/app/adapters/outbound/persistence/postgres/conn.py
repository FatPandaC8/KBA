"""Connection core for the PostgreSQL adapter.

Ownership model (ADR R1/R7):

- A process owns exactly one ``ConnectionPool`` per ``Database`` instance.
- ``Database.unit_of_work()`` opens ONE connection + ONE transaction. On clean
  exit it commits; on exception it rolls back; the connection is always
  returned to the pool.
- Repositories never commit. They obtain the connection from the ambient
  context while a UoW is open (``with uow:``), or run one short standalone
  transaction when called outside a UoW.
- Domain/application code never sees a connection or SQL.
"""

import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from server.app.infrastructure.config import ServerSettings

# Ambient connection while ``with uow:`` is open (per thread/task context).
_current_conn: ContextVar[Optional[psycopg.Connection]] = ContextVar(
    "echo_pg_conn", default=None
)


def scoped_clause(column: str, user_id: Optional[str]) -> Tuple[str, List[Any]]:
    if user_id is None:
        return "", []
    return f" AND {column} = %s", [user_id]


def scoped_where(column: str, user_id: Optional[str]) -> Tuple[str, List[Any]]:
    if user_id is None:
        return "", []
    return f" WHERE {column} = %s", [user_id]


def safe_uuid(value: Optional[str]):
    """Parse an id-like string; return None when it is not a UUID.

    SQLite tolerated non-UUID lookups (missing row on a no-op). PostgreSQL
    keeps the same external behavior: callers translate None to not-found or
    a silent no-op instead of a 500.
    """
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return None


class UnitOfWork:
    """One connection + one transaction, shared by every repo call inside."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._conn: Optional[psycopg.Connection] = None
        self._token: Any = None

    @property
    def connection(self) -> psycopg.Connection:
        if self._conn is None:
            raise RuntimeError("UnitOfWork used outside `with uow:`")
        return self._conn

    def __enter__(self) -> "UnitOfWork":
        if self._conn is not None:
            raise RuntimeError("UnitOfWork is not reentrant")
        self._conn = self._pool.getconn()
        if self._conn.closed:
            self._conn = self._pool.getconn()
        self._conn.rollback()  # discard any stale transaction on a pooled conn
        self._token = _current_conn.set(self._conn)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            _current_conn.reset(self._token)
            self._token = None
            if not self._conn.closed and not self._conn.broken:
                self._pool.putconn(self._conn)
            else:
                self._pool.putconn(self._conn)
            self._conn = None
        return False  # propagate exceptions after rollback


@contextmanager
def transaction(database):
    """Ambient-or-standalone transaction for repository methods.

    - Inside an open ``with uow:`` this yields the UoW's connection and does
      NOT commit: the UoW owns the transaction (R1).
    - Outside any UoW this yields one short standalone transaction that commits
      on clean exit and rolls back on exception, so direct repo reads/tests keep
      working unchanged.
    """
    pool = database.pool()
    current = _current_conn.get()
    if current is not None and not current.closed:
        yield current
        return
    with UnitOfWork(pool) as uow:
        yield uow.connection


class Database:
    """Process-wide handle around one ``ConnectionPool`` (R7).

    The pool is opened lazily and closed once (API lifespan or worker
    shutdown). Settings control pool size and timeouts; no schema is ever
    created from here.
    """

    def __init__(self, settings: ServerSettings):
        self._settings = settings
        self._pool: Optional[ConnectionPool] = None
        self._lock = threading.Lock()

    def open(self) -> None:
        self.pool()

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    def pool(self) -> ConnectionPool:
        with self._lock:
            if self._pool is None:
                url = self._settings.database_url
                if not url:
                    raise RuntimeError(
                        "DATABASE_URL is not configured; PostgreSQL is the only "
                        "supported database."
                    )
                connect_timeout = self._settings.database_connect_timeout
                options = (
                    f"-c statement_timeout={self._settings.database_statement_timeout_ms} "
                    f"-c idle_in_transaction_session_timeout="
                    f"{self._settings.database_idle_in_tx_timeout_ms}"
                )
                self._pool = ConnectionPool(
                    conninfo=url,
                    min_size=self._settings.database_pool_min,
                    max_size=self._settings.database_pool_max,
                    timeout=connect_timeout,
                    open=True,
                    kwargs={
                        "row_factory": dict_row,
                        "autocommit": False,
                        "connect_timeout": connect_timeout,
                        "options": options,
                    },
                )
            return self._pool

    def unit_of_work(self) -> UnitOfWork:
        return UnitOfWork(self.pool())

    @property
    def pool_ref(self) -> ConnectionPool:
        return self.pool()
