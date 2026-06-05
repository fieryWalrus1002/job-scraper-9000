"""create_app_user_applications

Revision ID: 0001
Revises:
Create Date: 2026-06-02 20:03:49.576181

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.user_applications (
            dedup_hash   TEXT        PRIMARY KEY,
            status       TEXT        NOT NULL DEFAULT 'saved',
            applied_at   DATE,
            notes        TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_applications_status
            ON app.user_applications (status)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.idx_user_applications_status")
    op.execute("DROP TABLE IF EXISTS app.user_applications")
