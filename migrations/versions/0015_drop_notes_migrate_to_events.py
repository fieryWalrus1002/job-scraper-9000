"""Backfill notes → events, then drop the notes column

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-24

Issue #413: every non-empty notes value becomes a 'event' (kind='event') row
in application_events, timestamped at the application's updated_at (NOT now()
— otherwise every migrated note would dominate the latest-activity column).
After the backfill, the notes column is dropped and all API/UI references are
removed. The activity timeline is now the only narrative path.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill: each non-empty notes value becomes a note event, timestamped
    # at the application's updated_at (NOT now() — otherwise every migrated note
    # would dominate the latest-activity column).
    op.execute("""
        INSERT INTO app.application_events (user_id, dedup_hash, kind, body, occurred_at)
        SELECT user_id, dedup_hash, 'event', notes, updated_at
        FROM app.user_applications
        WHERE notes IS NOT NULL AND btrim(notes) <> ''
    """)
    op.execute("ALTER TABLE app.user_applications DROP COLUMN IF EXISTS notes")


def downgrade() -> None:
    op.execute("ALTER TABLE app.user_applications ADD COLUMN IF NOT EXISTS notes TEXT")
    # (no attempt to reconstruct notes from events — one-way data migration)
