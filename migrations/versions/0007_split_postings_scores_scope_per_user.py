"""split_postings_scores_scope_per_user

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-11

The multi-user table split (specs/multi_user_design.md §2):

- raw.scored_job_postings is split into raw.job_postings (shared descriptive
  storage, PK dedup_hash) and raw.job_scores (per-user scoring + run
  provenance, PK (user_id, dedup_hash)). A posting is visible to a user iff
  a score row exists for them.
- app.user_applications and app.eval_corrections gain user_id and re-key to
  (user_id, dedup_hash).

All existing rows are backfilled to the bootstrap admin (the earliest-created
admin in app.users, seeded by 0006). If any data exists and no admin row can
be found, the migration fails fast rather than guessing an owner. Runs under
the migration advisory lock (migrations/env.py), so a rolling deploy cannot
run the backfill twice concurrently.

Downgrade reconstructs raw.scored_job_postings but is lossy once a second
user has score rows: it keeps one score per posting (most recently scored).
"""

import uuid
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POSTING_COLS = """
    dedup_hash, source, source_job_id, source_url,
    title, company, location, posted_at, description, scraped_at,
    remote_classification, salary_min_usd, salary_max_usd, salary_period,
    pipeline_metadata, metadata, ingested_at
"""

_SCORE_COLS = """
    fit_score, confidence, score_rationale, ai_fit_detail,
    run_id, scored_at, model, provider, profile_version, failure_reason
"""


def _resolve_backfill_admin(bind) -> uuid.UUID | None:
    """Earliest-created admin (the 0006 bootstrap seed, unless renamed)."""
    row = bind.execute(
        text(
            "SELECT id FROM app.users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
        )
    ).fetchone()
    return row[0] if row else None


def upgrade() -> None:
    bind = op.get_bind()

    # raw.scored_job_postings was historically created by db/schema.sql (the
    # ingest script's idempotent DDL), not by Alembic — so on a fresh DB the
    # schema, the enum types, and the legacy table may all be absent. From
    # this revision on, Alembic owns the raw tables; schema.sql mirrors them
    # idempotently for the ingest path.
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE raw.remote_classification AS ENUM (
                'fully_remote',
                'remote_with_quarterly_travel',
                'remote_with_monthly_travel',
                'remote_with_frequent_travel',
                'hybrid',
                'onsite_disguised',
                'location_restricted',
                'unclear'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE raw.fit_confidence AS ENUM ('low', 'medium', 'high');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.job_postings (
            -- Shared descriptive storage: one row per posting no matter how
            -- many users' pipeline runs surfaced it.
            dedup_hash              TEXT        PRIMARY KEY,
            source                  TEXT,
            source_job_id           TEXT,
            source_url              TEXT,
            title                   TEXT,
            company                 TEXT,
            location                TEXT,
            posted_at               DATE,
            description             TEXT,
            scraped_at              TIMESTAMPTZ,
            -- Classifies the job itself, not fit against a profile, so it
            -- lives on the shared posting.
            remote_classification   raw.remote_classification,
            salary_min_usd          INTEGER,
            salary_max_usd          INTEGER,
            salary_period           TEXT,
            pipeline_metadata       JSONB       NOT NULL DEFAULT '{}',
            metadata                JSONB       NOT NULL DEFAULT '{}',
            -- NULL = pipeline; set for manual entries (POST /jobs).
            created_by              UUID        REFERENCES app.users(id)
                                                ON DELETE SET NULL,
            ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.job_scores (
            -- A posting appears in a user's feed iff their score row exists.
            user_id                 UUID        NOT NULL REFERENCES app.users(id)
                                                ON DELETE CASCADE,
            dedup_hash              TEXT        NOT NULL
                                                REFERENCES raw.job_postings(dedup_hash)
                                                ON DELETE CASCADE,
            fit_score               SMALLINT    CHECK (fit_score BETWEEN 1 AND 5),
            confidence              raw.fit_confidence,
            score_rationale         TEXT,
            ai_fit_detail           JSONB,
            run_id                  TEXT        NOT NULL,
            scored_at               TIMESTAMPTZ NOT NULL,
            model                   TEXT        NOT NULL,
            provider                TEXT        NOT NULL,
            profile_version         TEXT        NOT NULL,
            failure_reason          TEXT,
            ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, dedup_hash)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_scores_user_fit"
        " ON raw.job_scores (user_id, fit_score)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_scores_user_scored_at"
        " ON raw.job_scores (user_id, scored_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_scores_run_id ON raw.job_scores (run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_postings_remote"
        " ON raw.job_postings (remote_classification)"
    )

    legacy_exists = bind.execute(
        text("SELECT to_regclass('raw.scored_job_postings') IS NOT NULL")
    ).scalar()
    n_postings = (
        bind.execute(text("SELECT count(*) FROM raw.scored_job_postings")).scalar()
        if legacy_exists
        else 0
    )
    n_apps = bind.execute(text("SELECT count(*) FROM app.user_applications")).scalar()
    n_corr = bind.execute(text("SELECT count(*) FROM app.eval_corrections")).scalar()

    admin_id = _resolve_backfill_admin(bind)
    if admin_id is None and (n_postings or n_apps or n_corr):
        raise RuntimeError(
            "0007: existing rows need a backfill owner but app.users has no "
            "admin. Seed one (0006 bootstrap / BOOTSTRAP_ADMIN_EMAIL) before "
            "running this migration."
        )

    if n_postings:
        op.execute(f"""
            INSERT INTO raw.job_postings ({_POSTING_COLS})
            SELECT {_POSTING_COLS} FROM raw.scored_job_postings
            ON CONFLICT (dedup_hash) DO NOTHING
        """)
        bind.execute(
            text(f"""
                INSERT INTO raw.job_scores
                    (user_id, dedup_hash, {_SCORE_COLS}, ingested_at)
                SELECT :admin_id, dedup_hash, {_SCORE_COLS}, ingested_at
                FROM raw.scored_job_postings
                ON CONFLICT (user_id, dedup_hash) DO NOTHING
            """),
            {"admin_id": admin_id},
        )
    if legacy_exists:
        op.execute("DROP TABLE raw.scored_job_postings")

    for table, idx_old, idx_new, idx_cols in (
        (
            "user_applications",
            "idx_user_applications_status",
            "idx_user_applications_user_status",
            "(user_id, status)",
        ),
        (
            "eval_corrections",
            "idx_eval_corrections_model_profile",
            "idx_eval_corrections_user_model_profile",
            "(user_id, original_model, profile_version)",
        ),
    ):
        op.execute(f"ALTER TABLE app.{table} ADD COLUMN user_id UUID")
        if admin_id is not None:
            bind.execute(
                text(f"UPDATE app.{table} SET user_id = :admin_id"),
                {"admin_id": admin_id},
            )
        op.execute(f"""
            ALTER TABLE app.{table}
                ALTER COLUMN user_id SET NOT NULL,
                ADD CONSTRAINT {table}_user_id_fkey
                    FOREIGN KEY (user_id) REFERENCES app.users(id)
                    ON DELETE CASCADE,
                DROP CONSTRAINT {table}_pkey,
                ADD PRIMARY KEY (user_id, dedup_hash)
        """)
        op.execute(f"DROP INDEX IF EXISTS app.{idx_old}")
        op.execute(f"CREATE INDEX {idx_new} ON app.{table} {idx_cols}")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE raw.scored_job_postings (
            dedup_hash              TEXT        PRIMARY KEY,
            source                  TEXT,
            source_job_id           TEXT,
            source_url              TEXT,
            title                   TEXT,
            company                 TEXT,
            location                TEXT,
            posted_at               DATE,
            description             TEXT,
            scraped_at              TIMESTAMPTZ,
            remote_classification   raw.remote_classification,
            fit_score               SMALLINT    CHECK (fit_score BETWEEN 1 AND 5),
            confidence              raw.fit_confidence,
            score_rationale         TEXT,
            ai_fit_detail           JSONB,
            pipeline_metadata       JSONB       NOT NULL DEFAULT '{}',
            run_id                  TEXT        NOT NULL,
            scored_at               TIMESTAMPTZ NOT NULL,
            model                   TEXT        NOT NULL,
            provider                TEXT        NOT NULL,
            profile_version         TEXT        NOT NULL,
            failure_reason          TEXT,
            metadata                JSONB       NOT NULL DEFAULT '{}',
            ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            salary_min_usd          INTEGER,
            salary_max_usd          INTEGER,
            salary_period           TEXT
        )
    """)
    # Lossy with >1 user: keep the most recently scored row per posting.
    # Postings with no score row at all cannot be represented (run_id/model/…
    # are NOT NULL on the old shape) and are dropped.
    op.execute(f"""
        INSERT INTO raw.scored_job_postings
            ({_POSTING_COLS}, {_SCORE_COLS})
        SELECT DISTINCT ON (p.dedup_hash)
            p.dedup_hash, p.source, p.source_job_id, p.source_url,
            p.title, p.company, p.location, p.posted_at, p.description, p.scraped_at,
            p.remote_classification, p.salary_min_usd, p.salary_max_usd, p.salary_period,
            p.pipeline_metadata, p.metadata, p.ingested_at,
            {", ".join("s." + c.strip() for c in _SCORE_COLS.split(","))}
        FROM raw.job_postings p
        JOIN raw.job_scores s USING (dedup_hash)
        ORDER BY p.dedup_hash, s.scored_at DESC
    """)
    op.execute("""
        CREATE INDEX idx_scored_jobs_fit_score
            ON raw.scored_job_postings (fit_score)
    """)
    op.execute("""
        CREATE INDEX idx_scored_jobs_remote_classification
            ON raw.scored_job_postings (remote_classification)
    """)
    op.execute("""
        CREATE INDEX idx_scored_jobs_scored_at
            ON raw.scored_job_postings (scored_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_scored_jobs_run_id
            ON raw.scored_job_postings (run_id)
    """)
    op.execute("""
        CREATE INDEX idx_scored_jobs_salary_min
            ON raw.scored_job_postings (salary_min_usd)
    """)
    op.execute("DROP TABLE raw.job_scores")
    op.execute("DROP TABLE raw.job_postings")

    for table, idx_old, idx_new in (
        (
            "user_applications",
            "idx_user_applications_user_status",
            "idx_user_applications_status",
        ),
        (
            "eval_corrections",
            "idx_eval_corrections_user_model_profile",
            "idx_eval_corrections_model_profile",
        ),
    ):
        # Collapsing (user_id, dedup_hash) → (dedup_hash) keeps one row per
        # posting (most recently updated wins) — lossy with >1 user.
        order_col = "updated_at" if table == "user_applications" else "corrected_at"
        op.execute(f"""
            DELETE FROM app.{table} t
            WHERE EXISTS (
                SELECT 1 FROM app.{table} other
                WHERE other.dedup_hash = t.dedup_hash
                  AND other.{order_col} > t.{order_col}
            )
        """)
        op.execute(f"""
            ALTER TABLE app.{table}
                DROP CONSTRAINT {table}_pkey,
                DROP CONSTRAINT {table}_user_id_fkey,
                DROP COLUMN user_id,
                ADD PRIMARY KEY (dedup_hash)
        """)
        op.execute(f"DROP INDEX IF EXISTS app.{idx_new}")
    op.execute(
        "CREATE INDEX idx_user_applications_status ON app.user_applications (status)"
    )
    op.execute("""
        CREATE INDEX idx_eval_corrections_model_profile
            ON app.eval_corrections (original_model, profile_version)
    """)
