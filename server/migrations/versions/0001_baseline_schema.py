"""Alembic baseline: the complete PostgreSQL schema.

Covers every table the persistence adapters read and write, the partial unique
self-entity rule, composite FKs for relationship endpoints, and the
graph-query indexes. Application startup never creates schema; all
environments apply this migration.

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-11-01
"""

import sys
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parents[2]  # server/
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from migrations.baseline import INITIAL_TABLES_SQL, INDEX_SQL, DROP_SQL  # noqa: E402

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(INITIAL_TABLES_SQL)
    op.execute(INDEX_SQL)


def downgrade() -> None:
    op.execute(DROP_SQL)
