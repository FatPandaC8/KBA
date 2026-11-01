"""Database factory for selecting between SQLite and PostgreSQL adapters."""

import os
from typing import Any, Dict, Optional

from server.app.infrastructure.config import get_settings


# Global flag to track if database has been initialized
_database_initialized = False


def get_container() -> Any:
    """Get the appropriate container based on configuration."""
    global _database_initialized
    settings = get_settings()
    
    if settings.database_url:
        # Use PostgreSQL
        from server.app.adapters.outbound.persistence.postgres_repos import PostgresContainer
        # Initialize database schema if needed (only once)
        if not _database_initialized:
            from server.app.adapters.outbound.persistence.postgres import init_database
            init_database()
            _database_initialized = True
        return PostgresContainer()
    else:
        # Use SQLite (existing implementation)
        from server.app.api.dependencies import get_container as get_sqlite_container
        return get_sqlite_container()


def reset_database_initialization() -> None:
    """Reset the database initialization flag for testing."""
    global _database_initialized
    _database_initialized = False
    # Also close the PostgreSQL connection pool
    from server.app.adapters.outbound.persistence.postgres import close_pool
    close_pool()