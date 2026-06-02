-- Raw ingestion schema for scored job postings.
-- Owned by the Python ingest script; dbt treats these as Sources (read-only).
-- All DDL is idempotent — safe to re-run against an existing database.

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

CREATE TABLE IF NOT EXISTS raw.scored_job_postings (
    -- Primary key
    dedup_hash              TEXT        PRIMARY KEY,

    -- Core job posting fields
    source                  TEXT,
    source_job_id           TEXT,
    source_url              TEXT,
    title                   TEXT,
    company                 TEXT,
    location                TEXT,
    posted_at               DATE,
    description             TEXT,
    scraped_at              TIMESTAMPTZ,

    -- Remote-filter output (promoted for frontend filtering)
    remote_classification   raw.remote_classification,

    -- Skills-fit scalars (promoted for sorting/filtering)
    fit_score               SMALLINT    CHECK (fit_score BETWEEN 1 AND 5),
    confidence              raw.fit_confidence,
    score_rationale         TEXT,

    -- Skills-fit arrays/nested (top_matches, gaps, hard_concerns, core_job_duties)
    ai_fit_detail           JSONB,

    -- Pipeline-internal keys (prefilter, remote-filter, scrub counts, search params)
    pipeline_metadata       JSONB       NOT NULL DEFAULT '{}',

    -- Run provenance (promoted for grouping/filtering by run or model)
    run_id                  TEXT        NOT NULL,
    scored_at               TIMESTAMPTZ NOT NULL,
    model                   TEXT        NOT NULL,
    provider                TEXT        NOT NULL,
    profile_version         TEXT        NOT NULL,
    failure_reason          TEXT,

    -- Remaining provenance fields (hashes, paths, commit, etc.)
    metadata                JSONB       NOT NULL DEFAULT '{}',

    -- Ingestion bookkeeping
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scored_jobs_fit_score
    ON raw.scored_job_postings (fit_score);

CREATE INDEX IF NOT EXISTS idx_scored_jobs_remote_classification
    ON raw.scored_job_postings (remote_classification);

CREATE INDEX IF NOT EXISTS idx_scored_jobs_scored_at
    ON raw.scored_job_postings (scored_at DESC);

CREATE INDEX IF NOT EXISTS idx_scored_jobs_run_id
    ON raw.scored_job_postings (run_id);

COMMENT ON TABLE raw.scored_job_postings IS
    'Append-only landing table for ScoredJobPosting records from the skills-fit pipeline. '
    'Written by scripts/db_ingest.py; read-only for dbt (declared as a source in sources.yml).';
