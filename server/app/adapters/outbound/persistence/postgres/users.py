"""User aggregate persistence: users."""

import uuid
from typing import Optional

from server.app.domain.entities import UserEntity

from .conn import Database, transaction


class PostgresUserRepository:
    """Users. Self-entity creation is NOT here: see entities.get_or_create_self."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, user: UserEntity) -> None:
        with transaction(self.db) as conn:
            row = conn.execute(
                """
                INSERT INTO users (id, email, email_normalized, password_hash,
                    google_sub, email_verified_at, is_locked, created_at, updated_at)
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
                    user.google_sub,
                    user.email_verified_at,
                    user.is_locked,
                    user.created_at,
                    user.updated_at,
                ),
            ).fetchone()
            user.id = str(row["id"])

    def get_by_id(self, user_id: str) -> Optional[UserEntity]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = %s", (uuid.UUID(user_id),)
            ).fetchone()
            return _row_to_user(row) if row else None

    def get_by_email(self, email_normalized: str) -> Optional[UserEntity]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email_normalized = %s",
                (email_normalized,),
            ).fetchone()
            return _row_to_user(row) if row else None

    def get_by_google_sub(self, google_sub: str) -> Optional[UserEntity]:
        with transaction(self.db) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE google_sub = %s", (google_sub,)
            ).fetchone()
            return _row_to_user(row) if row else None

    def update(self, user: UserEntity) -> None:
        with transaction(self.db) as conn:
            conn.execute(
                """
                UPDATE users SET email = %s, email_normalized = %s,
                    password_hash = %s, google_sub = %s,
                    email_verified_at = %s, is_locked = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (
                    user.email,
                    user.email_normalized,
                    user.password_hash,
                    user.google_sub,
                    user.email_verified_at,
                    user.is_locked,
                    uuid.UUID(user.id),
                ),
            )

    def delete(self, user_id: str) -> None:
        with transaction(self.db) as conn:
            conn.execute("DELETE FROM users WHERE id = %s", (uuid.UUID(user_id),))

    def count(self) -> int:
        with transaction(self.db) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            return row["count"] if row else 0


def _row_to_user(r) -> UserEntity:
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
