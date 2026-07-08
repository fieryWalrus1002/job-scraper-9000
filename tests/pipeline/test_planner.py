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

from unittest.mock import patch

from pipeline.planner import plan_run
from pipeline.resolver import ResolveResult

from .conftest import seed_user as _seed_user
from .conftest import skip_if_no_docker

pytestmark = pytest.mark.docker


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
    run_dir = tmp_path / "overnight-2026-06-12" / "magnus_example_com"
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
    assert not (tmp_path / "r" / "profile_only_example_com").exists()
    assert not (tmp_path / "r" / "search_only_example_com").exists()
    assert (tmp_path / "r" / "complete_example_com").exists()


@skip_if_no_docker
def test_plan_run_skips_pipeline_disabled_user(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "dormant@example.com", pipeline_enabled=False)
        _seed_user(conn, "active@example.com")

        summary = plan_run(conn, run_id="r", runs_dir=tmp_path)

    # Only the active user is planned; the disabled one surfaces in the run
    # summary (issue #245 — deactivation must not vanish silently).
    assert summary["users_planned"] == 1
    assert "dormant@example.com" in summary["skipped_emails"]
    assert "active@example.com" not in summary["skipped_emails"]

    # No run dir or queue rows for the disabled user.
    assert not (tmp_path / "r" / "dormant_example_com").exists()
    assert (tmp_path / "r" / "active_example_com").exists()
    with psycopg.connect(migrated_pg) as conn:
        rows = conn.execute(
            "SELECT u.email FROM pipe.scrape_jobs sj "
            "JOIN app.users u ON u.id = sj.user_id WHERE sj.run_id = 'r'"
        ).fetchall()
    assert all(email != "dormant@example.com" for (email,) in rows)


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


# ---------------------------------------------------------------------------
# Resolution pre-pass tests (#455)
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_plan_run_resolves_companies_before_enqueue(migrated_pg, tmp_path):
    """Companies from the default seed payload are resolved before enqueue."""
    mock_result = ResolveResult(board="linkedin", slug="acme", status="resolved")

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "resolver@example.com")

        with patch(
            "pipeline.planner.AliasCache.resolve_and_cache",
            return_value=mock_result,
        ) as mock_resolve:
            plan_run(conn, run_id="r-resolve", runs_dir=tmp_path)

            # Default seed payload has ["acme", "initech"]
            calls = [c.args for c in mock_resolve.call_args_list]
            assert (conn, "acme") in calls
            assert (conn, "initech") in calls


@skip_if_no_docker
def test_plan_run_dedupes_companies_across_users(migrated_pg, tmp_path):
    """Two users listing the same company → resolve_and_cache called once."""
    mock_result = ResolveResult(board="linkedin", slug="acme", status="resolved")

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "alice@example.com")
        _seed_user(conn, "bob@example.com")

        with patch(
            "pipeline.planner.AliasCache.resolve_and_cache",
            return_value=mock_result,
        ) as mock_resolve:
            plan_run(conn, run_id="r-dedup", runs_dir=tmp_path)

            # Both users have ["acme", "initech"] → 2 unique names total
            assert mock_resolve.call_count == 2
            called_names = {c.args[1] for c in mock_resolve.call_args_list}
            assert called_names == {"acme", "initech"}


@skip_if_no_docker
def test_plan_run_summary_includes_companies_resolved(migrated_pg, tmp_path):
    """Summary dict has companies_resolved key with correct count."""
    mock_result = ResolveResult(board="linkedin", slug="acme", status="resolved")

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "summary@example.com")

        with patch(
            "pipeline.planner.AliasCache.resolve_and_cache",
            return_value=mock_result,
        ):
            summary = plan_run(conn, run_id="r-summary", runs_dir=tmp_path)

    assert "companies_resolved" in summary
    # Default seed has 2 companies: acme, initech
    assert summary["companies_resolved"] == 2


@skip_if_no_docker
def test_plan_run_skips_resolution_for_ineligible_users(migrated_pg, tmp_path):
    """Users missing profile or search config contribute no companies."""
    mock_result = ResolveResult(board="linkedin", slug="acme", status="resolved")

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        _seed_user(conn, "eligible@example.com")
        _seed_user(conn, "no_profile@example.com", with_profile=False)
        _seed_user(conn, "no_search@example.com", with_search=False)
        _seed_user(conn, "disabled@example.com", pipeline_enabled=False)

        with patch(
            "pipeline.planner.AliasCache.resolve_and_cache",
            return_value=mock_result,
        ) as mock_resolve:
            plan_run(conn, run_id="r-skip", runs_dir=tmp_path)

            # Only eligible@example.com contributes companies (acme, initech)
            called_names = {c.args[1] for c in mock_resolve.call_args_list}
            assert called_names == {"acme", "initech"}
            assert mock_resolve.call_count == 2
