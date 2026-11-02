"""Pipeline split (rule 5 default): keep the last ingest error on captures.

The worker/job model is being removed; admin needs "which captures failed and
why" without job rows, so /api/text-kb writes last_error/last_error_at in a
separate small transaction after the ingest UoW rolled back.
"""

import sys
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parents[2]  # server/
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

# revision identifiers
revision = "0002_capture_last_error"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op_add = __import__("alembic").op
    op_add.execute(
        "ALTER TABLE captures "
        "ADD COLUMN IF NOT EXISTS last_error text NULL, "
        "ADD COLUMN IF NOT EXISTS last_error_at timestamptz NULL"
    )


def downgrade() -> None:
    op_drop = __import__("alembic").op
    op_drop.execute(
        "ALTER TABLE captures DROP COLUMN IF EXISTS last_error, "
        "DROP COLUMN IF EXISTS last_error_at"
    )
