"""Sessions and auth tokens (email tokens + consents)."""

import json
import uuid
from typing import Optional

from server.app.domain.entities import ConsentEntity, EmailTokenEntity, SessionEntity, UserEntity

from .conn import Database, transaction
from .users import _row_to_user


class PostgresSessionRepository:
    """Sessions. Touch is one conditional statement (R6): fresh sessions
    cause no write; stale ones gain a new last_used_at once per minute."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, user_id: str, token_hash: str, expires_at: str) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, last_used_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    uuid.UUID(user_id),
                    token_hash,
                    _utcnow_iso(),
                    _utcnow_iso(),
                    expires_at,
                ),
            )

    def get_user_by_token_hash(self, token_hash: str) -> Optional[UserEntity]:
        with transaction(self.db) as conn:
            row = conn.execute(
                """
                SELECT u.*, s.expires_at AS session_expires_at, s.revoked_at AS session_revoked_at
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > NOW()
                """,
                (token_hash,),
            ).fetchone()
            return _row_to_user(row) if row else None

    def touch(self, token_hash: str) -> None:
        # One conditional statement; a fresh session matches zero rows and no
        # write lock is held beyond the statement (no-op result).
        with transaction(self.db) as conn:
            conn.execute(
                """
                UPDATE sessions SET last_used_at = NOW()
                WHERE token_hash = %s
                  AND (last_used_at IS NULL
                       OR last_used_at < NOW() - INTERVAL '60 seconds')
                """,
                (token_hash,),
            )

    def revoke(self, token_hash: str) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = NOW() "
                "WHERE token_hash = %s AND revoked_at IS NULL",
                (token_hash,),
            )

    def revoke_all_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked_at = NOW() "
                "WHERE user_id = %s AND revoked_at IS NULL",
                (uuid.UUID(user_id),),
            )
            return cur.rowcount

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            return cur.rowcount


class PostgresEmailTokenRepository:
    """Email verification / reset tokens."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, user_id: str, purpose: str, token_hash: str, expires_at: str) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO email_tokens (id, token_hash, user_id, purpose, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                (uuid.uuid4(), token_hash, uuid.UUID(user_id), purpose, expires_at, _utcnow_iso()),
            )

    def consume(self, token_hash: str, purpose: str) -> Optional[str]:
        """Atomically mark the token used and return its user id."""
        with transaction(self.db) as conn:
            row = conn.execute(
                """
                UPDATE email_tokens SET consumed_at = NOW()
                WHERE token_hash = %s AND purpose = %s
                  AND consumed_at IS NULL AND expires_at > NOW()
                RETURNING user_id
                """,
                (token_hash, purpose),
            ).fetchone()
            return str(row["user_id"]) if row else None

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM email_tokens WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            return cur.rowcount


class PostgresConsentRepository:
    """Consent records, latest first (no UNIQUE(user_id): consent has history)."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, consent: ConsentEntity) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                INSERT INTO consents (id, user_id, version, providers_hash,
                    providers_json, granted, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.UUID(consent.id),
                    uuid.UUID(consent.user_id),
                    consent.version,
                    consent.providers_hash,
                    json.dumps(consent.providers or []),
                    consent.granted,
                    consent.created_at,
                ),
            )

    def get_latest(self, user_id: str) -> Optional[ConsentEntity]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT * FROM consents WHERE user_id = %s "
                "ORDER BY created_at DESC, id LIMIT 1",
                (uuid.UUID(user_id),),
            ).fetchone()
            return _row_to_consent(row) if row else None

    def delete_for_user(self, user_id: str) -> int:
        with transaction(self.db) as conn:
            cur = conn.execute(
                "DELETE FROM consents WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            return cur.rowcount


from datetime import datetime, timezone  # noqa: E402


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_consent(r) -> ConsentEntity:
    providers = r["providers_json"]
    return ConsentEntity(
        id=str(r["id"]),
        user_id=str(r["user_id"]),
        version=r["version"],
        providers_hash=r["providers_hash"],
        providers=json.loads(providers) if isinstance(providers, str) else (providers or []),
        granted=r["granted"],
        created_at=r["created_at"].isoformat() if r["created_at"] else None,
    )
