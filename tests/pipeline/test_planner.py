"""Integration tests for ``src/pipeline/planner.py``.

The planner reads ``app.users``, materializes per-user run dirs, and enqueues
``pipe.scrape_jobs`` rows per (user, source). These tests seed the DB with
realistic SearchConfigInput / CandidateProfileInput payloads and assert the
end-to-end behavior.
"""

from __future__ import annotations

import yaml

import psycopg
import pytest
from psycopg.types.json import Json

from pipeline.planner import plan_run

from .conftest import skip_if_no_docker

pytestmark = pytest.mark.docker


# ---------------------------------------------------------------------------
# Seed payloads — minimal-but-valid SearchConfigInput / CandidateProfileInput.
# ---------------------------------------------------------------------------


def _valid_search_payload() -> dict:
    return {
        "user": {
            "display_name": "Test User",
            "email": "test@example.com",
            "home_location": {"city": "Seattle", "region": "WA", "country": "US"},
        },
        "search_profile": {"name": "ML Engineer search"},
        "roles": {"target_titles": {"preferred": ["ML Engineer", "ML Ops"]}},
        "organizations": {"target_companies": ["acme", "initech"]},
    }


def _valid_profile_payload() -> dict:
    return {
        "summary": "Experienced ML engineer with infra background. " * 2,
        "level": "Senior individual contributor",
        "core_skills": ["Python", "PyTorch"],
    }


def _seed_user(
    conn: psycopg.Connection,
    email: str,
    *,
    with_profile: bool = True,
    with_search: bool = True,
) -> str:
    uid_row = conn.execute(
        "INSERT INTO app.users (email) VALUES (%s) RETURNING id::text", (email,)
    ).fetchone()
    assert uid_row is not None
    uid = uid_row[0]

    if with_search:
        conn.execute(
            """
            INSERT INTO app.user_search_configs (user_id, payload, policies)
            VALUES (%s::uuid, %s, %s)
            """,
            (uid, Json(_valid_search_payload()), Json({})),
        )
    if with_profile:
        conn.execute(
            """
            INSERT INTO app.candidate_profiles (user_id, payload, profile_version)
            VALUES (%s::uuid, %s, %s)
            """,
            (uid, Json(_valid_profile_payload()), "2026-06-12.testhashabcd"),
        )
    return uid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_plan_run_materializes_yaml_and_enqueues_rows(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "magnus@example.com")
        summary = plan_run(conn, run_id="overnight-2026-06-12", runs_dir=tmp_path)

    # The bootstrap admin (seeded by migration 0006 with no configs) is
    # skipped; magnus has both configs so they get planned.
    assert summary["users_planned"] == 1
    assert summary["users_skipped"] == 1
    assert "admin@example.com" in summary["skipped_emails"]
    assert summary["rows_enqueued"] >= 1

    # YAML files written for magnus.
    run_dir = tmp_path / "magnus_example_com" / "overnight-2026-06-12"
    assert (run_dir / "search.yml").exists()
    assert (run_dir / "policies.yml").exists()
    assert (run_dir / "candidate_profile.yml").exists()

    search_yaml = yaml.safe_load((run_dir / "search.yml").read_text())
    assert (
        "linkedin" in search_yaml
        or "jobspy" in search_yaml
        or "companies" in search_yaml
    )

    # Each enqueued row is pending, has a non-empty source, and a payload
    # that contains the named source key.
    with psycopg.connect(migrated_pg) as conn:
        rows = conn.execute(
            "SELECT source, status, query_payload FROM pipe.scrape_jobs "
            "WHERE run_id = 'overnight-2026-06-12'"
        ).fetchall()
    assert len(rows) == summary["rows_enqueued"]
    for source, status, payload in rows:
        assert status == "pending"
        assert source in {"linkedin", "jobspy", "companies"}
        assert source in payload


@skip_if_no_docker
def test_plan_run_skips_users_missing_one_config(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "profile_only@example.com", with_search=False)
        _seed_user(conn, "search_only@example.com", with_profile=False)
        _seed_user(conn, "complete@example.com")

        summary = plan_run(conn, run_id="r", runs_dir=tmp_path)

    assert summary["users_planned"] == 1  # only "complete@example.com"
    assert "profile_only@example.com" in summary["skipped_emails"]
    assert "search_only@example.com" in summary["skipped_emails"]
    assert "complete@example.com" not in summary["skipped_emails"]

    # No run dirs for the skipped users.
    assert not (tmp_path / "profile_only_example_com").exists()
    assert not (tmp_path / "search_only_example_com").exists()
    assert (tmp_path / "complete_example_com" / "r").exists()


@skip_if_no_docker
def test_plan_run_is_idempotent(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "rerun@example.com")
        first = plan_run(conn, run_id="r", runs_dir=tmp_path)

        # Second plan against same run_id — UNIQUE catches the inserts.
        second = plan_run(conn, run_id="r", runs_dir=tmp_path)

        rows_total = conn.execute(
            "SELECT COUNT(*) FROM pipe.scrape_jobs WHERE run_id = 'r'"
        ).fetchone()
    assert rows_total is not None
    assert rows_total[0] == first["rows_enqueued"]
    assert second["rows_enqueued"] == 0
    assert second["users_planned"] == first["users_planned"]
