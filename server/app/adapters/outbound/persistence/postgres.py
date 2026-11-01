"""PostgreSQL persistence adapter for the Echo Knowledge API.

This module provides a psycopg 3 implementation of all repository ports,
using psycopg_pool.ConnectionPool for connection management.

Schema differences from SQLite:
- %s placeholders instead of ?
- UUID type for primary keys where applicable
- TIMESTAMPTZ for timestamps
- BOOLEAN type for boolean columns
- JSONB for JSON data
- ON CONFLICT instead of INSERT OR REPLACE/IGNORE
- ILIKE for case-insensitive matching
- Partial unique index for self entity constraint
"""

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from server.app.application.ports import (
    AudioTranscriptionPort,
    CaptureRepositoryPort,
    ConsentRepositoryPort,
    DuplicateCandidateRepositoryPort,
    EmailTokenRepositoryPort,
    EmbeddingRepositoryPort,
    EntityRepositoryPort,
    JobStatusRepositoryPort,
    KnowledgeRepositoryPort,
    RecordSupportRepositoryPort,
    RelationshipRepositoryPort,
    RelationshipTypeRegistryPort,
    SessionRepositoryPort,
    TombstoneRepositoryPort,
    UserRepositoryPort,
)
from server.app.domain.entities import (
    CaptureEntity,
    ConsentEntity,
    EmailTokenEntity,
    ExtractedEntity,
    KnowledgeItemEntity,
    ProcessingJobDTO,
    RelationshipEntity,
    SessionEntity,
    UserEntity,
    current_utc_iso,
    normalize_key,
)
from server.app.domain.errors import ValidationError
from server.app.domain.value_objects import (
    CaptureStatus,
    Certainty,
    ErrorClass,
    JobStage,
    JobStatus,
    RelationStatus,
    RelationType,
)

# Thread-local storage for explicit transaction management
_LOCAL = threading.local()

# Default pool settings
DEFAULT_POOL_MIN = 1
DEFAULT_POOL_MAX = 3
DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_STATEMENT_TIMEOUT = 30000  # 30 seconds
DEFAULT_IDLE_IN_TRANSACTION_TIMEOUT = 30000  # 30 seconds


def _parse_database_url(url: str) -> Dict[str, Any]:
    """Parse a PostgreSQL DATABASE_URL into connection parameters."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValidationError(f"Unsupported database URL scheme: {parsed.scheme}")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") if parsed.path else "postgres",
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


def _get_settings():
    """Lazy import to avoid circular dependency."""
    from server.app.infrastructure.config import get_settings
    return get_settings()


def _get_pool() -> ConnectionPool:
    """Get or create the connection pool from thread-local storage."""
    pool = getattr(_LOCAL, "pool", None)
    if pool is None:
        settings = _get_settings()
        if not settings.database_url:
            raise ValidationError("DATABASE_URL not configured")
        params = _parse_database_url(settings.database_url)
        pool = ConnectionPool(
            conninfo="",
            min_size=DEFAULT_POOL_MIN,
            max_size=DEFAULT_POOL_MAX,
            timeout=30.0,  # Pool timeout - how long to wait for a connection
            kwargs={
                **params,
                "row_factory": dict_row,
                "autocommit": False,
                "connect_timeout": DEFAULT_CONNECT_TIMEOUT,
                "options": f"-c statement_timeout={DEFAULT_STATEMENT_TIMEOUT} "
                f"-c idle_in_transaction_session_timeout={DEFAULT_IDLE_IN_TRANSACTION_TIMEOUT}",
            },
        )
        pool.open()
        _LOCAL.pool = pool
    return pool


def close_pool() -> None:
    """Close the connection pool and remove it from thread-local storage."""
    pool = getattr(_LOCAL, "pool", None)
    if pool is not None:
        pool.close()
        delattr(_LOCAL, "pool")


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Context manager for a database transaction.

    Usage:
        with transaction() as conn:
            conn.execute(...)
            conn.execute(...)
        # commits on success, rolls back on exception
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def get_connection() -> psycopg.Connection:
    """Get a connection from the pool (for non-transactional use).

    Caller must return the connection via put_connection().
    Prefer using transaction() context manager instead.
    """
    pool = _get_pool()
    return pool.getconn()


def put_connection(conn: psycopg.Connection) -> None:
    """Return a connection to the pool."""
    pool = _get_pool()
    pool.putconn(conn)


def init_database() -> None:
    """Initialize the database schema.

    This creates all tables, indexes, and triggers.
    Should be called once at application startup.
    """
    with transaction() as conn:
        _create_schema(conn)


def _create_schema(conn: psycopg.Connection) -> None:
    """Create the full database schema."""
    # UUID extension for uuid_generate_v4() if available
    conn.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    # Users table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL,
            email_normalized TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            google_sub TEXT UNIQUE,
            email_verified_at TIMESTAMPTZ,
            is_locked BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Sessions table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        );
        """
    )
    # Add expires_at column if it doesn't exist (for existing tables)
    conn.execute(
        """
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
        """
    )

    # Email tokens table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token_hash TEXT NOT NULL UNIQUE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

# Consents table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS consents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            version TEXT NOT NULL,
            providers_hash TEXT NOT NULL,
            providers_json TEXT NOT NULL,
            granted BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id)
        );
        """
    )
    # Add updated_at column and trigger if they don't exist (for existing tables)
    conn.execute(
        """
        ALTER TABLE consents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION update_consents_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END $$;
        """
    )
    conn.execute(
        """
        DROP TRIGGER IF EXISTS trigger_update_consents_updated_at ON consents;
        CREATE TRIGGER trigger_update_consents_updated_at
        BEFORE UPDATE ON consents
        FOR EACH ROW EXECUTE FUNCTION update_consents_updated_at();
        """
    )

    # Captures table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS captures (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            audio_path TEXT,
            duration_ms INTEGER,
            status TEXT NOT NULL DEFAULT 'received',
            stage TEXT NOT NULL DEFAULT 'uploaded',
            error_class TEXT,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            user_edited_title BOOLEAN NOT NULL DEFAULT FALSE,
            user_edited_summary BOOLEAN NOT NULL DEFAULT FALSE,
            knowledge_item_id UUID,
            has_audio BOOLEAN NOT NULL DEFAULT FALSE,
            audio_on_server BOOLEAN NOT NULL DEFAULT FALSE,
            idempotency_key TEXT UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    # Add idempotency_key column if it doesn't exist (for existing tables)
    conn.execute(
        """
        ALTER TABLE captures ADD COLUMN IF NOT EXISTS idempotency_key TEXT UNIQUE;
        """
    )

    # Knowledge items table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            core_idea TEXT,
            transcript TEXT,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            details TEXT,
            concepts TEXT[] NOT NULL DEFAULT '{}',
            tags TEXT[] NOT NULL DEFAULT '{}',
            open_questions TEXT[] NOT NULL DEFAULT '{}',
            candidate_relations TEXT[] NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL DEFAULT 'voice-capture',
            provider_id TEXT NOT NULL DEFAULT '',
            model_version TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Entities table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT 'concept',
            description TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            certainty TEXT NOT NULL DEFAULT 'confirmed',
            provenance TEXT NOT NULL DEFAULT 'voice-capture',
            provider_id TEXT NOT NULL DEFAULT '',
            model_version TEXT NOT NULL DEFAULT '',
            user_edited BOOLEAN NOT NULL DEFAULT FALSE,
            is_self BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Self entity partial unique index: at most one self entity per user
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_one_self_per_user
        ON entities(user_id) WHERE is_self = TRUE;
        """
    )

    # Relationships table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relationships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            from_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            to_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'suggested',
            confidence REAL NOT NULL DEFAULT 0.6,
            certainty TEXT NOT NULL DEFAULT 'confirmed',
            source_capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
            provenance TEXT NOT NULL DEFAULT 'voice-capture',
            user_edited BOOLEAN NOT NULL DEFAULT FALSE,
            evidence_utterance TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, from_id, to_id, relation_type)
        );
        """
    )
    # Add updated_at column to existing relationships table
    conn.execute(
        """
        ALTER TABLE relationships ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        """
    )

    # Relationship type registry table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relationship_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            canonical_name TEXT NOT NULL,
            normalized_key TEXT NOT NULL,
            semantic_description TEXT,
            aliases TEXT[] NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL DEFAULT 'registry-seed',
            user_edited BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, normalized_key)
        );
        """
    )
    # Add missing columns to existing tables
    conn.execute(
        """
        ALTER TABLE relationship_types ADD COLUMN IF NOT EXISTS provenance TEXT NOT NULL DEFAULT 'registry-seed';
        """
    )
    conn.execute(
        """
        ALTER TABLE relationship_types ADD COLUMN IF NOT EXISTS user_edited BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )

    # Duplicate candidates table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            score REAL NOT NULL,
            decision TEXT NOT NULL DEFAULT 'pending',
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Tombstones table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tombstones (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            target_kind TEXT NOT NULL,
            target_name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Record supports table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_supports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            record_id UUID NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            target_kind TEXT NOT NULL,
            target_id UUID NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Model evaluation records table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_eval_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
            transcript TEXT,
            structured_json JSONB,
            user_corrected BOOLEAN NOT NULL DEFAULT FALSE,
            consent_given BOOLEAN NOT NULL DEFAULT FALSE,
            pipeline_version TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Knowledge embeddings table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            item_id UUID PRIMARY KEY REFERENCES knowledge_items(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            embedding BYTEA,
            model_name TEXT NOT NULL DEFAULT '',
            dimension INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

# Processing jobs table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
            stage TEXT NOT NULL DEFAULT 'queued',
            status TEXT NOT NULL DEFAULT 'queued',
            attempt INTEGER NOT NULL DEFAULT 0,
            error_class TEXT NOT NULL DEFAULT '',
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_at TIMESTAMPTZ,
            stage_outputs JSONB NOT NULL DEFAULT '{}',
            duration_ms INTEGER,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    # Make lease_expires_at nullable if it's not (for existing tables)
    conn.execute(
        """
        ALTER TABLE processing_jobs ALTER COLUMN lease_expires_at DROP NOT NULL;
        """
    )

    # LLM usage tracking table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider_id TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd NUMERIC(10, 6),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # App settings table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )

    # Admin audit log table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            details JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Triggers for updated_at timestamps
    _create_updated_at_triggers(conn)

    # Integrity triggers
    _create_integrity_triggers(conn)

    # Indexes
    _create_indexes(conn)


def _create_updated_at_triggers(conn: psycopg.Connection) -> None:
    """Create triggers to auto-update updated_at columns."""
    tables_with_updated_at = [
        "users",
        "captures",
        "knowledge_items",
        "entities",
        "relationships",
        "relationship_types",
        "duplicate_candidates",
        "consents",
        "processing_jobs",
        "relationships",
    ]
    for table in tables_with_updated_at:
        conn.execute(
            f"""
            CREATE OR REPLACE FUNCTION update_{table}_updated_at()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END $$;
            """
        )
        conn.execute(
            f"""
            DROP TRIGGER IF EXISTS trigger_update_{table}_updated_at ON {table};
            CREATE TRIGGER trigger_update_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_{table}_updated_at();
            """
        )


def _create_integrity_triggers(conn: psycopg.Connection) -> None:
    """Create triggers for referential integrity that can't be expressed as FKs."""
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION check_relationship_endpoints_same_owner()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM entities WHERE id = NEW.from_id AND user_id = NEW.user_id
                ) OR NOT EXISTS (
                    SELECT 1 FROM entities WHERE id = NEW.to_id AND user_id = NEW.user_id
                ) THEN
                    RAISE EXCEPTION 'relationship endpoints must share owner';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    conn.execute(
        """
        DROP TRIGGER IF EXISTS trg_relationship_endpoints_same_owner ON relationships;
        CREATE TRIGGER trg_relationship_endpoints_same_owner
        BEFORE INSERT OR UPDATE ON relationships
        FOR EACH ROW EXECUTE FUNCTION check_relationship_endpoints_same_owner();
        """
    )

    conn.execute(
        """
        CREATE OR REPLACE FUNCTION check_entity_owner_exists()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM users WHERE id = NEW.user_id
            ) THEN
                RAISE EXCEPTION 'entity owner does not exist';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    conn.execute(
        """
        DROP TRIGGER IF EXISTS trg_entity_owner_exists ON entities;
        CREATE TRIGGER trg_entity_owner_exists
        BEFORE INSERT ON entities
        FOR EACH ROW EXECUTE FUNCTION check_entity_owner_exists();
        """
    )

    conn.execute(
        """
        CREATE OR REPLACE FUNCTION check_relationship_owner_exists()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM users WHERE id = NEW.user_id
            ) THEN
                RAISE EXCEPTION 'relationship owner does not exist';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    conn.execute(
        """
        DROP TRIGGER IF EXISTS trg_relationship_owner_exists ON relationships;
        CREATE TRIGGER trg_relationship_owner_exists
        BEFORE INSERT ON relationships
        FOR EACH ROW EXECUTE FUNCTION check_relationship_owner_exists();
        """
    )


def _create_indexes(conn: psycopg.Connection) -> None:
    """Create all indexes."""
    indexes = [
        # Knowledge items
        ("idx_knowledge_created_at", "knowledge_items", "created_at DESC"),
        ("idx_knowledge_capture_id", "knowledge_items", "capture_id"),
        ("idx_knowledge_user", "knowledge_items", "user_id, created_at DESC"),
        # Relationships
        ("idx_relationships_from_to", "relationships", "from_id, to_id"),
        ("idx_relationships_status", "relationships", "status"),
        ("idx_relationships_user", "relationships", "user_id"),
        ("idx_relationships_capture", "relationships", "source_capture_id"),
        ("idx_relationships_type", "relationships", "relation_type"),
        # Captures
        ("idx_captures_created", "captures", "created_at DESC"),
        ("idx_captures_user", "captures", "user_id, created_at DESC"),
        # Entities
        ("idx_entities_user_name", "entities", "user_id, normalized_name"),
        ("idx_entities_capture", "entities", "capture_id"),
        ("idx_entities_user_type", "entities", "user_id, entity_type"),
        ("idx_entities_user_self", "entities", "user_id") + (" WHERE is_self = TRUE",),
        # Sessions
        ("idx_sessions_token", "sessions", "token_hash"),
        ("idx_sessions_user", "sessions", "user_id"),
        # Email tokens
        ("idx_email_tokens_token", "email_tokens", "token_hash"),
        # Consents
        ("idx_consents_user", "consents", "user_id, created_at DESC"),
        # Record supports
        ("idx_record_supports_record", "record_supports", "record_id"),
        ("idx_record_supports_target", "record_supports", "user_id, target_kind, target_id"),
        # Duplicate candidates
        ("idx_duplicate_candidates_user", "duplicate_candidates", "user_id, decision"),
        # LLM usage
        ("idx_llm_usage_created", "llm_usage", "created_at"),
        ("idx_llm_usage_user_created", "llm_usage", "user_id, created_at"),
        # Processing jobs
        ("idx_processing_jobs_capture", "processing_jobs", "capture_id"),
        ("idx_processing_jobs_user", "processing_jobs", "user_id, created_at DESC"),
        ("idx_processing_jobs_status_lease", "processing_jobs", "status, lease_expires_at"),
        # Admin audit
        ("idx_admin_audit_created", "admin_audit_log", "created_at DESC"),
        ("idx_admin_audit_user", "admin_audit_log", "user_id, created_at DESC"),
        # Relationship types
        ("idx_relationship_types_user", "relationship_types", "user_id, normalized_key"),
        # Model eval
        ("idx_eval_consent", "model_eval_records", "consent_given"),
    ]

    for idx in indexes:
        if isinstance(idx, tuple) and len(idx) == 3 and isinstance(idx[2], str):
            name, table, cols = idx
            where = ""
        elif isinstance(idx, tuple) and len(idx) == 4:
            name, table, cols, where = idx
        else:
            continue
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table}({cols}){where};"
        )