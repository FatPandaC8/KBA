"""Review service: accept a proposal into knowledge, or reject it."""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entity, Fact, Relationship, ReviewItem, User
from app.ports.extraction import FactProposal, RelationshipProposal


def _resolve(db, user, mention, canonical, etype, now):
    existing = db.execute(
        select(Entity).where(
            Entity.user_id == user.id,
            Entity.canonical_name == canonical,
            Entity.entity_type == etype,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    ent = Entity(user_id=user.id, canonical_name=canonical, entity_type=etype,
                 aliases=[], status="active", created_at=now, updated_at=now)
    db.add(ent)
    db.flush()
    return ent


def accept_review(db: Session, user: User, review_id: str) -> dict:
    item = db.execute(
        select(ReviewItem).where(
            ReviewItem.id == review_id, ReviewItem.user_id == user.id
        )
    ).scalar_one_or_none()
    if item is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")
    if item.status != "pending":
        return {"id": item.id, "status": item.status}

    now = datetime.now(timezone.utc)
    kind = item.item_type

    if kind == "entity":
        p = item.proposed_json
        _resolve(db, user, p["mention"], p["canonical_name"], p["entity_type"], now)
    elif kind == "fact":
        p = item.proposed_json
        subj = _resolve(db, user, p["subject_mention"], p["subject_mention"], "other", now)
        obj = None
        if p.get("value_type") == "entity" and p.get("object_mention"):
            obj = _resolve(db, user, p["object_mention"], p["object_mention"], "other", now)
        db.add(Fact(
            user_id=user.id, subject_entity_id=subj.id, predicate=p["predicate"],
            object_entity_id=obj.id if obj else None,
            value_text=None if obj else p.get("value_text"),
            value_type=p.get("value_type"), qualifiers={}, assertion_type="explicit",
            confidence=p.get("confidence", 0.5), created_at=now, updated_at=now,
        ))
    elif kind == "relationship":
        p = item.proposed_json
        src = _resolve(db, user, p["source_mention"], p["source_mention"], "other", now)
        tgt = _resolve(db, user, p["target_mention"], p["target_mention"], "other", now)
        db.add(Relationship(
            user_id=user.id, source_entity_id=src.id, target_entity_id=tgt.id,
            predicate=p["predicate"], qualifiers={}, assertion_type="explicit",
            confidence=p.get("confidence", 0.5), created_at=now, updated_at=now,
        ))

    item.status = "accepted"
    item.reviewed_at = now
    item.updated_at = now
    return {"id": item.id, "status": item.status, "item_type": item.item_type}


def reject_review(db: Session, user: User, review_id: str) -> dict:
    item = db.execute(
        select(ReviewItem).where(
            ReviewItem.id == review_id, ReviewItem.user_id == user.id
        )
    ).scalar_one_or_none()
    if item is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")
    item.status = "rejected"
    item.reviewed_at = datetime.now(timezone.utc)
    item.updated_at = item.reviewed_at
    return {"id": item.id, "status": item.status, "item_type": item.item_type}
