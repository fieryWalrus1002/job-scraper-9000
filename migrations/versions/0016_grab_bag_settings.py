"""grab_bag_settings

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-25

Issue #421: per-user grab-bag settings for seeded weighted-by-fit sampling.
Two integer columns on app.user_search_configs: grab_bag_size (batch size,
default 20) and grab_bag_score_floor (minimum fit_score, default 3).
Typed columns — not jsonb — since the grab-bag query branches on them.

Defaults: grab_bag_size=20, grab_bag_score_floor=3.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS grab_bag_size INTEGER NOT NULL DEFAULT 20
    """)
    op.execute("""
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS grab_bag_score_floor INTEGER NOT NULL DEFAULT 3
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS grab_bag_size"
    )
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS grab_bag_score_floor"
    )
