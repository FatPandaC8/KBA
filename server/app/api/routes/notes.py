"""Notes routes."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import User
from app.notes_service import create_note, delete_note, get_note, list_notes, update_note
from app.schemas import NoteIn, NoteOut, NotePatchIn

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def post_note(body: NoteIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    return create_note(db, user, body.content, body.idempotency_key)


@router.get("", response_model=list[NoteOut])
def get_notes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list_notes(db, user)


@router.get("/{note_id}", response_model=NoteOut)
def get_one(note_id: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return get_note(db, user, note_id)


@router.patch("/{note_id}", response_model=NoteOut)
def patch_note(note_id: str, body: NotePatchIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    return update_note(db, user, note_id, body.content)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_one(note_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    delete_note(db, user, note_id)
