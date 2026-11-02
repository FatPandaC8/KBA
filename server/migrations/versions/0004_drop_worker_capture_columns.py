"""Pipeline split (S2): drop the worker-era capture columns.

``stage``, ``error_class``, ``error_message`` and ``retry_count`` existed only
for the worker/job model. Capture truth is now: status + last_error
(written by /api/text-kb on ingest failure, rule 5).
"""

import sys
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parents[2]  # server/
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

# revision identifiers
revision = "0004_drop_worker_capture_columns"
down_revision = "0003_drop_processing_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op = __import__("alembic").op
    op.execute(
        "ALTER TABLE captures "
        "DROP COLUMN IF EXISTS stage, "
        "DROP COLUMN IF EXISTS error_class, "
        "DROP COLUMN IF EXISTS error_message, "
        "DROP COLUMN IF EXISTS retry_count"
    )


def downgrade() -> None:
    op = __import__("alembic").op
    op.execute(
        "ALTER TABLE captures "
        "ADD COLUMN IF NOT EXISTS stage text NOT NULL DEFAULT 'uploaded', "
        "ADD COLUMN IF NOT EXISTS error_class text, "
        "ADD COLUMN IF NOT EXISTS error_message text, "
        "ADD COLUMN IF NOT EXISTS retry_count integer NOT NULL DEFAULT 0"
    )
