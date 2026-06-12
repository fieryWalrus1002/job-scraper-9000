"""pipeline_queue

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-12

Phase 13 (specs/multi_user_pipeline_orchestration.md §5): DB-table queue for
the multi-user overnight pipeline.

- pipe.scrape_jobs — one row per (run_id, user_id, source). The worker claims
  pending rows via FOR UPDATE SKIP LOCKED with source-serialization built
  into the claim query (≤1 in-flight per source globally, spec §6). UNIQUE
  (run_id, user_id, source) makes enqueue idempotent across re-runs.
- pipe.consolidated_postings — fan-in state for the shared remote_filter
  classification phase. ``requested_by`` (UUID[]) holds the users whose feeds
  should receive the posting if it survives the downstream per-user policies.

New schema ``pipe`` (pipeline orchestration), separate from ``app`` (user
data) and ``raw`` (postings/scores). Additive — no backfill.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS pipe")
    op.execute("""
        CREATE TABLE IF NOT EXISTS pipe.scrape_jobs (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id          TEXT        NOT NULL,
            user_id         UUID        NOT NULL REFERENCES app.users(id),
            source          TEXT        NOT NULL,
            query_payload   JSONB       NOT NULL,
            status          TEXT        NOT NULL DEFAULT 'pending'
                                        CHECK (status IN ('pending','running','succeeded','failed')),
            attempts        INT         NOT NULL DEFAULT 0,
            error           TEXT,
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            posting_count   INT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (run_id, user_id, source)
        )
    """)
    # Partial index keeps the planner happy when the queue grows large and
    # most rows are 'succeeded'/'failed' — the worker only ever asks about the
    # active subset.
    op.execute("""
        CREATE INDEX IF NOT EXISTS scrape_jobs_active_idx
            ON pipe.scrape_jobs (status)
            WHERE status IN ('pending','running')
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS scrape_jobs_run_idx
            ON pipe.scrape_jobs (run_id)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS pipe.consolidated_postings (
            run_id          TEXT        NOT NULL,
            dedup_hash      TEXT        NOT NULL,
            requested_by    UUID[]      NOT NULL,
            posting_ref     TEXT,
            PRIMARY KEY (run_id, dedup_hash)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pipe.consolidated_postings")
    op.execute("DROP TABLE IF EXISTS pipe.scrape_jobs")
    op.execute("DROP SCHEMA IF EXISTS pipe")
