"""pipeline_enabled_flag

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-15

Issue #245: per-user gate so dormant / test accounts stop burning scrape + LLM
spend on every overnight run. Without this the only way to stop a user's run is
to delete their search config, which destroys their settings.

The flag lives on app.user_search_configs (decision in #245): "should the
overnight run for me" is a pipeline setting, not an identity attribute — an
account can exist and log in without overnight runs. ``DEFAULT true`` so every
existing user is unaffected; flip to false to deactivate. The planner gates on
it and reports skipped users in its run summary.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS pipeline_enabled BOOLEAN NOT NULL DEFAULT true
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS pipeline_enabled"
    )
