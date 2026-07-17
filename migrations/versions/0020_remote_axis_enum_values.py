"""remote_axis_enum_values

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-17

Extend raw.remote_classification for the 4-way taxonomy in
specs/remote_filter_taxonomy.md while keeping legacy enum members so
historical rows remain readable/validatable. Postgres enum values cannot be
removed on downgrade, so this migration is additive only.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE raw.remote_classification ADD VALUE IF NOT EXISTS 'remote'")
    op.execute("ALTER TYPE raw.remote_classification ADD VALUE IF NOT EXISTS 'onsite'")


def downgrade() -> None:
    # Postgres cannot DROP an enum value; downgrade is intentionally a no-op.
    pass
