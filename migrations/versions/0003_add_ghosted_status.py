"""add_ghosted_status

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_STATUSES = (
    "saved",
    "maybe",
    "to_apply",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "hired",
)
_NEW_STATUSES = _OLD_STATUSES + ("ghosted",)


def _status_check(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{s}'" for s in statuses)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_applications DROP CONSTRAINT IF EXISTS user_applications_status_check"
    )
    op.execute(f"""
        ALTER TABLE app.user_applications
            ADD CONSTRAINT user_applications_status_check
            CHECK (status IN ({_status_check(_NEW_STATUSES)}))
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.user_applications DROP CONSTRAINT IF EXISTS user_applications_status_check"
    )
    op.execute(f"""
        ALTER TABLE app.user_applications
            ADD CONSTRAINT user_applications_status_check
            CHECK (status IN ({_status_check(_OLD_STATUSES)}))
    """)
