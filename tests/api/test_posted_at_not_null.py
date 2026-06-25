"""Live-Postgres tests for migration 0017: posted_at backfill + NOT NULL.

Verifies the backfill chain (posted_at ← scraped_at ← ingested_at) and
that the NOT NULL constraint is enforced after upgrade.

Run: uv run pytest tests/api/test_posted_at_not_null.py -v -m docker
Requires Docker. Skipped automatically if Docker is unavailable.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from tests.api.conftest import _run_alembic, skip_if_no_docker

pytestmark = pytest.mark.docker

_BOOTSTRAP = {"BOOTSTRAP_ADMIN_EMAIL": "admin@example.com"}


@skip_if_no_docker
def test_0017_backfills_null_posted_at_and_enforces_not_null(fresh_pg):
    """Migration 0017 must backfill NULL posted_at from scraped_at or
    ingested_at, then flip the column to NOT NULL."""
    # Migrate through 0016 (pre-0017 state)
    _run_alembic("0016", fresh_pg, extra_env=_BOOTSTRAP)

    # Seed rows with various NULL posted_at scenarios
    with psycopg.connect(fresh_pg) as conn:
        conn.execute("""
            INSERT INTO raw.job_postings
                (dedup_hash, title, company, source, source_url, posted_at,
                 scraped_at, ingested_at, remote_classification)
            VALUES
                -- Row 1: posted_at NULL, scraped_at present → should backfill from scraped_at
                ('hash-scraped', 'Scraped Job', 'A', 'test', 'http://x/1', NULL,
                 '2026-03-15T10:00:00'::timestamptz, '2026-03-15T10:00:00'::timestamptz, 'fully_remote'),
                -- Row 2: posted_at NULL, scraped_at NULL → should backfill from ingested_at
                ('hash-ingested', 'Ingested Job', 'B', 'test', 'http://x/2', NULL,
                 NULL, '2026-04-01T08:00:00'::timestamptz, 'fully_remote'),
                -- Row 3: posted_at already set → should be untouched
                ('hash-already', 'Already Set', 'C', 'test', 'http://x/3', '2026-05-01',
                 '2026-05-01T12:00:00'::timestamptz, '2026-05-01T12:00:00'::timestamptz, 'fully_remote')
        """)

    _run_alembic("0017", fresh_pg, extra_env=_BOOTSTRAP)

    # Verify backfill values
    with psycopg.connect(fresh_pg) as conn:
        rows = dict(
            conn.execute(
                "SELECT dedup_hash, posted_at FROM raw.job_postings ORDER BY dedup_hash"
            ).fetchall()
        )

    # Row 1: backfilled from scraped_at
    assert rows["hash-scraped"] == date(2026, 3, 15), (
        "posted_at should be backfilled from scraped_at::date"
    )
    # Row 2: backfilled from ingested_at
    assert rows["hash-ingested"] == date(2026, 4, 1), (
        "posted_at should be backfilled from ingested_at::date when scraped_at is NULL"
    )
    # Row 3: untouched
    assert rows["hash-already"] == date(2026, 5, 1), (
        "posted_at should be unchanged when already set"
    )


@skip_if_no_docker
def test_0017_posted_at_is_not_null_in_schema(fresh_pg):
    """After migration 0017, posted_at must be NOT NULL in information_schema."""
    _run_alembic("0017", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        row = conn.execute("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name = 'job_postings'
              AND column_name = 'posted_at'
        """).fetchone()

    assert row is not None, "posted_at column not found in information_schema"
    assert row[0] == "NO", f"posted_at should be NOT NULL, got is_nullable={row[0]!r}"


@skip_if_no_docker
def test_0017_rejects_null_posted_at_insert(fresh_pg):
    """After migration 0017, inserting a row with posted_at=NULL must raise
    a NOT NULL violation."""
    _run_alembic("0017", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute("""
                INSERT INTO raw.job_postings
                    (dedup_hash, title, company, source, source_url, posted_at,
                     remote_classification)
                VALUES
                    ('hash-null-insert', 'Null Job', 'D', 'test', 'http://x/4', NULL,
                     'fully_remote')
            """)


@skip_if_no_docker
def test_0017_downgrade_drops_not_null(fresh_pg):
    """Downgrade from 0017 back to 0016 must drop the NOT NULL constraint."""
    _run_alembic("0017", fresh_pg, extra_env=_BOOTSTRAP)
    _run_alembic("0016", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        row = conn.execute("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name = 'job_postings'
              AND column_name = 'posted_at'
        """).fetchone()

    assert row is not None, "posted_at column not found"
    assert row[0] == "YES", (
        f"After downgrade, posted_at should be nullable, got is_nullable={row[0]!r}"
    )
