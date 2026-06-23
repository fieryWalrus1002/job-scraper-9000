"""alert_threshold_settings

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-23

Issue #386: per-user alert thresholds for Upcoming Steps reminders.
Three integer (days) columns on app.user_search_configs, mirroring the
pipeline_enabled precedent (migration 0011). Typed columns — not jsonb —
since the rules engine (#384) branches on them load-bearing.

Defaults: stale_to_apply_days=3, post_interview_nudge_days=7,
  inactivity_days=14.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS stale_to_apply_days INTEGER NOT NULL DEFAULT 3
    """)
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS post_interview_nudge_days INTEGER NOT NULL DEFAULT 7
    """)
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS inactivity_days INTEGER NOT NULL DEFAULT 14
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS stale_to_apply_days"
    )
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS post_interview_nudge_days"
    )
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS inactivity_days"
    )
