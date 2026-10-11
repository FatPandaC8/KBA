"""Note CRUD with idempotency and ownership enforcement."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MAX_NOTE_LENGTH
from app.models import Note, User


def create_note(db: Session, user: User, content: str,
                idempotency_key: Optional[str]) -> Note:
    if not content or len(content) > MAX_NOTE_LENGTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="content is required and within the size limit")
    if idempotency_key:
        existing = db.execute(
            select(Note).where(
                Note.user_id == user.id, Note.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing:
            return existing
    note = Note(user_id=user.id, content=content, capture_type="text", status="active",
               idempotency_key=idempotency_key)
    db.add(note)
    db.flush()
    return note


def list_notes(db: Session, user: User) -> list[Note]:
    return list(db.execute(
        select(Note).where(Note.user_id == user.id, Note.status == "active")
        .order_by(Note.created_at.desc())
    ).scalars().all())


def get_note(db: Session, user: User, note_id: str) -> Note:
    note = db.execute(
        select(Note).where(Note.id == note_id, Note.user_id == user.id)
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


def update_note(db: Session, user: User, note_id: str, content: str) -> Note:
    note = get_note(db, user, note_id)
    if not content or len(content) > MAX_NOTE_LENGTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid content")
    note.content = content
    note.content_version = note.content_version + 1
    note.updated_at = datetime.now(timezone.utc)
    return note


def delete_note(db: Session, user: User, note_id: str) -> None:
    note = get_note(db, user, note_id)
    note.status = "deleted"
    note.deleted_at = datetime.now(timezone.utc)
    note.updated_at = datetime.now(timezone.utc)
