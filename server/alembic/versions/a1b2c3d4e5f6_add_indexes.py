"""Add DATA_MODEL 18 indexes for user-scoped listing, FTS, and traversal."""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "62693f485ce3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_notes_user_status", "notes", ["user_id", "status"])
    op.create_index("ix_entities_user_status", "entities", ["user_id", "status"])
    op.create_index("ix_entities_user_name", "entities", ["user_id", "canonical_name"])
    op.create_index("ix_facts_user", "facts", ["user_id", "subject_entity_id"])
    op.create_index("ix_relationships_user", "relationships", ["user_id", "source_entity_id"])
    op.create_index("ix_review_items_user_status", "review_items", ["user_id", "status"])
    op.create_index("ix_extraction_runs_user_note", "extraction_runs", ["user_id", "note_id"])
    op.create_index("ix_evidence_user_note", "evidence", ["user_id", "note_id"])
    op.create_index("ix_audit_actor_time", "admin_audit_events", ["actor_user_id", "created_at"])


def downgrade():
    op.drop_index("ix_audit_actor_time", table_name="admin_audit_events")
    op.drop_index("ix_evidence_user_note", table_name="evidence")
    op.drop_index("ix_extraction_runs_user_note", table_name="extraction_runs")
    op.drop_index("ix_review_items_user_status", table_name="review_items")
    op.drop_index("ix_relationships_user", table_name="relationships")
    op.drop_index("ix_facts_user", table_name="facts")
    op.drop_index("ix_entities_user_name", table_name="entities")
    op.drop_index("ix_entities_user_status", table_name="entities")
    op.drop_index("ix_notes_user_status", table_name="notes")
