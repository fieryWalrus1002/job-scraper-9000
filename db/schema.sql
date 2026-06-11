-- Raw ingestion schema: shared job postings + per-user scores.
-- Owned by the Python ingest script; dbt treats these as Sources (read-only).
-- All DDL is idempotent — safe to re-run against an existing database.
--
-- NOTE: raw.job_scores references app.users, which is owned by Alembic
-- (migration 0006). On a fresh database, run the API (or `alembic upgrade
-- head`) once before applying this schema. Ingest cannot run without
-- app.users anyway — every batch resolves its target user against it.

CREATE SCHEMA IF NOT EXISTS raw;

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
END $$;

DO $$ BEGIN
    CREATE TYPE raw.fit_confidence AS ENUM ('low', 'medium', 'high');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Shared descriptive storage: one row per posting regardless of how many
-- users' pipeline runs surfaced it. First scrape wins (ingest upserts with
-- ON CONFLICT DO NOTHING).
CREATE TABLE IF NOT EXISTS raw.job_postings (
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

    -- Classifies the job itself, not fit against a profile.
    remote_classification   raw.remote_classification,

    salary_min_usd          INTEGER,
    salary_max_usd          INTEGER,
    salary_period           TEXT,

    pipeline_metadata       JSONB       NOT NULL DEFAULT '{}',
    metadata                JSONB       NOT NULL DEFAULT '{}',

    -- NULL = pipeline; set for manual entries created via the API.
    created_by              UUID        REFERENCES app.users(id)
                                        ON DELETE SET NULL,

    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user scoring + run provenance. A posting appears in a user's feed iff
-- their score row exists. Re-scores are last-write-wins (ingest upserts with
-- ON CONFLICT DO UPDATE).
CREATE TABLE IF NOT EXISTS raw.job_scores (
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
);

CREATE INDEX IF NOT EXISTS idx_job_scores_user_fit
    ON raw.job_scores (user_id, fit_score);

CREATE INDEX IF NOT EXISTS idx_job_scores_user_scored_at
    ON raw.job_scores (user_id, scored_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_scores_run_id
    ON raw.job_scores (run_id);

CREATE INDEX IF NOT EXISTS idx_job_postings_remote
    ON raw.job_postings (remote_classification);

COMMENT ON TABLE raw.job_postings IS
    'Shared landing table for scraped job postings (descriptive fields only). '
    'Written by the ingest CLI; read-only for dbt.';
COMMENT ON TABLE raw.job_scores IS
    'Per-user skills-fit scores and run provenance, keyed (user_id, dedup_hash). '
    'Written by the ingest CLI; read-only for dbt.';
