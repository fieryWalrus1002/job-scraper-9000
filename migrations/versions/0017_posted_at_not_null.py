"""posted_at_not_null

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-25

Issue #431: backfill NULL posted_at values and enforce NOT NULL.

Backfill chain: posted_at ← COALESCE(posted_at, scraped_at::date,
ingested_at::date). Because scraped_at is also nullable (pipeline scrapes
can lack it), fall through to ingested_at (NOT NULL DEFAULT now()) so the
UPDATE never leaves a row NULL before the constraint is applied.

This is the DB backstop behind the app-layer fallback from #434. The app
layer handles live writes; this migration cleans historical data and makes
the invariant enforceable at the DB so a future stray writer fails loud
instead of inserting a NULL.

Downgrade drops the NOT NULL constraint. The backfilled values are *not*
reverted — they are best-effort approximations that are correct for
scraped jobs.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE raw.job_postings
        SET posted_at = COALESCE(posted_at, scraped_at::date, ingested_at::date)
        WHERE posted_at IS NULL
    """)
    op.execute("""
        ALTER TABLE raw.job_postings
            ALTER COLUMN posted_at SET NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE raw.job_postings
            ALTER COLUMN posted_at DROP NOT NULL
    """)
