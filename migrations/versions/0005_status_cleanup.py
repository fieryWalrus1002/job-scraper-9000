"""rename_withdrawn_add_passed_drop_saved

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09

Cleanup of application_status:
- 'saved' removed (redundant with 'maybe'); existing rows backfill to 'maybe'.
- 'withdrawn' renamed to 'candidate_withdrew' for subject clarity (the prior
  name was ambiguous: candidate-withdrew vs offer-withdrawn).
- 'passed' added for user-dismissed-at-intake (distinct from any offer-stage
  outcome).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
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
    "ghosted",
)
_NEW_STATUSES = (
    "maybe",
    "to_apply",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "candidate_withdrew",
    "hired",
    "ghosted",
    "passed",
)


def _status_check(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{s}'" for s in statuses)


def upgrade() -> None:
    # Backfill removed/renamed values BEFORE swapping the CHECK constraint,
    # otherwise rows would violate the new constraint at install time.
    op.execute(
        "UPDATE app.user_applications SET status = 'maybe' WHERE status = 'saved'"
    )
    op.execute(
        "UPDATE app.user_applications SET status = 'candidate_withdrew' WHERE status = 'withdrawn'"
    )
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
    # Map both candidate_withdrew and passed back to 'withdrawn' so the old
    # constraint holds. Rows originally 'saved' can't be recovered — they stay
    # 'maybe' on downgrade. Lossy but acceptable for an undo path.
    op.execute(
        "UPDATE app.user_applications SET status = 'withdrawn' "
        "WHERE status IN ('candidate_withdrew', 'passed')"
    )
    op.execute(f"""
        ALTER TABLE app.user_applications
            ADD CONSTRAINT user_applications_status_check
            CHECK (status IN ({_status_check(_OLD_STATUSES)}))
    """)
