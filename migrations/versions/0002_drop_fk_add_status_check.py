"""drop_fk_add_status_check

Decouple app schema from raw schema lifecycle by removing the FK to
raw.scored_job_postings, and enforce valid status values at the DB level.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02 20:45:55.016259

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID_STATUSES = (
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
_STATUS_LIST = ", ".join(f"'{s}'" for s in _VALID_STATUSES)


def upgrade() -> None:
    # Remove FK so app schema has no hard dependency on raw schema.
    op.execute("""
        ALTER TABLE app.user_applications
            DROP CONSTRAINT IF EXISTS user_applications_dedup_hash_fkey
    """)
    # Enforce valid statuses at the DB level.
    op.execute(f"""
        ALTER TABLE app.user_applications
            ADD CONSTRAINT user_applications_status_check
            CHECK (status IN ({_STATUS_LIST}))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE app.user_applications
            DROP CONSTRAINT IF EXISTS user_applications_status_check
    """)
    op.execute("""
        ALTER TABLE app.user_applications
            ADD CONSTRAINT user_applications_dedup_hash_fkey
            FOREIGN KEY (dedup_hash)
            REFERENCES raw.scored_job_postings(dedup_hash)
            ON DELETE CASCADE
    """)
