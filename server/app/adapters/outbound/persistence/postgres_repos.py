"""PostgreSQL repository implementations for the Echo Knowledge API.

This module provides psycopg 3 implementations of all repository ports.
"""

import json
import uuid
import datetime
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from server.app.adapters.outbound.persistence.postgres import (
    _get_pool,
    get_connection,
    put_connection,
    transaction,
)
from server.app.application.ports import (
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
from server.app.domain.value_objects import (
    CaptureStatus,
    Certainty,
    ErrorClass,
    JobStage,
    JobStatus,
    RelationStatus,
    RelationType,
)


# Helper functions for scoped queries
def _scoped(column: str, value: Optional[str]) -> Tuple[str, List]:
    """Return WHERE clause and params for optional user_id scoping."""
    if value is None:
        return "", []
    return f" AND {column} = %s", [value]


def _where_scoped(column: str, value: Optional[str]) -> Tuple[str, List]:
    """Return WHERE clause and params for optional user_id scoping."""
    if value is None:
        return "", []
    return f" WHERE {column} = %s", [value]


# Row mappers
def _row_to_user(r: Dict[str, Any]) -> UserEntity:
    return UserEntity(
        id=str(r["id"]),
        email=r["email"],
        email_normalized=r["email_normalized"],
        password_hash=r["password_hash"],
        google_sub=str(r["google_sub"]) if r["google_sub"] else None,
        email_verified_at=r["email_verified_at"].isoformat() if r["email_verified_at"] else None,
        is_locked=r["is_locked"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )


def _row_to_session(r: Dict[str, Any]) -> SessionEntity:
    return SessionEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        token_hash=r["token_hash"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        last_used_at=r["last_used_at"].isoformat() if r["last_used_at"] else None,
        revoked_at=r["revoked_at"].isoformat() if r["revoked_at"] else None,
    )


def _row_to_capture(r: Dict[str, Any]) -> CaptureEntity:
    return CaptureEntity(
        id=str(r["id"]),
        idempotency_key=r["idempotency_key"],
        user_id=str(r["user_id"]),
        audio_path=r["audio_path"],
        duration_ms=r["duration_ms"],
        status=r["status"],
        stage=r["stage"],
        error_class=r["error_class"],
        error_message=r["error_message"],
        retry_count=r["retry_count"],
        user_edited_title=r["user_edited_title"],
        user_edited_summary=r["user_edited_summary"],
        knowledge_item_id=str(r["knowledge_item_id"]) if r["knowledge_item_id"] else None,
        has_audio=r["has_audio"],
        audio_on_server=r["audio_on_server"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )


def _row_to_knowledge_item(r: Dict[str, Any]) -> KnowledgeItemEntity:
    return KnowledgeItemEntity(
        id=str(r["id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else None,
        title=r["title"],
        core_idea=r["core_idea"],
        transcript=r["transcript"],
        user_id=str(r["user_id"]),
        details=r["details"],
        concepts=r["concepts"] or [],
        tags=r["tags"] or [],
        open_questions=r["open_questions"] or [],
        candidate_relations=r["candidate_relations"] or [],
        provenance=r["provenance"],
        provider_id=r["provider_id"],
        model_version=r["model_version"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )


def _row_to_entity(r: Dict[str, Any]) -> ExtractedEntity:
    return ExtractedEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else None,
        name=r["name"],
        entity_type=r["entity_type"],
        description=r["description"],
        confidence=r["confidence"],
        certainty=r["certainty"],
        provenance=r["provenance"],
        provider_id=r["provider_id"],
        model_version=r["model_version"],
        user_edited=r["user_edited"],
        is_self=r["is_self"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )


def _row_to_relationship(r: Dict[str, Any]) -> RelationshipEntity:
    return RelationshipEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        from_id=str(r["from_id"]),
        to_id=str(r["to_id"]),
        relation_type=r["relation_type"],
        status=r["status"],
        confidence=r["confidence"],
        certainty=r["certainty"],
        source_capture_id=str(r["source_capture_id"]) if r["source_capture_id"] else None,
        provenance=r["provenance"],
        user_edited=r["user_edited"],
        evidence_utterance=r["evidence_utterance"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
    )


def _row_to_processing_job(r: Dict[str, Any]) -> ProcessingJobDTO:
    return ProcessingJobDTO(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        capture_id=str(r["capture_id"]) if r["capture_id"] else None,
        stage=r["stage"],
        status=r["status"],
        attempt=r["attempt"],
        error_class=r["error_class"],
        lease_owner=r["lease_owner"],
        lease_expires_at=r["lease_expires_at"].isoformat() if r["lease_expires_at"] else None,
        stage_outputs=r["stage_outputs"] if isinstance(r["stage_outputs"], dict) else (json.loads(r["stage_outputs"]) if r["stage_outputs"] else {}),
        duration_ms=r["duration_ms"],
        error_message=r["error_message"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
        updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
    )


def _row_to_consent(r: Dict[str, Any]) -> ConsentEntity:
    return ConsentEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        version=r["version"],
        providers_hash=r["providers_hash"],
        providers=json.loads(r["providers_json"]) if isinstance(r["providers_json"], str) and r["providers_json"] else [],
        granted=r["granted"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
    )


def _row_to_email_token(r: Dict[str, Any]) -> EmailTokenEntity:
    return EmailTokenEntity(
        id=str(r["id"]),
        token_hash=r["token_hash"],
        user_id=str(r["user_id"]),
        purpose=r["purpose"],
        expires_at=r["expires_at"].isoformat() if r["expires_at"] else None,
        consumed_at=r["consumed_at"].isoformat() if r["consumed_at"] else None,
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
    )


# Repository implementations

class PostgresUserRepository(UserRepositoryPort):
    def __init__(self):
        pass

    def save(self, user: UserEntity) -> None:
        with transaction() as conn:
            # Insert user
            conn.execute(
                """
                INSERT INTO users (id, email, email_normalized, password_hash, google_sub, email_verified_at, is_locked, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email_normalized) DO UPDATE SET
                    email = EXCLUDED.email,
                    password_hash = EXCLUDED.password_hash,
                    google_sub = EXCLUDED.google_sub,
                    email_verified_at = EXCLUDED.email_verified_at,
                    is_locked = EXCLUDED.is_locked,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    uuid.UUID(user.id),
                    user.email,
                    user.email_normalized,
                    user.password_hash,
                    uuid.UUID(user.google_sub) if user.google_sub else None,
                    user.email_verified_at,
                    user.is_locked,
                    user.created_at,
                    user.updated_at,
                ),
            )
            row = conn.execute(
                """
                INSERT INTO users (id, email, email_normalized, password_hash, google_sub, email_verified_at, is_locked, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email_normalized) DO UPDATE SET
                    email = EXCLUDED.email,
                    password_hash = EXCLUDED.password_hash,
                    google_sub = EXCLUDED.google_sub,
                    email_verified_at = EXCLUDED.email_verified_at,
                    is_locked = EXCLUDED.is_locked,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    uuid.UUID(user.id),
                    user.email,
                    user.email_normalized,
                    user.password_hash,
                    uuid.UUID(user.google_sub) if user.google_sub else None,
                    user.email_verified_at,
                    user.is_locked,
                    user.created_at,
                    user.updated_at,
                ),
            ).fetchone()
            if row:
                user.id = str(row["id"])

            # Create or get self entity for this user (atomic upsert)
            conn.execute(
                """
                INSERT INTO entities (id, user_id, capture_id, name, normalized_name, entity_type, description, confidence, certainty, provenance, provider_id, model_version, user_edited, is_self, created_at, updated_at)
                VALUES (%s, %s, NULL, 'Me', 'me', 'self', '', 1.0, 'confirmed', 'system', '', '', FALSE, TRUE, %s, %s)
                ON CONFLICT (user_id) WHERE is_self DO NOTHING
                """,
                (uuid.uuid4(), uuid.UUID(user.id), user.created_at, user.updated_at),
            )
            conn.commit()

    def get_by_id(self, user_id: str) -> Optional[UserEntity]:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = %s", (uuid.UUID(user_id),)).fetchone()
            return _row_to_user(row) if row else None

    def get_by_email(self, email_normalized: str) -> Optional[UserEntity]:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM users WHERE email_normalized = %s", (email_normalized,)).fetchone()
            return _row_to_user(row) if row else None

    def get_by_google_sub(self, google_sub: str) -> Optional[UserEntity]:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM users WHERE google_sub = %s", (uuid.UUID(google_sub),)).fetchone()
            return _row_to_user(row) if row else None

    def update(self, user: UserEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                UPDATE users SET email = %s, email_normalized = %s, password_hash = %s,
                    google_sub = %s, email_verified_at = %s, is_locked = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (
                    user.email,
                    user.email_normalized,
                    user.password_hash,
                    uuid.UUID(user.google_sub) if user.google_sub else None,
                    user.email_verified_at,
                    user.is_locked,
                    uuid.UUID(user.id),
                ),
            )
            conn.commit()

    def delete(self, user_id: str) -> None:
        with transaction() as conn:
            conn.execute("DELETE FROM users WHERE id = %s", (uuid.UUID(user_id),))
            conn.commit()

    def count(self) -> int:
        with transaction() as conn:
            row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            return row["count"] if row else 0

    def delete(self, user_id: str) -> None:
        with transaction() as conn:
            conn.execute("DELETE FROM users WHERE id = %s", (uuid.UUID(user_id),))
            conn.commit()


class PostgresSessionRepository(SessionRepositoryPort):
    def __init__(self):
        pass

    def save(self, session: SessionEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, last_used_at, revoked_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    last_used_at = EXCLUDED.last_used_at,
                    revoked_at = EXCLUDED.revoked_at
                """,
                (
                    uuid.UUID(session.id),
                    uuid.UUID(session.user_id),
                    session.token_hash,
                    session.created_at,
                    session.last_used_at,
                    session.revoked_at,
                ),
            )
            conn.commit()

    def get_user_by_token_hash(self, token_hash: str) -> Optional[UserEntity]:
        with transaction() as conn:
            row = conn.execute(
                """
                SELECT u.* FROM users u
                JOIN sessions s ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.revoked_at IS NULL
                """,
                (token_hash,),
            ).fetchone()
            return _row_to_user(row) if row else None

    def touch(self, token_hash: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET last_used_at = NOW()
                WHERE token_hash = %s
                  AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '60 seconds')
                """,
                (token_hash,),
            )
            conn.commit()

    def revoke(self, token_hash: str) -> None:
        with transaction() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = NOW() WHERE token_hash = %s AND revoked_at IS NULL",
                (token_hash,),
            )
            conn.commit()

    def revoke_all_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL",
                (uuid.UUID(user_id),),
            )
            conn.commit()
            return cur.rowcount

    # Alias for revoke_all_for_user to match SessionRepositoryPort interface
    def delete_for_user(self, user_id: str) -> int:
        return self.revoke_all_for_user(user_id)

    def create(self, user_id: str, token_hash: str, expires_at: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                (uuid.uuid4(), uuid.UUID(user_id), token_hash, current_utc_iso(), expires_at),
            )
            conn.commit()


class PostgresEmailTokenRepository(EmailTokenRepositoryPort):
    def __init__(self):
        pass

    def save(self, token: EmailTokenEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO email_tokens (id, token_hash, user_id, purpose, expires_at, consumed_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                (
                    uuid.UUID(token.id),
                    token.token_hash,
                    uuid.UUID(token.user_id),
                    token.purpose,
                    token.expires_at,
                    token.consumed_at,
                    token.created_at,
                ),
            )
            conn.commit()

    def consume(self, token_hash: str, purpose: str) -> Optional[str]:
        with transaction() as conn:
            row = conn.execute(
                """
                UPDATE email_tokens
                SET consumed_at = NOW()
                WHERE token_hash = %s AND purpose = %s AND consumed_at IS NULL AND expires_at > NOW()
                RETURNING user_id
                """,
                (token_hash, purpose),
            ).fetchone()
            conn.commit()
            return str(row["user_id"]) if row else None

    def delete_expired(self) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM email_tokens WHERE expires_at < NOW()")
            conn.commit()
            return cur.rowcount

    def create(self, user_id: str, purpose: str, token_hash: str, expires_at: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO email_tokens (id, token_hash, user_id, purpose, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                (uuid.uuid4(), token_hash, uuid.UUID(user_id), purpose, expires_at, current_utc_iso()),
            )
            conn.commit()

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM email_tokens WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount


class PostgresConsentRepository(ConsentRepositoryPort):
    def __init__(self):
        pass

    def save(self, consent: ConsentEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO consents (id, user_id, version, providers_hash, providers_json, granted, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    version = EXCLUDED.version,
                    providers_hash = EXCLUDED.providers_hash,
                    providers_json = EXCLUDED.providers_json,
                    granted = EXCLUDED.granted,
                    created_at = NOW()
                """,
                (
                    uuid.UUID(consent.id),
                    uuid.UUID(consent.user_id),
                    consent.version,
                    consent.providers_hash,
                    json.dumps(consent.providers),
                    consent.granted,
                    consent.created_at,
                ),
            )
            conn.commit()

    def get_latest(self, user_id: str) -> Optional[ConsentEntity]:
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM consents WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                (uuid.UUID(user_id),),
            ).fetchone()
            return _row_to_consent(row) if row else None

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM consents WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount


class PostgresCaptureRepository(CaptureRepositoryPort):
    def __init__(self):
        pass

    def save(self, capture: CaptureEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO captures (id, user_id, audio_path, duration_ms, status, stage, error_class, error_message,
                    retry_count, user_edited_title, user_edited_summary, knowledge_item_id, has_audio, audio_on_server, idempotency_key, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    audio_path = EXCLUDED.audio_path,
                    duration_ms = EXCLUDED.duration_ms,
                    status = EXCLUDED.status,
                    stage = EXCLUDED.stage,
                    error_class = EXCLUDED.error_class,
                    error_message = EXCLUDED.error_message,
                    retry_count = EXCLUDED.retry_count,
                    user_edited_title = EXCLUDED.user_edited_title,
                    user_edited_summary = EXCLUDED.user_edited_summary,
                    knowledge_item_id = EXCLUDED.knowledge_item_id,
                    has_audio = EXCLUDED.has_audio,
                    audio_on_server = EXCLUDED.audio_on_server,
                    idempotency_key = EXCLUDED.idempotency_key,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(capture.id),
                    uuid.UUID(capture.user_id),
                    capture.audio_path,
                    capture.duration_ms,
                    capture.status,
                    capture.stage,
                    capture.error_class,
                    capture.error_message,
                    capture.retry_count,
                    capture.user_edited_title,
                    capture.user_edited_summary,
                    uuid.UUID(capture.knowledge_item_id) if capture.knowledge_item_id else None,
                    capture.has_audio,
                    capture.audio_on_server,
                    capture.idempotency_key,
                    capture.created_at,
                    capture.updated_at,
                ),
            )
            conn.commit()

    def get_by_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[CaptureEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM captures WHERE id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            ).fetchone()
            return _row_to_capture(row) if row else None

    def get_all(self, user_id: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> List[CaptureEntity]:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            sql = f"SELECT * FROM captures{where} ORDER BY created_at DESC, id"
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)
            if offset > 0:
                sql += " OFFSET %s"
                params.append(offset)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_capture(r) for r in rows]

    def delete(self, capture_id: str, user_id: str) -> bool:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM captures WHERE id = %s AND user_id = %s", (uuid.UUID(capture_id), uuid.UUID(user_id)))
            conn.commit()
            return cur.rowcount > 0

    def get_by_idempotency_key(self, key: str, user_id: Optional[str] = None) -> Optional[CaptureEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM captures WHERE idempotency_key = %s{clause}",
                (key, *params),
            ).fetchone()
            return _row_to_capture(row) if row else None

    def list_recent(self, limit: int = 50, user_id: Optional[str] = None) -> List[CaptureEntity]:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            sql = f"SELECT * FROM captures{where} ORDER BY created_at DESC, id LIMIT %s"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_capture(r) for r in rows]

    def list_all(self, user_id: Optional[str] = None) -> List[CaptureEntity]:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            rows = conn.execute(
                f"SELECT * FROM captures{where} ORDER BY created_at DESC, id",
                tuple(params),
            ).fetchall()
            return [_row_to_capture(r) for r in rows]

    def clear_audio_path(self, capture_id: str, user_id: str) -> bool:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"UPDATE captures SET audio_path = NULL, has_audio = FALSE WHERE id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            conn.commit()
            return cur.rowcount > 0

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            row = conn.execute(f"SELECT COUNT(*) FROM captures{clause}", tuple(params)).fetchone()
            return row["count"] if row else 0


class PostgresKnowledgeRepository(KnowledgeRepositoryPort):
    def __init__(self):
        pass

    def save(self, item: KnowledgeItemEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_items (id, capture_id, title, core_idea, transcript, user_id, details, concepts, tags,
                    open_questions, candidate_relations, provenance, provider_id, model_version, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    core_idea = EXCLUDED.core_idea,
                    transcript = EXCLUDED.transcript,
                    details = EXCLUDED.details,
                    concepts = EXCLUDED.concepts,
                    tags = EXCLUDED.tags,
                    open_questions = EXCLUDED.open_questions,
                    candidate_relations = EXCLUDED.candidate_relations,
                    provenance = EXCLUDED.provenance,
                    provider_id = EXCLUDED.provider_id,
                    model_version = EXCLUDED.model_version,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(item.id),
                    uuid.UUID(item.capture_id) if item.capture_id else None,
                    item.title,
                    item.core_idea,
                    item.transcript,
                    uuid.UUID(item.user_id),
                    item.details,
                    item.concepts,
                    item.tags,
                    item.open_questions,
                    item.candidate_relations,
                    item.provenance,
                    item.provider_id,
                    item.model_version,
                    item.created_at,
                    item.updated_at,
                ),
            )
            conn.commit()

    def get_by_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[KnowledgeItemEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM knowledge_items WHERE id = %s{clause}",
                (uuid.UUID(item_id), *params),
            ).fetchone()
            return _row_to_knowledge_item(row) if row else None

    def get_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[KnowledgeItemEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM knowledge_items WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            ).fetchone()
            return _row_to_knowledge_item(row) if row else None

    def get_all(self, query: str = "", limit: Optional[int] = None, offset: int = 0, user_id: Optional[str] = None) -> List[KnowledgeItemEntity]:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            if query:
                where += " AND (title ILIKE %s OR core_idea ILIKE %s OR transcript ILIKE %s)"
                params.extend([f"%{query}%"] * 3)
            sql = f"SELECT * FROM knowledge_items{where} ORDER BY created_at DESC, id"
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)
            if offset > 0:
                sql += " OFFSET %s"
                params.append(offset)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_knowledge_item(r) for r in rows]

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            if user_id is not None:
                conn.execute("DELETE FROM knowledge_items WHERE id = %s AND user_id = %s", (uuid.UUID(item_id), uuid.UUID(user_id)))
            else:
                conn.execute("DELETE FROM knowledge_items WHERE id = %s", (uuid.UUID(item_id),))
            conn.commit()

    def count(self, query: str = "", user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            if query:
                where += " AND (title ILIKE %s OR core_idea ILIKE %s OR transcript ILIKE %s)"
                params.extend([f"%{query}%"] * 3)
            row = conn.execute(
                f"SELECT COUNT(*) FROM knowledge_items{where}",
                tuple(params),
            ).fetchone()
            return row["count"] if row else 0

    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM knowledge_items WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            conn.commit()
            return cur.rowcount


class PostgresEntityRepository(EntityRepositoryPort):
    def __init__(self):
        pass

    def save(self, entity: ExtractedEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO entities (id, user_id, capture_id, name, normalized_name, entity_type, description, confidence,
                    certainty, provenance, provider_id, model_version, user_edited, is_self, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    normalized_name = EXCLUDED.normalized_name,
                    entity_type = EXCLUDED.entity_type,
                    description = EXCLUDED.description,
                    confidence = EXCLUDED.confidence,
                    certainty = EXCLUDED.certainty,
                    provenance = EXCLUDED.provenance,
                    provider_id = EXCLUDED.provider_id,
                    model_version = EXCLUDED.model_version,
                    user_edited = EXCLUDED.user_edited,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(entity.id),
                    uuid.UUID(entity.user_id),
                    uuid.UUID(entity.capture_id) if entity.capture_id else None,
                    entity.name,
                    entity.normalized_name,
                    entity.entity_type,
                    entity.description,
                    entity.confidence,
                    entity.certainty,
                    entity.provenance,
                    entity.provider_id,
                    entity.model_version,
                    entity.user_edited,
                    entity.is_self,
                    entity.created_at,
                    entity.updated_at,
                ),
            )
            conn.commit()

    def get_by_id(self, entity_id: str, user_id: Optional[str] = None) -> Optional[ExtractedEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM entities WHERE id = %s{clause}",
                (uuid.UUID(entity_id), *params),
            ).fetchone()
            return _row_to_entity(row) if row else None

    def get_all(self, user_id: Optional[str] = None, limit: Optional[int] = None) -> List[ExtractedEntity]:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            sql = f"SELECT * FROM entities{where} ORDER BY created_at DESC, id"
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_entity(r) for r in rows]

    def get_self_entity(self, user_id: str) -> Optional[ExtractedEntity]:
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE user_id = %s AND is_self = TRUE LIMIT 1",
                (uuid.UUID(user_id),),
            ).fetchone()
            return _row_to_entity(row) if row else None

    def list_by_capture(self, capture_id: str, user_id: Optional[str] = None) -> List[ExtractedEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            rows = conn.execute(
                f"SELECT * FROM entities WHERE capture_id = %s{clause} ORDER BY id",
                (uuid.UUID(capture_id), *params),
            ).fetchall()
            return [_row_to_entity(r) for r in rows]

    def find_by_normalized(self, user_id: str, normalized_name: str) -> List[ExtractedEntity]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE user_id = %s AND normalized_name = %s ORDER BY id",
                (uuid.UUID(user_id), normalized_name),
            ).fetchall()
            return [_row_to_entity(r) for r in rows]

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            row = conn.execute(f"SELECT COUNT(*) FROM entities{clause}", tuple(params)).fetchone()
            return row["count"] if row else 0

    def delete(self, entity_id: str, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            conn.execute(
                f"DELETE FROM entities WHERE id = %s{clause}",
                (uuid.UUID(entity_id), *params),
            )
            conn.commit()

    def update_fields(self, entity_id: str, user_id: str, name: Optional[str], description: Optional[str]) -> bool:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM entities WHERE id = %s{clause}",
                (uuid.UUID(entity_id), *params),
            ).fetchone()
            if not row:
                return False
            new_name = row["name"] if name is None else name.strip()
            new_description = row["description"] if description is None else description.strip()

            conn.execute(
                """
                UPDATE entities
                SET name = %s, normalized_name = %s, description = %s, user_edited = TRUE, updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (new_name, normalize_key(new_name), new_description, uuid.UUID(entity_id), uuid.UUID(user_id)),
            )
            conn.commit()
            return True

    def cleanup_orphans(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute(
                """DELETE FROM entities WHERE user_id = %s AND is_self = FALSE AND NOT EXISTS
                   (SELECT 1 FROM relationships r WHERE r.user_id = entities.user_id
                    AND (r.from_id = entities.id OR r.to_id = entities.id))
                   AND NOT EXISTS
                   (SELECT 1 FROM duplicate_candidates dc WHERE dc.user_id = entities.user_id
                    AND (dc.source_entity_id = entities.id OR dc.target_entity_id = entities.id))""",
                (uuid.UUID(user_id),),
            )
            conn.commit()
            return cur.rowcount


class PostgresRelationshipRepository(RelationshipRepositoryPort):
    def __init__(self):
        pass

    def save(self, rel: RelationshipEntity) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO relationships (id, user_id, from_id, to_id, relation_type, status, confidence,
                    certainty, source_capture_id, provenance, user_edited, evidence_utterance, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, from_id, to_id, relation_type) DO UPDATE SET
                    confidence = GREATEST(relationships.confidence, EXCLUDED.confidence),
                    certainty = CASE
                        WHEN relationships.certainty = 'conflicting' OR EXCLUDED.certainty = 'conflicting'
                        THEN 'conflicting' ELSE relationships.certainty END,
                    source_capture_id = CASE
                        WHEN relationships.source_capture_id IS NULL THEN EXCLUDED.source_capture_id
                        ELSE relationships.source_capture_id END,
                    evidence_utterance = CASE
                        WHEN relationships.evidence_utterance IS NULL THEN EXCLUDED.evidence_utterance
                        ELSE relationships.evidence_utterance END,
                    status = CASE
                        WHEN relationships.user_edited = TRUE THEN relationships.status
                        ELSE EXCLUDED.status END
                """,
                (
                    uuid.UUID(rel.id),
                    uuid.UUID(rel.user_id),
                    uuid.UUID(rel.from_id),
                    uuid.UUID(rel.to_id),
                    rel.relation_type,
                    rel.status,
                    rel.confidence,
                    rel.certainty,
                    uuid.UUID(rel.source_capture_id) if rel.source_capture_id else None,
                    rel.provenance,
                    rel.user_edited,
                    (rel.evidence_utterance or "")[:280],
                    rel.created_at,
                ),
            )
            conn.commit()

    def get_by_id(self, rel_id: str, user_id: Optional[str] = None) -> Optional[RelationshipEntity]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM relationships WHERE id = %s{clause}",
                (uuid.UUID(rel_id), *params),
            ).fetchone()
            return _row_to_relationship(row) if row else None

    def get_all(self, user_id: Optional[str] = None) -> List[RelationshipEntity]:
        with transaction() as conn:
            where, params = _where_scoped("user_id", user_id)
            rows = conn.execute(
                f"SELECT * FROM relationships{where} ORDER BY created_at DESC, id",
                tuple(params),
            ).fetchall()
            return [_row_to_relationship(r) for r in rows]

    def get_between(self, user_id: str, from_id: str, to_id: str) -> List[RelationshipEntity]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE user_id = %s AND from_id = %s AND to_id = %s ORDER BY id",
                (uuid.UUID(user_id), uuid.UUID(from_id), uuid.UUID(to_id)),
            ).fetchall()
            return [_row_to_relationship(r) for r in rows]

    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            conn.execute(
                f"DELETE FROM relationships WHERE (from_id = %s OR to_id = %s){clause}",
                (uuid.UUID(entity_id), uuid.UUID(entity_id), *params),
            )
            conn.commit()

    def delete(self, rel_id: str, user_id: Optional[str] = None) -> bool:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM relationships WHERE id = %s{clause}",
                (uuid.UUID(rel_id), *params),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_for_entity(self, user_id: str, entity_id: str) -> List[RelationshipEntity]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE user_id = %s AND (from_id = %s OR to_id = %s) ORDER BY id",
                (uuid.UUID(user_id), uuid.UUID(entity_id), uuid.UUID(entity_id)),
            ).fetchall()
            return [_row_to_relationship(r) for r in rows]

    def update_status(self, rel_id: str, status: str, relation_type: Optional[str] = None, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            if relation_type:
                conn.execute(
                    f"UPDATE relationships SET status = %s WHERE id = %s AND relation_type = %s{clause}",
                    (status, uuid.UUID(rel_id), relation_type, *params),
                )
            else:
                conn.execute(
                    f"UPDATE relationships SET status = %s WHERE id = %s{clause}",
                    (status, uuid.UUID(rel_id), *params),
                )
            conn.commit()

    def delete(self, rel_id: str, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            conn.execute(
                f"DELETE FROM relationships WHERE id = %s{clause}",
                (uuid.UUID(rel_id), *params),
            )
            conn.commit()

    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM relationships WHERE (from_id = %s OR to_id = %s){clause}",
                (uuid.UUID(entity_id), uuid.UUID(entity_id), *params),
            )
            conn.commit()
            return cur.rowcount

    def get_graph(self, user_id: Optional[str] = None) -> Any:
        from server.app.application.dto import GraphDataDTO
        from server.app.domain.graph_layout import compute_graph_layout
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            # Get nodes
            nodes = conn.execute(
                f"SELECT * FROM entities{clause} ORDER BY created_at",
                tuple(params),
            ).fetchall()
            # Get edges
            edges = conn.execute(
                f"SELECT * FROM relationships{clause} ORDER BY created_at",
                tuple(params),
            ).fetchall()

            nodes_dto, edges_dto, clusters_dto = compute_graph_layout(nodes, edges)

            return GraphDataDTO(
                nodes=nodes_dto,
                edges=edges_dto,
                clusters=clusters_dto,
            )

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            row = conn.execute(f"SELECT COUNT(*) FROM relationships{clause}", tuple(params)).fetchone()
            return row["count"] if row else 0

    def count_orphans(self, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            row = conn.execute(
                f"""SELECT COUNT(*) FROM entities e{clause} WHERE e.is_self = FALSE AND NOT EXISTS
                   (SELECT 1 FROM relationships r WHERE r.user_id = e.user_id
                    AND (r.from_id = e.id OR r.to_id = e.id))""",
                tuple(params),
            ).fetchone()
            return row["count"] if row else 0
    def __init__(self):
        pass

    def record(self, user_id: str, source_entity_id: str, target_entity_id: str, score: float, decision: str = "pending") -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO duplicate_candidates (id, user_id, source_entity_id, target_entity_id, score, decision, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    uuid.UUID(source_entity_id),
                    uuid.UUID(target_entity_id),
                    score,
                    decision,
                    current_utc_iso(),
                ),
            )
            conn.commit()

    def list_flagged(self, user_id: str) -> List[Dict[str, Any]]:
        print(f"[DEBUG list_flagged] Querying for user_id: {user_id}", flush=True)
        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT dc.*, e1.name as source_name, e2.name as target_name
                FROM duplicate_candidates dc
                JOIN entities e1 ON dc.source_entity_id = e1.id
                JOIN entities e2 ON dc.target_entity_id = e2.id
                WHERE dc.user_id = %s AND dc.decision = 'flagged'
                ORDER BY dc.created_at DESC
                """,
                (uuid.UUID(user_id),),
            ).fetchall()
            print(f"[DEBUG list_flagged] Found {len(rows)} flagged duplicates", flush=True)
            if len(rows) == 0:
                # Debug: check raw table
                check_rows = conn.execute("SELECT * FROM duplicate_candidates WHERE user_id = %s", (uuid.UUID(user_id),)).fetchall()
                print(f"[DEBUG list_flagged] Raw table has {len(check_rows)} rows for user", flush=True)
                for r in check_rows:
                    print(f"  {r}", flush=True)
            return [
                {
                    "source_entity_id": str(r["source_entity_id"]),
                    "target_entity_id": str(r["target_entity_id"]),
                    "source_name": r["source_name"],
                    "target_name": r["target_name"],
                    "score": r["score"],
                    "decision": r["decision"],
                    "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]

    def decide(self, user_id: str, source_entity_id: str, target_entity_id: str, decision: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                UPDATE duplicate_candidates
                SET decision = %s, decided_at = NOW()
                WHERE user_id = %s AND source_entity_id = %s AND target_entity_id = %s
                """,
                (decision, uuid.UUID(user_id), uuid.UUID(source_entity_id), uuid.UUID(target_entity_id)),
            )
            conn.commit()




class PostgresDuplicateRepository(DuplicateCandidateRepositoryPort):
    def __init__(self):
        pass

    def record(self, user_id: str, source_entity_id: str, target_entity_id: str, score: float, decision: str = "pending") -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO duplicate_candidates (id, user_id, source_entity_id, target_entity_id, score, decision, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    uuid.UUID(source_entity_id),
                    uuid.UUID(target_entity_id),
                    score,
                    decision,
                    current_utc_iso(),
                ),
            )
            conn.commit()

    def list_flagged(self, user_id: str) -> List[Dict[str, Any]]:
        print(f"[DEBUG list_flagged] Querying for user_id: {user_id}", flush=True)
        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT dc.*, e1.name as source_name, e2.name as target_name
                FROM duplicate_candidates dc
                JOIN entities e1 ON dc.source_entity_id = e1.id
                JOIN entities e2 ON dc.target_entity_id = e2.id
                WHERE dc.user_id = %s AND dc.decision = 'flagged'
                ORDER BY dc.created_at DESC
                """,
                (uuid.UUID(user_id),),
            ).fetchall()
            print(f"[DEBUG list_flagged] Found {len(rows)} flagged duplicates", flush=True)
            if len(rows) == 0:
                # Debug: check raw table
                check_rows = conn.execute("SELECT * FROM duplicate_candidates WHERE user_id = %s", (uuid.UUID(user_id),)).fetchall()
                print(f"[DEBUG list_flagged] Raw table has {len(check_rows)} rows for user", flush=True)
                for r in check_rows:
                    print(f"  {r}", flush=True)
            return [
                {
                    "source_entity_id": str(r["source_entity_id"]),
                    "target_entity_id": str(r["target_entity_id"]),
                    "source_name": r["source_name"],
                    "target_name": r["target_name"],
                    "score": r["score"],
                    "decision": r["decision"],
                    "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]

    def decide(self, user_id: str, source_entity_id: str, target_entity_id: str, decision: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                UPDATE duplicate_candidates
                SET decision = %s, decided_at = NOW()
                WHERE user_id = %s AND source_entity_id = %s AND target_entity_id = %s
                """,
                (decision, uuid.UUID(user_id), uuid.UUID(source_entity_id), uuid.UUID(target_entity_id)),
            )
            conn.commit()

    def delete_for_entity(self, entity_id: str, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM duplicate_candidates WHERE source_entity_id = %s OR target_entity_id = %s{clause}",
                (uuid.UUID(entity_id), uuid.UUID(entity_id), *params),
            )
            conn.commit()
            return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM duplicate_candidates WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount


class PostgresTombstoneRepository(TombstoneRepositoryPort):
    def __init__(self):
        pass

    def add(self, user_id: str, target_kind: str, target_name: str) -> None:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO tombstones (id, user_id, target_kind, target_name, created_at) VALUES (%s, %s, %s, %s, %s)",
                (uuid.uuid4(), uuid.UUID(user_id), target_kind, target_name, current_utc_iso()),
            )
            conn.commit()

    def is_tombstoned(self, user_id: str, target_kind: str, target_name: str) -> bool:
        with transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM tombstones WHERE user_id = %s AND target_kind = %s AND target_name = %s",
                (uuid.UUID(user_id), target_kind, target_name),
            ).fetchone()
            return row is not None

    def list_for_user(self, user_id: str) -> List[Dict[str, str]]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT target_kind, target_name FROM tombstones WHERE user_id = %s ORDER BY created_at DESC",
                (uuid.UUID(user_id),),
            ).fetchall()
            return [{"target_kind": r["target_kind"], "target_name": r["target_name"]} for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM tombstones WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount


class PostgresSupportRepository(RecordSupportRepositoryPort):
    def __init__(self):
        pass

    def add(self, user_id: str, capture_id: str, target_kind: str, target_id: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO record_supports (id, record_id, target_kind, target_id, user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(capture_id),
                    target_kind,
                    uuid.UUID(target_id),
                    uuid.UUID(user_id),
                    current_utc_iso(),
                ),
            )
            conn.commit()

    def list_for_target(self, user_id: str, target_kind: str, target_id: str) -> List[str]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT record_id FROM record_supports WHERE user_id = %s AND target_kind = %s AND target_id = %s",
                (uuid.UUID(user_id), target_kind, uuid.UUID(target_id)),
            ).fetchall()
            return [str(r["record_id"]) for r in rows]

    def delete_for_target(self, user_id: str, target_kind: str, target_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM record_supports WHERE user_id = %s AND target_kind = %s AND target_id = %s",
                (uuid.UUID(user_id), target_kind, uuid.UUID(target_id)),
            )
            conn.commit()
            return cur.rowcount

    def list_for_record(self, user_id: str, capture_id: str) -> List[Dict[str, str]]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT target_kind, target_id FROM record_supports WHERE user_id = %s AND record_id = %s",
                (uuid.UUID(user_id), uuid.UUID(capture_id)),
            ).fetchall()
            return [{"target_kind": r["target_kind"], "target_id": str(r["target_id"])} for r in rows]

    def delete_for_record(self, user_id: str, capture_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM record_supports WHERE user_id = %s AND record_id = %s",
                (uuid.UUID(user_id), uuid.UUID(capture_id)),
            )
            conn.commit()
            return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM record_supports WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount


class PostgresRelationshipTypeRegistry(RelationshipTypeRegistryPort):
    def __init__(self):
        pass

    def ensure(
        self,
        user_id: Optional[str],
        canonical_name: str,
        semantic_description: str = "",
        aliases: Optional[List[str]] = None,
        provenance: str = "extraction",
        user_edited: bool = False,
    ) -> "RelationshipTypeRegistryEntry":
        from server.app.domain.entities import RelationshipTypeRegistryEntry
        normalized = normalize_key(canonical_name)
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM relationship_types WHERE user_id = %s AND normalized_key = %s",
                (uuid.UUID(user_id) if user_id else None, normalized),
            ).fetchone()
            if row:
                return RelationshipTypeRegistryEntry(
                    id=str(row["id"]),
                    user_id=str(row["user_id"]) if row["user_id"] else "",
                    canonical_name=row["canonical_name"],
                    semantic_description=row["semantic_description"],
                    aliases=row["aliases"] or [],
                    provenance=row["provenance"] if row["provenance"] else "registry-seed",
                    user_edited=row["user_edited"],
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                )
            new_id = uuid.uuid4()
            conn.execute(
                """
                INSERT INTO relationship_types (id, user_id, canonical_name, normalized_key, semantic_description, aliases, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    new_id,
                    uuid.UUID(user_id) if user_id else None,
                    canonical_name,
                    normalized,
                    semantic_description,
                    aliases or [],
                    current_utc_iso(),
                ),
            )
            conn.commit()
            return RelationshipTypeRegistryEntry(
                id=str(new_id),
                user_id=user_id or "",
                canonical_name=canonical_name,
                semantic_description=semantic_description,
                aliases=aliases or [],
                provenance=provenance,
                user_edited=user_edited,
                created_at=current_utc_iso(),
            )

    def find_equivalent(
        self, user_id: Optional[str], names: List[str]
    ) -> Optional["RelationshipTypeRegistryEntry"]:
        from server.app.domain.entities import RelationshipTypeRegistryEntry
        normalized_names = [normalize_key(n) for n in names]
        with transaction() as conn:
            for norm in normalized_names:
                row = conn.execute(
                    "SELECT * FROM relationship_types WHERE (user_id = %s OR user_id IS NULL) AND normalized_key = %s",
                    (uuid.UUID(user_id) if user_id else None, norm),
                ).fetchone()
                if row:
                    return RelationshipTypeRegistryEntry(
                        id=str(row["id"]),
                        user_id=str(row["user_id"]) if row["user_id"] else "",
                        canonical_name=row["canonical_name"],
                        semantic_description=row["semantic_description"],
                        aliases=row["aliases"] or [],
                        provenance=row["provenance"] if row["provenance"] else "registry-seed",
                        user_edited=row["user_edited"],
                        created_at=row["created_at"].isoformat() if row["created_at"] else None,
                    )
        return None

    def update(
        self,
        entry_id: str,
        *,
        semantic_description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> bool:
        with transaction() as conn:
            # Build the update query dynamically
            updates = []
            params = []
            if semantic_description is not None:
                updates.append("semantic_description = %s")
                params.append(semantic_description)
            if aliases is not None:
                updates.append("aliases = %s")
                params.append(aliases)
            if not updates:
                return False
            params.append(uuid.UUID(entry_id))
            conn.execute(
                f"UPDATE relationship_types SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
            conn.commit()
            return True

    def get_or_create(self, user_id: str, canonical_name: str, semantic_description: str = "", aliases: List[str] = None) -> Dict[str, Any]:
        normalized = normalize_key(canonical_name)
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM relationship_types WHERE user_id = %s AND normalized_key = %s",
                (uuid.UUID(user_id), normalized),
            ).fetchone()
            if row:
                return {
                    "canonical_name": row["canonical_name"],
                    "normalized_key": row["normalized_key"],
                    "semantic_description": row["semantic_description"],
                    "aliases": row["aliases"] or [],
                }
            conn.execute(
                """
                INSERT INTO relationship_types (id, user_id, canonical_name, normalized_key, semantic_description, aliases, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    canonical_name,
                    normalized,
                    semantic_description,
                    aliases or [],
                    current_utc_iso(),
                ),
            )
            conn.commit()
            return {
                "canonical_name": canonical_name,
                "normalized_key": normalized,
                "semantic_description": semantic_description,
                "aliases": aliases or [],
            }

    def list_for_user(self, user_id: str) -> List["RelationshipTypeRegistryEntry"]:
        from server.app.domain.entities import RelationshipTypeRegistryEntry
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM relationship_types WHERE user_id = %s ORDER BY created_at DESC",
                (uuid.UUID(user_id),),
            ).fetchall()
            return [
                RelationshipTypeRegistryEntry(
                    id=str(r["id"]),
                    user_id=str(r["user_id"]) if r["user_id"] else "",
                    canonical_name=r["canonical_name"],
                    semantic_description=r["semantic_description"],
                    aliases=r["aliases"] or [],
                    provenance=r["provenance"] if r["provenance"] else "registry-seed",
                    user_edited=r["user_edited"],
                    created_at=r["created_at"].isoformat() if r["created_at"] else None,
                )
                for r in rows
            ]


class PostgresJobRepository(JobStatusRepositoryPort):
    def __init__(self):
        pass

    def record_job(self, job: ProcessingJobDTO) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO processing_jobs (id, user_id, capture_id, stage, status, attempt, error_class,
                    lease_owner, lease_expires_at, stage_outputs, duration_ms, error_message, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    status = EXCLUDED.status,
                    attempt = EXCLUDED.attempt,
                    error_class = EXCLUDED.error_class,
                    lease_owner = EXCLUDED.lease_owner,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    stage_outputs = EXCLUDED.stage_outputs,
                    duration_ms = EXCLUDED.duration_ms,
                    error_message = EXCLUDED.error_message,
                    updated_at = NOW()
                """,
                (
                    uuid.UUID(job.id),
                    uuid.UUID(job.user_id),
                    uuid.UUID(job.capture_id) if job.capture_id else None,
                    job.stage,
                    job.status,
                    job.attempt,
                    job.error_class,
                    job.lease_owner,
                    job.lease_expires_at,
                    json.dumps(job.stage_outputs) if isinstance(job.stage_outputs, dict) else job.stage_outputs,
                    job.duration_ms,
                    job.error_message,
                    job.created_at,
                    job.updated_at,
                ),
            )
            conn.commit()

    def claim(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None, retry_limit: int = 3) -> Optional[ProcessingJobDTO]:
        with transaction() as conn:
            now = datetime.datetime.now(timezone.utc)
            expires = now + datetime.timedelta(seconds=lease_seconds)
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET lease_owner = %s, lease_expires_at = %s, status = 'running', updated_at = %s
                WHERE capture_id = %s
                  AND attempt < %s
                  AND (
                        status = 'queued'
                     OR (status IN ('running', 'processing') AND (lease_owner = '' OR lease_expires_at < %s))
                  ){clause}
                RETURNING *
                """,
                (lease_owner, expires, now.isoformat(), uuid.UUID(capture_id), retry_limit, now.isoformat(), *params),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_processing_job(row) if row else None

    def get_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> Optional[ProcessingJobDTO]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT * FROM processing_jobs WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            ).fetchone()
            return _row_to_processing_job(row) if row else None

    def list_resumable(self, now: str, retry_limit: int = 3) -> List[ProcessingJobDTO]:
        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT * FROM processing_jobs
                WHERE attempt < %s
                  AND status IN ('queued', 'running', 'processing')
                  AND (lease_owner = '' OR lease_expires_at < %s)
                ORDER BY updated_at
                """,
                (retry_limit, now),
            ).fetchall()
            return [_row_to_processing_job(r) for r in rows]

    def save_stage_output(self, capture_id: str, stage: str, output: Dict[str, Any], user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            conn.execute(
                f"""
                UPDATE processing_jobs
                SET stage = %s, stage_outputs = stage_outputs || %s, updated_at = %s
                WHERE capture_id = %s{clause}
                """,
                (stage, json.dumps(output), current_utc_iso(), uuid.UUID(capture_id), *params),
            )
            conn.commit()

    def complete(self, capture_id: str, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            conn.execute(
                f"""
                UPDATE processing_jobs
                SET status = 'ready', stage = 'completed', lease_owner = '', lease_expires_at = NOW(), updated_at = %s
                WHERE capture_id = %s{clause}
                """,
                (current_utc_iso(), uuid.UUID(capture_id), *params),
            )
            conn.commit()

    def record_attempt(self, capture_id: str, attempt: int, error_class: str, error_message: str, user_id: Optional[str] = None, retry_limit: int = 3) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            terminal = not ErrorClass.is_recoverable(error_class) or attempt >= retry_limit
            new_status = 'failed' if terminal else 'queued'
            conn.execute(
                f"""
                UPDATE processing_jobs
                SET attempt = %s, error_class = %s, error_message = %s, status = %s, updated_at = %s
                WHERE capture_id = %s{clause}
                """,
                (attempt, error_class, error_message, new_status, current_utc_iso(), uuid.UUID(capture_id), *params),
            )
            conn.commit()

    def renew_lease(self, capture_id: str, lease_owner: str, lease_seconds: int, user_id: Optional[str] = None) -> bool:
        with transaction() as conn:
            expires = datetime.now(timezone.utc) + datetime.timedelta(seconds=lease_seconds)
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET lease_expires_at = %s, updated_at = %s
                WHERE capture_id = %s AND lease_owner = %s{clause}
                """,
                (expires.isoformat(), datetime.now(timezone.utc).isoformat(), uuid.UUID(capture_id), lease_owner, *params),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_job_status(self, capture_id: str, stage: str, status: str, error_message: Optional[str] = None, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            if error_message:
                conn.execute(
                    f"""
                    UPDATE processing_jobs
                    SET stage = %s, status = %s, error_message = %s, updated_at = %s
                    WHERE capture_id = %s{clause}
                    """,
                    (stage, status, error_message, current_utc_iso(), uuid.UUID(capture_id), *params),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE processing_jobs
                    SET stage = %s, status = %s, updated_at = %s
                    WHERE capture_id = %s{clause}
                    """,
                    (stage, status, current_utc_iso(), uuid.UUID(capture_id), *params),
                )
            conn.commit()

    def get_recent_jobs(self, limit: int = 50, user_id: Optional[str] = None) -> List[ProcessingJobDTO]:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            sql = f"SELECT * FROM processing_jobs{clause} ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_processing_job(r) for r in rows]

    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM processing_jobs WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            conn.commit()
            return cur.rowcount

    def release(self, capture_id: str, lease_owner: str, user_id: Optional[str] = None) -> bool:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET lease_owner = '', lease_expires_at = NOW(), status = 'queued', updated_at = %s
                WHERE capture_id = %s AND lease_owner = %s{clause}
                """,
                (current_utc_iso(), uuid.UUID(capture_id), lease_owner, *params),
            )
            conn.commit()
            return cur.rowcount > 0

    def reset_for_retry(self, capture_id: str, user_id: Optional[str] = None) -> bool:
        """Reset a job for retry by clearing lease and resetting status to queued."""
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"""
                UPDATE processing_jobs
                SET lease_owner = '', lease_expires_at = NOW(), status = 'queued', 
                    stage = 'queued', error_class = '', error_message = NULL, updated_at = %s
                WHERE capture_id = %s{clause}
                """,
                (current_utc_iso(), uuid.UUID(capture_id), *params),
            )
            conn.commit()
            return cur.rowcount > 0


class PostgresEmbeddingRepository(EmbeddingRepositoryPort):
    def __init__(self):
        pass

    def save(self, item_id: str, embedding: bytes, user_id: str = "", model_name: str = "", dimension: int = 0) -> None:
        print(f"[DEBUG embedding_repo.save] user_id = {repr(user_id)}", flush=True)
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_embeddings (item_id, user_id, embedding, model_name, dimension, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (item_id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    model_name = EXCLUDED.model_name,
                    dimension = EXCLUDED.dimension,
                    updated_at = NOW()
                """,
                (uuid.UUID(item_id), uuid.UUID(user_id), embedding, model_name, dimension, current_utc_iso()),
            )
            conn.commit()

    def get(self, item_id: str, user_id: Optional[str] = None) -> Optional[bytes]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT embedding FROM knowledge_embeddings WHERE item_id = %s{clause}",
                (uuid.UUID(item_id), *params),
            ).fetchone()
            return row["embedding"] if row else None

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            conn.execute(
                f"DELETE FROM knowledge_embeddings WHERE item_id = %s{clause}",
                (uuid.UUID(item_id), *params),
            )
            conn.commit()

    def get_by_item_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[bytes]:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT embedding FROM knowledge_embeddings WHERE item_id = %s{clause}",
                (uuid.UUID(item_id), *params),
            ).fetchone()
            return row["embedding"] if row else None

    def get_all(self, user_id: Optional[str] = None) -> List[Tuple[str, bytes]]:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            rows = conn.execute(
                f"SELECT item_id, embedding FROM knowledge_embeddings{clause}",
                tuple(params),
            ).fetchall()
            return [(str(r["item_id"]), r["embedding"]) for r in rows]

    def count(self, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            row = conn.execute(
                f"SELECT COUNT(*) FROM knowledge_embeddings{clause}",
                tuple(params),
            ).fetchone()
            return row["count"] if row else 0


class PostgresEvalRecordRepository:
    """Repository for model evaluation records."""

    def __init__(self):
        pass

    def save(self, item_id: str, user_id: str, capture_id: Optional[str], transcript: str, 
             structured_json: Dict[str, Any], user_corrected: bool, consent_given: bool, 
             pipeline_version: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO model_eval_records (id, user_id, capture_id, transcript, structured_json, 
                    user_corrected, consent_given, pipeline_version, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    uuid.UUID(capture_id) if capture_id else None,
                    transcript,
                    json.dumps(structured_json),
                    user_corrected,
                    consent_given,
                    pipeline_version,
                    current_utc_iso(),
                ),
            )
            conn.commit()

    def list_all(self, user_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with transaction() as conn:
            clause, params = _where_scoped("user_id", user_id)
            sql = f"SELECT * FROM model_eval_records{clause} ORDER BY created_at DESC"
            if limit:
                sql += " LIMIT %s"
                params.append(limit)
            if offset:
                sql += " OFFSET %s"
                params.append(offset)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM model_eval_records WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount

    def delete_by_capture_id(self, capture_id: str, user_id: Optional[str] = None) -> int:
        with transaction() as conn:
            clause, params = _scoped("user_id", user_id)
            cur = conn.execute(
                f"DELETE FROM model_eval_records WHERE capture_id = %s{clause}",
                (uuid.UUID(capture_id), *params),
            )
            conn.commit()
            return cur.rowcount


class PostgresAdminAuditLogRepository:
    """Repository for admin audit logs."""

    def __init__(self):
        pass

    def log(self, user_id: str, action: str, details: Optional[Dict[str, Any]] = None) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO admin_audit_log (id, user_id, action, details, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    action,
                    json.dumps(details) if details else None,
                    current_utc_iso(),
                ),
            )
            conn.commit()

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM admin_audit_log WHERE user_id = %s", (uuid.UUID(user_id),))
            conn.commit()
            return cur.rowcount


class PostgresLLMUsageRepository:
    """Repository for LLM usage tracking."""

    def __init__(self):
        pass

    def log_usage(self, user_id: str, provider_id: str, model: str, 
                  prompt_tokens: int, completion_tokens: int, total_tokens: int, cost_usd: Optional[float] = None) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO llm_usage (id, user_id, provider_id, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    provider_id,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost_usd,
                    current_utc_iso(),
                ),
            )
            conn.commit()

    def usage_since(self, since: str) -> Dict[str, int]:
        with transaction() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(calls), 0) as calls, COALESCE(SUM(total_tokens), 0) as total_tokens
                FROM (
                    SELECT COUNT(*) as calls, SUM(total_tokens) as total_tokens
                    FROM llm_usage WHERE created_at >= %s
                ) t
                """,
                (since,),
            ).fetchone()
            return {"calls": row["calls"] or 0, "total_tokens": row["total_tokens"] or 0}

    def last_calls(self, limit: int = 10) -> List[Dict[str, Any]]:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_usage ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


class PostgresAppSettingsRepository:
    """Repository for application settings."""

    def __init__(self):
        pass

    def get(self, key: str) -> Optional[str]:
        with transaction() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s",
                (key,),
            ).fetchone()
            return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )
            conn.commit()

    def delete(self, key: str) -> None:
        with transaction() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = %s", (key,))
            conn.commit()


# Composite container class for easy dependency injection
class PostgresContainer:
    """Container that provides all PostgreSQL repository implementations."""

    def __init__(self):
        self.user_repo = PostgresUserRepository()
        self.session_repo = PostgresSessionRepository()
        self.email_token_repo = PostgresEmailTokenRepository()
        self.consent_repo = PostgresConsentRepository()
        self.capture_repo = PostgresCaptureRepository()
        self.knowledge_repo = PostgresKnowledgeRepository()
        self.entity_repo = PostgresEntityRepository()
        self.rel_repo = PostgresRelationshipRepository()
        self.duplicate_repo = PostgresDuplicateRepository()
        self.tombstone_repo = PostgresTombstoneRepository()
        self.support_repo = PostgresSupportRepository()
        self.relationship_type_repo = PostgresRelationshipTypeRegistry()
        self.job_repo = PostgresJobRepository()
        self.embedding_repo = PostgresEmbeddingRepository()
        self.eval_repo = PostgresEvalRecordRepository()
        self.audit_repo = PostgresAdminAuditLogRepository()
        self.llm_usage_repo = PostgresLLMUsageRepository()
        self.app_settings_repo = PostgresAppSettingsRepository()