"""SQLAlchemy models for the knowledge graph."""


import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="users_role_check"),
        CheckConstraint("status IN ('active', 'disabled')", name="users_status_check"),
    )

    notes: Mapped[list["Note"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    entities: Mapped[list["Entity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="actor", foreign_keys="AuditEvent.actor_user_id"
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    capture_type: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("capture_type IN ('text', 'voice')", name="notes_capture_type_check"),
        CheckConstraint("status IN ('active', 'deleted')", name="notes_status_check")
    )

    user: Mapped["User"] = relationship(back_populates="notes")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="note", cascade="all, delete-orphan")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )
    review_items: Mapped[list["ReviewItem"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('person', 'organization', 'place', 'concept', 'other')",
            name="entities_entity_type_check",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="entities_status_check"),
    )

    user: Mapped["User"] = relationship(back_populates="entities")
    facts_as_subject: Mapped[list["Fact"]] = relationship(
        back_populates="subject_entity", cascade="all, delete-orphan",
        foreign_keys="Fact.subject_entity_id",
    )
    facts_as_object: Mapped[list["Fact"]] = relationship(
        back_populates="object_entity", cascade="all, delete-orphan",
        foreign_keys="Fact.object_entity_id",
    )
    relationships_as_source: Mapped[list["Relationship"]] = relationship(
        back_populates="source_entity", cascade="all, delete-orphan",
        foreign_keys="Relationship.source_entity_id",
    )
    relationships_as_target: Mapped[list["Relationship"]] = relationship(
        back_populates="target_entity", cascade="all, delete-orphan",
        foreign_keys="Relationship.target_entity_id",
    )

class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object_entity_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assertion_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "assertion_type IN ('explicit', 'inferred')", name="facts_assertion_type_check"
        ),
        CheckConstraint(
            "value_type IS NULL OR value_type IN "
            "('entity', 'text', 'number', 'boolean', 'date', 'datetime')",
            name="facts_value_type_check",
        ),
    )

    subject_entity: Mapped["Entity"] = relationship(
        back_populates="facts_as_subject", foreign_keys="Fact.subject_entity_id"
    )
    object_entity: Mapped["Entity | None"] = relationship(
        back_populates="facts_as_object", foreign_keys="Fact.object_entity_id"
    )
    evidence_links: Mapped[list["FactEvidence"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan"
    )


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_entity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    qualifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assertion_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "assertion_type IN ('explicit', 'inferred')",
            name="relationships_assertion_type_check",
        ),
    )

    source_entity: Mapped["Entity"] = relationship(
        back_populates="relationships_as_source", foreign_keys="Relationship.source_entity_id"
    )
    target_entity: Mapped["Entity"] = relationship(
        back_populates="relationships_as_target", foreign_keys="Relationship.target_entity_id"
    )
    evidence_links: Mapped[list["RelationshipEvidence"]] = relationship(
        back_populates="relationship", cascade="all, delete-orphan"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    note_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    __table_args__ = (
        CheckConstraint("start_offset >= 0", name="evidence_start_offset_check"),
        CheckConstraint("end_offset >= start_offset", name="evidence_end_offset_check"),
    )

    note: Mapped["Note"] = relationship(back_populates="evidence")


class FactEvidence(Base):
    __tablename__ = "fact_evidence"

    fact_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("facts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("evidence.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    fact: Mapped["Fact"] = relationship(back_populates="evidence_links")


class RelationshipEvidence(Base):
    __tablename__ = "relationship_evidence"

    relationship_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("relationships.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("evidence.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    relationship: Mapped["Relationship"] = relationship(back_populates="evidence_links")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    note_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    source_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="extraction_runs_status_check",
        ),
    )

    note: Mapped["Note"] = relationship(back_populates="extraction_runs")


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    note_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    extraction_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('entity', 'fact', 'relationship')",
            name="review_items_item_type_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="review_items_status_check",
        )
    )

    note: Mapped["Note"] = relationship(back_populates="review_items")


class AuditEvent(Base):
    __tablename__ = "admin_audit_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    actor_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'failure')", name="audit_outcome_check"),
    )

    actor: Mapped["User"] = relationship(
        back_populates="audit_events", foreign_keys="AuditEvent.actor_user_id"
    )
