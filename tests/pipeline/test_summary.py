"""Tests for ``src/pipeline/summary.py`` — the end-of-run per-user rollup
and the all-failed exit verdict (Phase 13 slice 7, spec §7).

Scrape outcomes are seeded straight into ``pipe.scrape_jobs`` against a real
Postgres so the grouping query runs its actual SQL; the scoring summary is
the in-memory dict ``score_run`` returns.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Json

from pipeline.summary import build_overnight_summary

from .conftest import seed_user, skip_if_no_docker

pytestmark = pytest.mark.docker

RUN_ID = "overnight-2026-06-12"


def _scrape_job(
    conn: psycopg.Connection,
    *,
    user_id: str,
    source: str,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO pipe.scrape_jobs (run_id, user_id, source, query_payload, status, error)
        VALUES (%s, %s::uuid, %s, %s, %s, %s)
        """,
        (RUN_ID, user_id, source, Json({}), status, error),
    )


def _scoring(per_user: list[dict]) -> dict:
    return {"per_user": per_user}


@skip_if_no_docker
def test_partial_success_exits_zero_and_lists_failed_user(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u_ok = seed_user(conn, "ok@example.com")
        u_bad = seed_user(conn, "bad@example.com")
        _scrape_job(conn, user_id=u_ok, source="linkedin", status="succeeded")
        _scrape_job(
            conn,
            user_id=u_bad,
            source="jobspy",
            status="failed",
            error="Traceback ...\nRuntimeError: indeed timed out",
        )

    summary = build_overnight_summary(
        migrated_pg,
        run_id=RUN_ID,
        scrape={"succeeded": 1, "failed": 1},
        scoring=_scoring([{"email": "ok@example.com", "postings_scored": 3}]),
    )

    assert summary["users_ok"] == 1
    assert summary["users_failed"] == 1
    assert summary["all_failed"] is False
    # Failed user's exception one-liner surfaces; full traceback stays in the log.
    assert "RuntimeError: indeed timed out" in summary["text"]
    assert "bad@example.com — FAILED" in summary["text"]
    assert "ok@example.com — OK (3 scored)" in summary["text"]


@skip_if_no_docker
def test_all_users_failed_exits_nonzero(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "a@example.com")
        u2 = seed_user(conn, "b@example.com")
        _scrape_job(conn, user_id=u1, source="linkedin", status="failed", error="boom1")
        _scrape_job(conn, user_id=u2, source="jobspy", status="failed", error="boom2")

    summary = build_overnight_summary(
        migrated_pg,
        run_id=RUN_ID,
        scrape={"succeeded": 0, "failed": 2},
        scoring=None,
    )

    assert summary["users_ok"] == 0
    assert summary["users_failed"] == 2
    assert summary["all_failed"] is True


@skip_if_no_docker
def test_scoring_failure_marks_user_failed(migrated_pg, tmp_path):
    """A user whose scrape succeeded but whose skills_fit step raised is
    failed overall — and is the only user, so the run all-failed."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "scorefail@example.com")
        _scrape_job(conn, user_id=u1, source="linkedin", status="succeeded")

    summary = build_overnight_summary(
        migrated_pg,
        run_id=RUN_ID,
        scrape={"succeeded": 1, "failed": 0},
        scoring=_scoring(
            [
                {
                    "email": "scorefail@example.com",
                    "failed": True,
                    "error": "Traceback ...\nValueError: bad profile",
                }
            ]
        ),
    )

    assert summary["all_failed"] is True
    assert summary["users_failed"] == 1
    assert "skills_fit: ValueError: bad profile" in summary["text"]


@skip_if_no_docker
def test_partial_scrape_failure_keeps_user_ok_but_lists_source(migrated_pg, tmp_path):
    """One source failing while another succeeds: the user still passes the
    scrape gate, but the failed source is surfaced for the admin."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "mixed@example.com")
        _scrape_job(conn, user_id=u1, source="linkedin", status="succeeded")
        _scrape_job(
            conn, user_id=u1, source="jobspy", status="failed", error="ZipRecruiter 403"
        )

    summary = build_overnight_summary(
        migrated_pg,
        run_id=RUN_ID,
        scrape={"succeeded": 1, "failed": 1},
        scoring=_scoring([{"email": "mixed@example.com", "postings_scored": 2}]),
    )

    assert summary["all_failed"] is False
    assert summary["users_ok"] == 1
    user = summary["per_user"][0]
    assert user["ok"] is True
    assert user["scrape_failed"] == [("jobspy", "ZipRecruiter 403")]
    assert "jobspy: ZipRecruiter 403" in summary["text"]


@skip_if_no_docker
def test_no_users_planned_is_not_all_failed(migrated_pg, tmp_path):
    """An empty run (no scrape jobs at all) is vacuously not all-failed —
    exit zero, nothing for the admin to chase."""
    summary = build_overnight_summary(
        migrated_pg,
        run_id=RUN_ID,
        scrape={"succeeded": 0, "failed": 0},
        scoring=None,
    )

    assert summary["per_user"] == []
    assert summary["all_failed"] is False
    assert "no users planned" in summary["text"]
