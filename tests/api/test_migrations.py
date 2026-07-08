"""Migration integration tests: verify upgrade/downgrade on real Postgres data.

Each test seeds rows with statuses that a migration transforms, runs the
migration against a live DB, then asserts correctness. This catches bugs where
constraint operations and data backfills are ordered incorrectly.

Run: uv run pytest tests/api/test_migrations.py -v -m docker
Requires Docker. Skipped automatically if Docker is unavailable.
"""

from __future__ import annotations

import psycopg
import pytest

# Container + alembic helpers are shared via conftest (also used by the
# application_events DB round-trip tests). `fresh_pg` is auto-discovered.
from tests.api.conftest import _run_alembic, skip_if_no_docker

pytestmark = pytest.mark.docker


# ---------------------------------------------------------------------------
# 0005: rename withdrawn/saved, add passed
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_0005_upgrade_transforms_statuses_and_enforces_constraint(fresh_pg):
    """Upgrade 0005 must backfill renamed values and install the new constraint.

    This is the test that would have caught the migration bug: candidate_withdrew
    is not in the 0004 constraint, so the UPDATE must happen after the DROP.
    """
    _run_alembic("0004", fresh_pg)

    with psycopg.connect(fresh_pg) as conn:
        conn.execute("""
            INSERT INTO app.user_applications (dedup_hash, status) VALUES
                ('hash-withdrawn', 'withdrawn'),
                ('hash-saved',     'saved'),
                ('hash-applied',   'applied'),
                ('hash-maybe',     'maybe')
        """)

    _run_alembic("0005", fresh_pg)

    with psycopg.connect(fresh_pg) as conn:
        rows = dict(
            conn.execute(
                "SELECT dedup_hash, status FROM app.user_applications"
            ).fetchall()
        )

    assert rows["hash-withdrawn"] == "candidate_withdrew"
    assert rows["hash-saved"] == "maybe"
    assert rows["hash-applied"] == "applied"
    assert rows["hash-maybe"] == "maybe"

    # Old values must be rejected by the new constraint
    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO app.user_applications (dedup_hash, status) "
                "VALUES ('hash-constraint-check', 'withdrawn')"
            )

    # New values added by 0005 must be accepted
    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO app.user_applications (dedup_hash, status) "
            "VALUES ('hash-passed', 'passed')"
        )


@skip_if_no_docker
def test_0005_downgrade_remaps_new_statuses(fresh_pg):
    """Downgrade from 0005 back to 0004 must remap candidate_withdrew/passed to withdrawn."""
    _run_alembic("0005", fresh_pg)

    with psycopg.connect(fresh_pg) as conn:
        conn.execute("""
            INSERT INTO app.user_applications (dedup_hash, status) VALUES
                ('hash-candidate-withdrew', 'candidate_withdrew'),
                ('hash-passed',            'passed'),
                ('hash-applied',           'applied')
        """)

    _run_alembic("0004", fresh_pg, command="downgrade")

    with psycopg.connect(fresh_pg) as conn:
        rows = dict(
            conn.execute(
                "SELECT dedup_hash, status FROM app.user_applications"
            ).fetchall()
        )

    assert rows["hash-candidate-withdrew"] == "withdrawn"
    assert rows["hash-passed"] == "withdrawn"
    assert rows["hash-applied"] == "applied"

    # After downgrade, 'passed' must be rejected and 'withdrawn' accepted again
    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO app.user_applications (dedup_hash, status) "
                "VALUES ('hash-constraint-check', 'passed')"
            )


# ---------------------------------------------------------------------------
# 0006: create app.users + bootstrap admin seed
# ---------------------------------------------------------------------------

_BOOTSTRAP = {"BOOTSTRAP_ADMIN_EMAIL": "Bootstrap-Admin@Example.com"}


@skip_if_no_docker
def test_0006_creates_users_and_seeds_bootstrap_admin(fresh_pg):
    """BOOTSTRAP_ADMIN_EMAIL takes precedence over any local auth.yml, so the
    seed is deterministic across machines with and without that file."""
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        rows = conn.execute(
            "SELECT email, role, external_id, identity_provider FROM app.users"
        ).fetchall()

    assert rows == [("bootstrap-admin@example.com", "admin", None, None)]


@skip_if_no_docker
def test_0006_users_constraints(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        # duplicate email rejected
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO app.users (email) VALUES ('bootstrap-admin@example.com')"
            )
        # invalid role rejected
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO app.users (email, role) VALUES ('x@example.com', 'root')"
            )
        # duplicate (identity_provider, external_id) rejected once linked
        conn.execute(
            "INSERT INTO app.users (email, identity_provider, external_id) "
            "VALUES ('a@example.com', 'aad', 'oid-1')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO app.users (email, identity_provider, external_id) "
                "VALUES ('b@example.com', 'aad', 'oid-1')"
            )
        # multiple unlinked rows (NULL external_id) are fine
        conn.execute("INSERT INTO app.users (email) VALUES ('c@example.com')")
        conn.execute("INSERT INTO app.users (email) VALUES ('d@example.com')")


@skip_if_no_docker
def test_0006_downgrade_drops_users(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)
    _run_alembic("0005", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        exists = conn.execute("SELECT to_regclass('app.users') IS NOT NULL").fetchone()[
            0
        ]
    assert exists is False


# ---------------------------------------------------------------------------
# 0007: split postings/scores, scope app tables per user
# ---------------------------------------------------------------------------


def _legacy_schema_sql() -> str:
    """The pre-0007 raw.scored_job_postings DDL, inlined: 0007 must be tested
    against the legacy single-table shape it migrates (the hand-maintained
    db/schema.sql that once described it has since been retired, #173)."""
    return """
    CREATE SCHEMA IF NOT EXISTS raw;
    DO $$ BEGIN
        CREATE TYPE raw.remote_classification AS ENUM (
            'fully_remote', 'remote_with_quarterly_travel',
            'remote_with_monthly_travel', 'remote_with_frequent_travel',
            'hybrid', 'onsite_disguised', 'location_restricted', 'unclear');
    EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    DO $$ BEGIN
        CREATE TYPE raw.fit_confidence AS ENUM ('low', 'medium', 'high');
    EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    CREATE TABLE raw.scored_job_postings (
        dedup_hash TEXT PRIMARY KEY,
        source TEXT, source_job_id TEXT, source_url TEXT,
        title TEXT, company TEXT, location TEXT,
        posted_at DATE, description TEXT, scraped_at TIMESTAMPTZ,
        remote_classification raw.remote_classification,
        fit_score SMALLINT CHECK (fit_score BETWEEN 1 AND 5),
        confidence raw.fit_confidence,
        score_rationale TEXT, ai_fit_detail JSONB,
        pipeline_metadata JSONB NOT NULL DEFAULT '{}',
        run_id TEXT NOT NULL, scored_at TIMESTAMPTZ NOT NULL,
        model TEXT NOT NULL, provider TEXT NOT NULL,
        profile_version TEXT NOT NULL, failure_reason TEXT,
        metadata JSONB NOT NULL DEFAULT '{}',
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        salary_min_usd INTEGER, salary_max_usd INTEGER, salary_period TEXT
    );
    """


def _seed_legacy_data(conn_str: str) -> None:
    with psycopg.connect(conn_str) as conn:
        conn.execute(_legacy_schema_sql())
        conn.execute("""
            INSERT INTO raw.scored_job_postings
                (dedup_hash, title, company, fit_score, run_id, scored_at,
                 model, provider, profile_version)
            VALUES
                ('hash-1', 'Engineer A', 'Acme', 4, 'run-1', now(), 'm', 'p', 'v1'),
                ('hash-2', 'Engineer B', 'Initech', 2, 'run-1', now(), 'm', 'p', 'v1')
        """)
        conn.execute(
            "INSERT INTO app.user_applications (dedup_hash, status) "
            "VALUES ('hash-1', 'applied')"
        )
        conn.execute("""
            INSERT INTO app.eval_corrections
                (dedup_hash, corrected_score, original_score, original_model,
                 profile_version)
            VALUES ('hash-2', 3, 2, 'm', 'v1')
        """)


@skip_if_no_docker
def test_0007_splits_tables_and_backfills_to_admin(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)
    _seed_legacy_data(fresh_pg)

    _run_alembic("0007", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        admin_id = conn.execute(
            "SELECT id FROM app.users WHERE role = 'admin'"
        ).fetchone()[0]

        postings = conn.execute(
            "SELECT dedup_hash, title FROM raw.job_postings ORDER BY dedup_hash"
        ).fetchall()
        assert postings == [("hash-1", "Engineer A"), ("hash-2", "Engineer B")]

        scores = conn.execute(
            "SELECT dedup_hash, user_id, fit_score FROM raw.job_scores "
            "ORDER BY dedup_hash"
        ).fetchall()
        assert scores == [("hash-1", admin_id, 4), ("hash-2", admin_id, 2)]

        legacy = conn.execute(
            "SELECT to_regclass('raw.scored_job_postings')"
        ).fetchone()[0]
        assert legacy is None

        app_row = conn.execute(
            "SELECT user_id, status FROM app.user_applications"
        ).fetchall()
        assert app_row == [(admin_id, "applied")]

        corr_row = conn.execute(
            "SELECT user_id, corrected_score FROM app.eval_corrections"
        ).fetchall()
        assert corr_row == [(admin_id, 3)]


@skip_if_no_docker
def test_0007_composite_pk_allows_second_user_rows(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)
    _seed_legacy_data(fresh_pg)
    _run_alembic("0007", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        other_id = conn.execute(
            "INSERT INTO app.users (email, role) "
            "VALUES ('member@example.com', 'member') RETURNING id"
        ).fetchone()[0]
        # Same dedup_hash, different user — legal under the composite PK
        conn.execute(
            "INSERT INTO raw.job_scores "
            "(user_id, dedup_hash, fit_score, run_id, scored_at, model, "
            " provider, profile_version) "
            "VALUES (%s, 'hash-1', 5, 'run-2', now(), 'm', 'p', 'v1')",
            (other_id,),
        )
        conn.execute(
            "INSERT INTO app.user_applications (user_id, dedup_hash, status) "
            "VALUES (%s, 'hash-1', 'maybe')",
            (other_id,),
        )
        # Duplicate (user, hash) still rejected
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO app.user_applications (user_id, dedup_hash, status) "
                "VALUES (%s, 'hash-1', 'applied')",
                (other_id,),
            )


@skip_if_no_docker
def test_0007_upgrade_on_fresh_db_without_legacy_table(fresh_pg):
    """A fresh DB never had raw.scored_job_postings (it came from the
    now-retired hand-maintained schema, not Alembic) — 0007 must bootstrap
    raw itself."""
    _run_alembic("0007", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        for table in ("raw.job_postings", "raw.job_scores"):
            exists = conn.execute(
                f"SELECT to_regclass('{table}') IS NOT NULL"
            ).fetchone()[0]
            assert exists is True, f"{table} missing"


@skip_if_no_docker
def test_0007_downgrade_reconstructs_legacy_table(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)
    _seed_legacy_data(fresh_pg)
    _run_alembic("0007", fresh_pg, extra_env=_BOOTSTRAP)

    _run_alembic("0006", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        rows = conn.execute(
            "SELECT dedup_hash, fit_score FROM raw.scored_job_postings "
            "ORDER BY dedup_hash"
        ).fetchall()
        assert rows == [("hash-1", 4), ("hash-2", 2)]
        app_pk_cols = conn.execute("""
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'app.user_applications'::regclass
              AND i.indisprimary
        """).fetchall()
        assert app_pk_cols == [("dedup_hash",)]


# ---------------------------------------------------------------------------
# 0010: pipe schema + scrape_jobs / consolidated_postings (Phase 13 §5)
# ---------------------------------------------------------------------------


def _make_user(conn_str: str, email: str) -> str:
    """Insert a user row; return the generated UUID as text (so the test can
    cast back to UUID when it needs to)."""
    with psycopg.connect(conn_str) as conn:
        row = conn.execute(
            "INSERT INTO app.users (email) VALUES (%s) RETURNING id::text",
            (email,),
        ).fetchone()
    assert row is not None
    return row[0]


@skip_if_no_docker
def test_0010_creates_pipe_schema_and_tables(fresh_pg):
    _run_alembic("0010", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        for table in ("pipe.scrape_jobs", "pipe.consolidated_postings"):
            row = conn.execute(f"SELECT to_regclass('{table}') IS NOT NULL").fetchone()
            assert row is not None and row[0] is True, f"{table} missing"


@skip_if_no_docker
def test_0010_scrape_jobs_constraints(fresh_pg):
    _run_alembic("0010", fresh_pg, extra_env=_BOOTSTRAP)
    uid = _make_user(fresh_pg, "constraints@example.com")

    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO pipe.scrape_jobs (run_id, user_id, source, query_payload) "
            "VALUES ('r1', %s::uuid, 'linkedin', '{}'::jsonb)",
            (uid,),
        )
        # UNIQUE (run_id, user_id, source) makes re-enqueue idempotent
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO pipe.scrape_jobs (run_id, user_id, source, query_payload) "
                "VALUES ('r1', %s::uuid, 'linkedin', '{}'::jsonb)",
                (uid,),
            )
        # status CHECK rejects unknown values
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO pipe.scrape_jobs "
                "(run_id, user_id, source, query_payload, status) "
                "VALUES ('r2', %s::uuid, 'linkedin', '{}'::jsonb, 'queued')",
                (uid,),
            )


@skip_if_no_docker
def test_0010_downgrade_drops_pipe(fresh_pg):
    _run_alembic("0010", fresh_pg, extra_env=_BOOTSTRAP)
    _run_alembic("0009", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        for table in ("pipe.scrape_jobs", "pipe.consolidated_postings"):
            row = conn.execute(f"SELECT to_regclass('{table}') IS NOT NULL").fetchone()
            assert row is not None and row[0] is False, f"{table} still present"
        schema = conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'pipe'"
        ).fetchone()
        assert schema is None


# ---------------------------------------------------------------------------
# 0015: backfill notes → events, then drop the notes column
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_0015_backfills_notes_into_events_and_drops_column(fresh_pg):
    """Migration 0015 must INSERT each non-empty notes value as a kind='event'
    row (occurred_at = updated_at), then DROP the notes column."""
    _run_alembic("0014", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        uid = conn.execute("SELECT id FROM app.users WHERE role = 'admin'").fetchone()[
            0
        ]

        # Seed applications with notes
        conn.execute(
            """
            INSERT INTO app.user_applications (user_id, dedup_hash, status, notes, updated_at)
            VALUES
                (%s, 'hash-with-notes',   'maybe',   'Important note here', '2026-01-15T10:00:00'::timestamptz),
                (%s, 'hash-empty-notes',  'applied', '',                    '2026-02-20T14:00:00'::timestamptz),
                (%s, 'hash-null-notes',   'screening', NULL,               '2026-03-10T09:00:00'::timestamptz),
                (%s, 'hash-whitespace',   'maybe',   '   ',               '2026-04-01T12:00:00'::timestamptz)
        """,
            (uid, uid, uid, uid),
        )

    _run_alembic("0015", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        # Only the non-empty, non-whitespace notes row should have been backfilled
        events = conn.execute("""
            SELECT dedup_hash, kind, body, occurred_at
            FROM app.application_events
            WHERE kind = 'event'
            ORDER BY dedup_hash
        """).fetchall()
        assert len(events) == 1
        assert events[0][0] == "hash-with-notes"
        assert events[0][1] == "event"
        assert events[0][2] == "Important note here"
        assert events[0][3].isoformat().startswith("2026-01-15")

        # The notes column must be gone
        col_exists = conn.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'app'
              AND table_name = 'user_applications'
              AND column_name = 'notes'
        """).fetchone()
        assert col_exists is None, "notes column still exists"


@skip_if_no_docker
def test_0015_downgrade_recreates_notes_column(fresh_pg):
    """Downgrade from 0015 back to 0014 must re-add the notes column."""
    _run_alembic("0014", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        uid = conn.execute("SELECT id FROM app.users WHERE role = 'admin'").fetchone()[
            0
        ]
        conn.execute(
            """
            INSERT INTO app.user_applications (user_id, dedup_hash, status, notes)
            VALUES (%s, 'hash-a', 'maybe', 'some note')
        """,
            (uid,),
        )

    _run_alembic("0015", fresh_pg, extra_env=_BOOTSTRAP)
    _run_alembic("0014", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        col_exists = conn.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'app'
              AND table_name = 'user_applications'
              AND column_name = 'notes'
        """).fetchone()
        assert col_exists is not None, "notes column not restored by downgrade"


# ---------------------------------------------------------------------------
# 0016: grab_bag_size + grab_bag_score_floor columns
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_0016_adds_grab_bag_columns_with_defaults(fresh_pg):
    """Migration 0016 adds grab_bag_size (default 20) and grab_bag_score_floor
    (default 3) to app.user_search_configs."""
    _run_alembic("0015", fresh_pg, extra_env=_BOOTSTRAP)

    # Seed a search config row so we can check defaults
    with psycopg.connect(fresh_pg) as conn:
        uid = conn.execute("SELECT id FROM app.users WHERE role = 'admin'").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO app.user_search_configs (user_id, payload, policies) "
            "VALUES (%s, '{}'::jsonb, '{}'::jsonb)",
            (uid,),
        )

    _run_alembic("0016", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        row = conn.execute(
            "SELECT grab_bag_size, grab_bag_score_floor FROM app.user_search_configs"
        ).fetchone()
        assert row[0] == 20, "grab_bag_size default should be 20"
        assert row[1] == 3, "grab_bag_score_floor default should be 3"


@skip_if_no_docker
def test_0016_downgrade_drops_grab_bag_columns(fresh_pg):
    """Downgrade from 0016 back to 0015 must remove grab_bag columns."""
    _run_alembic("0016", fresh_pg, extra_env=_BOOTSTRAP)
    _run_alembic("0015", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        for col in ("grab_bag_size", "grab_bag_score_floor"):
            exists = conn.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name = 'user_search_configs'
                  AND column_name = %s
            """,
                (col,),
            ).fetchone()
            assert exists is None, f"{col} should be dropped after downgrade"


# ---------------------------------------------------------------------------
# 0019: raw.company_aliases + raw.company_boards
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_0019_downgrade_drops_both_tables(fresh_pg):
    """Downgrade from 0019 to 0018 must drop both tables."""
    _run_alembic("0019", fresh_pg)

    # Confirm tables exist after upgrade
    with psycopg.connect(fresh_pg) as conn:
        for table in ("raw.company_aliases", "raw.company_boards"):
            exists = conn.execute(
                f"SELECT to_regclass('{table}') IS NOT NULL"
            ).fetchone()[0]
            assert exists is True, f"{table} missing after upgrade"

    _run_alembic("0018", fresh_pg, command="downgrade")

    # Confirm tables are gone after downgrade
    with psycopg.connect(fresh_pg) as conn:
        for table in ("raw.company_aliases", "raw.company_boards"):
            exists = conn.execute(
                f"SELECT to_regclass('{table}') IS NOT NULL"
            ).fetchone()[0]
            assert exists is False, f"{table} still present after downgrade"
