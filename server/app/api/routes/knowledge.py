"""Routes: self-registration (F2), extraction (F4/F5), review."""
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import Note, ReviewItem, User
from app.ports.extraction import StubExtractor
from app.extraction_service import run_extraction
from app.review_service import accept_review, reject_review
from app.schemas import NoteOut

router = APIRouter(tags=["knowledge"])
extractor = StubExtractor()  # ponytail: deterministic, no model loaded


@router.post("/auth/register", response_model=dict)
def register(
    username: str = Body(..., embed=True),
    password: str = Body(..., embed=True),
):
    """F2: public self-registration → user role only. Admins use /admin/users."""
    from app.auth import hash_password

    db = next(get_db())
    try:
        if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")
        user = User(username=username, password_hash=hash_password(password),
                    role="user", status="active")
        db.add(user)
        db.commit()
        return {"id": user.id, "role": user.role}
    finally:
        db.close()


@router.post("/notes/{note_id}/extract", response_model=dict)
def post_extract(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """F4/F5: run the local extractor on a note → knowledge or review queue."""
    note = db.execute(
        select(Note).where(Note.id == note_id, Note.user_id == user.id)
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    run = run_extraction(db, user, note, extractor)
    db.flush()
    review_count = db.execute(
        select(ReviewItem).where(ReviewItem.extraction_run_id == run.id)
    ).scalars().all()
    return {"run_id": run.id, "status": run.status, "review_items": len(review_count)}


@router.get("/notes/{note_id}/proposals", response_model=list[dict])
def get_proposals(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = db.execute(
        select(Note).where(Note.id == note_id, Note.user_id == user.id)
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    items = db.execute(
        select(ReviewItem).where(ReviewItem.note_id == note_id, ReviewItem.user_id == user.id)
    ).scalars().all()
    return [{"id": i.id, "item_type": i.item_type, "status": i.status,
             "proposed_json": i.proposed_json} for i in items]


@router.post("/review-items/{review_id}/accept", response_model=dict)
def accept(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return accept_review(db, user, review_id)


@router.post("/review-items/{review_id}/reject", response_model=dict)
def reject(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reject_review(db, user, review_id)
