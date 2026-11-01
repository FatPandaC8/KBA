"""Alembic environment.

The URL is taken from ``DATABASE_URL`` so the same migrations apply to the
local Docker database and a future hosted database (ADR D3). Plain
``postgresql://`` URLs are upgraded to SQLAlchemy's psycopg3 driver.
"""

import os
from urllib.parse import urlparse, urlunparse

from alembic import context
from sqlalchemy import create_engine


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set; migrations refuse to guess a target."
        )
    parsed = urlparse(url)
    if parsed.scheme == "postgresql":
        parsed = parsed._replace(scheme="postgresql+psycopg")
    return urlunparse(parsed)


config = context.config


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
