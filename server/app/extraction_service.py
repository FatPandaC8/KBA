"""Extraction service: run the extractor, validate, persist or queue for review."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import EXTRACTION_AUTO_SAVE_CONFIDENCE, MAX_NOTE_LENGTH
from app.models import (
    Entity,
    Evidence,
    ExtractionRun,
    Fact,
    Note,
    Relationship,
    ReviewItem,
    User,
)
from app.ports.extraction import ExtractionOutput, KnowledgeExtractor


def _utf16_slice(content: str, start: int, end: int) -> str:
    # Ponytail: Python 3 str indexing is code units (BMP safe); convert offsets.
    chars = content.encode("utf-16-le")
    start_c = start * 2
    end_c = end * 2 if end <= len(content) else len(chars) // 2 * 2
    return content[start:end]


def _resolve_entity(db: Session, user: User, mention: str, canonical_name: str,
                    entity_type: str, now: datetime) -> Entity:
    """Reuse an existing entity matching canonical_name + type for this user."""
    existing = db.execute(
        select(Entity).where(
            Entity.user_id == user.id,
            Entity.canonical_name == canonical_name,
            Entity.entity_type == entity_type,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    return Entity(
        user_id=user.id, canonical_name=canonical_name, entity_type=entity_type,
        aliases=[], status="active", created_at=now, updated_at=now,
    )


def run_extraction(
    db: Session, user: User, note: Note, extractor: KnowledgeExtractor
) -> ExtractionRun:
    """Execute extraction on a note. Auto-persists qualifying assertions; queues the rest."""
    output: ExtractionOutput = extractor.extract(note.content)
    run = ExtractionRun(
        user_id=user.id, note_id=note.id, source_content_version=note.content_version,
        model_name=output.model, prompt_version=output.prompt_version,
        status="succeeded", started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc), output_json=output.model_dump(exclude_none=True),
    )
    db.add(run)
    db.flush()

    now = datetime.now(timezone.utc)
    entities: dict[str, Entity] = {}

    for ep in output.entities:
        # Resolve/merge by canonical name within the user's graph.
        ent = _resolve_entity(db, user, ep.mention, ep.canonical_name, ep.entity_type, now)
        db.add(ent)
        db.flush()
        entities[ep.canonical_name] = ent

    # Auto-save high-confidence EXPLICIT assertions with valid evidence.
    for rp in output.relationships:
        if (rp.assertion_type == "explicit"
                and rp.confidence >= EXTRACTION_AUTO_SAVE_CONFIDENCE
                and (ev := _validate_evidence(db, user, note, rp.evidence, now))):
            src = entities.get(rp.source_mention)
            tgt = entities.get(rp.target_mention)
            if src and tgt:
                rel = Relationship(
                    user_id=user.id, source_entity_id=src.id, target_entity_id=tgt.id,
                    predicate=rp.predicate, qualifiers={}, assertion_type="explicit",
                    confidence=rp.confidence, created_at=now, updated_at=now,
                )
                db.add(rel)
                db.flush()
                _link_evidence(db, rel.id, ev, "relationships")
        else:
            _queue_review(db, user, note, run, "relationship", rp.model_dump(exclude_none=True), now)

    for ep in output.entities:
        pass  # entities reused/resolved above are already persisted

    for fp in output.facts:
        if (fp.assertion_type == "explicit"
                and fp.confidence >= EXTRACTION_AUTO_SAVE_CONFIDENCE
                and (ev := _validate_evidence(db, user, note, fp.evidence, now))):
            subj = entities.get(fp.subject_mention)
            if not subj:
                continue
            obj = _resolve_entity(db, user, fp.object_mention or "", fp.object_mention or "",
                                  "other", now) if fp.value_type == "entity" and fp.object_mention else None
            db.add(Fact(
                user_id=user.id, subject_entity_id=subj.id, predicate=fp.predicate,
                object_entity_id=obj.id if obj else None,
                value_text=None if obj else fp.value_text,
                value_type=fp.value_type, qualifiers={}, assertion_type="explicit",
                confidence=fp.confidence, created_at=now, updated_at=now,
            ))
        else:
            _queue_review(db, user, note, run, "fact", fp.model_dump(exclude_none=True), now)

    return run


def _validate_evidence(db, user, note, spans, now) -> Optional[Evidence]:
    """Keep one validated Evidence row; drop invalid spans."""
    for sp in spans:
        start = sp.note_offset
        end = sp.note_offset + sp.note_length
        if start < 0 or end < start:
            return None
        decoded = _utf16_slice(note.content, start, end)
        if decoded != sp.quoted_text:
            continue  # skip invalid spans, keep first valid one
        ev = db.execute(
            select(Evidence).where(
                Evidence.user_id == user.id, Evidence.note_id == note.id,
                Evidence.start_offset == start,
                Evidence.end_offset == end,
                Evidence.quoted_text == sp.quoted_text,
            )
        ).scalar_one_or_none()
        if not ev:
            ev = Evidence(
                user_id=user.id, note_id=note.id, start_offset=start,
                end_offset=end, quoted_text=sp.quoted_text, created_at=now,
            )
            db.add(ev)
            db.flush()
        return ev
    return None


def _link_evidence(db, target_id, evidence, kind):
    if kind == "relationships":
        from app.models import RelationshipEvidence
        db.add(RelationshipEvidence(relationship_id=target_id, evidence_id=evidence.id,
                                    created_at=datetime.now(timezone.utc)))
    else:
        from app.models import FactEvidence
        db.add(FactEvidence(fact_id=target_id, evidence_id=evidence.id,
                            created_at=datetime.now(timezone.utc)))


def _queue_review(db, user, note, run, item_type, proposed, now):
    db.add(ReviewItem(
        user_id=user.id, note_id=note.id, extraction_run_id=run.id,
        item_type=item_type, proposed_json=proposed, status="pending",
        created_at=now, updated_at=now,
    ))
