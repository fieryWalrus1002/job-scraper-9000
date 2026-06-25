"""grab_bag_max_age_days

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-25

Issue #432: per-user grab-bag max-age window setting. One nullable integer
column on app.user_search_configs: grab_bag_max_age_days (relative window —
"only include postings from the last N days"; NULL = no age limit).
Typed column — not jsonb — since the grab-bag query branches on it.

Nullable (no default): NULL means "no age limit".
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.user_search_configs
            ADD COLUMN IF NOT EXISTS grab_bag_max_age_days INTEGER
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_search_configs DROP COLUMN IF EXISTS grab_bag_max_age_days"
    )
