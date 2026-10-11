"""Administrative account management with last-active-admin protection."""
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def _audit(db: Session, actor: User, action: str, target: Optional[User],
           outcome: str, reason: Optional[str]) -> None:
    db.add(AuditEvent(
        actor_user_id=actor.id,
        action=action,
        target_user_id=target.id if target else None,
        outcome=outcome,
        reason=reason,
        metadata_payload={},
    ))



def _admin_lock(db: Session) -> None:
    """Serialize all administrative role/status mutations process-wide.

    ponytail: a single pg_advisory transaction lock. SELECT ... FOR UPDATE on the
    admin set does NOT fix the race, because two concurrent transactions can both
    scan the set before either commits and both see count=2. A fixed advisory lock
    makes the count-and-mutate atomic with respect to every other admin request.
    Upgrade path: per-account advisory locks if admin mutations ever contend.
    """
    from sqlalchemy import text

    db.execute(text("SELECT pg_advisory_xact_lock(1)"))


def change_role(db: Session, actor: User, target_id: str, role: str,
                reason: Optional[str]) -> User:
    """Assign/revokes role. Concurrency-safe last-active-admin guard inside one txn."""
    target = db.execute(
        select(User).where(User.id == target_id).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if role == "admin" and target.role == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="User is already an administrator")
    if role == "user" and target.role == "admin":
        # Last-active-administrator invariant, checked first: self-demotion included.
        _admin_lock(db)
        admins = db.execute(
            select(User).where(User.role == "admin", User.status == "active")
        ).scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Cannot demote the last active administrator")

    old = target.role
    target.role = role
    target.updated_at = datetime.now(timezone.utc)
    _audit(db, actor, "user.role_changed", target, "success", reason or "")
    db.flush()
    return target


def change_status(db: Session, actor: User, target_id: str, new_status: str,
                  reason: Optional[str]) -> User:
    target = db.execute(
        select(User).where(User.id == target_id).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if new_status == "disabled" and target.role == "admin" and target.status == "active":
        # Last-active-administrator invariant, checked first: self-disable included.
        _admin_lock(db)
        admins = db.execute(
            select(User).where(User.role == "admin", User.status == "active")
        ).scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Cannot disable the last active administrator")
    if new_status == "disabled" and actor.id == target_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot disable your own account")

    target.status = new_status
    target.updated_at = datetime.now(timezone.utc)
    action = "user.disabled" if new_status == "disabled" else "user.reactivated"
    _audit(db, actor, action, target, "success", reason or "")
    db.flush()
    return target


def list_users(db: Session, actor: User) -> list[User]:
    return list(db.execute(select(User).order_by(User.username)).scalars().all())


def list_audit(db: Session, actor: User, limit: int = 50) -> list[AuditEvent]:
    return list(db.execute(select(AuditEvent).order_by(AuditEvent.created_at.desc())
                           .limit(limit)).scalars().all())


def create_user(db: Session, actor: User, username: str, password: str,
                display_name: Optional[str] = None) -> User:
    from app.auth import hash_password

    existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role="user",
        status="active",
    )
    db.add(user)
    db.flush()
    _audit(db, actor, "user.created", user, "success", "Admin-created account")
    return user


def seed_initial_admin(db: Session) -> Optional[User]:
    """Idempotent: only seeds when no users exist. Ponytail: one-shot setup hook."""
    from app.config import ADMIN_SEED_USERNAME, ADMIN_SEED_PASSWORD, ADMIN_SEED_EMAIL
    from app.auth import hash_password

    if db.execute(select(User).limit(1)).scalar_one_or_none() is not None:
        return None
    admin = User(
        username=ADMIN_SEED_USERNAME,
        password_hash=hash_password(ADMIN_SEED_PASSWORD),
        display_name=ADMIN_SEED_EMAIL,
        role="admin",
        status="active",
    )
    db.add(admin)
    db.commit()
    return admin
