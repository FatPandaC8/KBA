"""Pipeline split (S2): drop the processing_jobs table.

The worker, the queue and all retry/lease state are deleted with the split;
the two synchronous APIs (POST /api/stt, POST /api/text-kb) own no job rows.
The baseline keeps its historical shape (new deployments only need the final
state, which this migration produces).
"""

import sys
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parents[2]  # server/
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

# revision identifiers
revision = "0003_drop_processing_jobs"
down_revision = "0002_capture_last_error"
branch_labels = None
depends_on = None


def upgrade() -> None:
    alembic_op = __import__("alembic").op
    alembic_op.execute(
        "DROP TABLE IF EXISTS processing_jobs CASCADE"
    )
    alembic_op.execute(
        "DROP INDEX IF EXISTS idx_processing_jobs_status_claim;"
        "DROP INDEX IF EXISTS idx_processing_jobs_capture;"
        "DROP INDEX IF EXISTS idx_processing_jobs_user_created;"
        "DROP INDEX IF EXISTS idx_processing_jobs_lease"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "processing_jobs is gone for good (S2); restore from the baseline if you must."
    )
