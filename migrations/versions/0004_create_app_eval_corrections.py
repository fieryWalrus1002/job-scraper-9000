"""create_app_eval_corrections

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03

Adds app.eval_corrections — dashboard-sourced human corrections to skills_fit
scores. Feeds the gold set for eval-harness comparison alongside the sampled
proposal flow (scripts/propose_skills_fit_seed.py).

One row per dedup_hash, last-write-wins. Snapshots (original_score, model,
profile_version) at correction time so corrections stay interpretable when
the underlying score is re-run with a different model or profile.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.eval_corrections (
            dedup_hash         TEXT        PRIMARY KEY
                                   REFERENCES raw.scored_job_postings(dedup_hash)
                                   ON DELETE CASCADE,
            corrected_score    INT         NOT NULL
                                   CHECK (corrected_score BETWEEN 1 AND 5),
            correction_reason  TEXT,
            original_score     INT,
            original_model     TEXT        NOT NULL,
            profile_version    TEXT        NOT NULL,
            corrected_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eval_corrections_model_profile
            ON app.eval_corrections (original_model, profile_version)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.idx_eval_corrections_model_profile")
    op.execute("DROP TABLE IF EXISTS app.eval_corrections")
