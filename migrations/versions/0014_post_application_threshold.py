"""post_application_nudge_days threshold

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-24

Issue #404a: add post_application_nudge_days (default 10) as a per-user alert
threshold setting. Stores and serves the value; the rule that consumes it is
#404b. Clones the pattern from migration 0013 (three existing thresholds).
Typed column — not jsonb — since the rules engine branches on it load-bearing.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS post_application_nudge_days INTEGER NOT NULL DEFAULT 10
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS post_application_nudge_days"
    )
