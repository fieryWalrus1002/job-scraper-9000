"""Integration tests for ``src/pipeline/worker.py``.

A fake ``scrape_fn`` is injected so the tests don't hit any real job board.
The worker still talks to a real Postgres so claim/lease/mark semantics
exercise their actual SQL.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
import yaml

from pipeline.queue import enqueue
from pipeline.worker import (
    _apply_title_filter,
    _to_dict,
    process_job,
    run_worker,
)

from .conftest import skip_if_no_docker

pytestmark = pytest.mark.docker


def _seed_user_with_runs_dir(
    conn: psycopg.Connection,
    runs_dir: Path,
    *,
    email: str,
    run_id: str,
    excluded_title_terms: list[str] | None = None,
) -> str:
    """Make a user, materialize their per-run dir, return user_id."""
    uid_row = conn.execute(
        "INSERT INTO app.users (email) VALUES (%s) RETURNING id::text", (email,)
    ).fetchone()
    assert uid_row is not None
    uid = uid_row[0]

    # Same slug convention the worker uses internally.
    slug = email.strip().lower().replace("@", "_").replace(".", "_")
    run_dir = runs_dir / run_id / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "policies.yml").write_text(
        yaml.safe_dump(
            {"prefilter": {"excluded_title_terms": excluded_title_terms or []}}
        )
    )
    return uid


def _fake_scrape_factory(jobs: list[dict]):
    def _fn(source: str, query_payload: dict, conn=None):
        return list(jobs)

    return _fn


def _raising_scrape_fn(source: str, query_payload: dict, conn=None):
    raise RuntimeError("scraper exploded")


# ---------------------------------------------------------------------------
# Unit-ish helpers
# ---------------------------------------------------------------------------


def test_apply_title_filter_drops_case_insensitive_substrings():
    jobs = [
        {"title": "Senior ML Engineer"},
        {"title": "ML Manager (people lead)"},
        {"title": "Staff ML Engineer"},
        {"title": ""},  # no title — kept
        {"title": None},  # nullable — kept
    ]
    out = _apply_title_filter(jobs, ["manager"])
    titles = [j["title"] for j in out]
    assert "ML Manager (people lead)" not in titles
    assert "Senior ML Engineer" in titles
    assert "Staff ML Engineer" in titles


def test_to_dict_accepts_plain_dict_and_dataclass():
    from dataclasses import dataclass

    @dataclass
    class _J:
        title: str
        company: str

    assert _to_dict(_J(title="X", company="Y")) == {"title": "X", "company": "Y"}
    assert _to_dict({"title": "Z"}) == {"title": "Z"}

    with pytest.raises(TypeError):
        _to_dict("not a job")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# process_job — single job, with policy + persistence
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_process_job_writes_filtered_jsonl_and_returns_count(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _seed_user_with_runs_dir(
            conn,
            tmp_path,
            email="proc@example.com",
            run_id="r",
            excluded_title_terms=["manager"],
        )
        enqueue(conn, run_id="r", user_id=uid, source="linkedin", query_payload={})

        # Bypass claim_next by constructing the job dict the worker would receive.
        row = conn.execute(
            "SELECT id, run_id, user_id, source, query_payload "
            "FROM pipe.scrape_jobs WHERE source = 'linkedin'"
        ).fetchone()
        assert row is not None
        job = {
            "id": row[0],
            "run_id": row[1],
            "user_id": row[2],
            "source": row[3],
            "query_payload": row[4],
        }
        scrape_fn = _fake_scrape_factory(
            [
                {"title": "ML Engineer", "company": "Acme"},
                {"title": "ML Manager", "company": "Initech"},
            ]
        )
        count = process_job(conn, job, runs_dir=tmp_path, scrape_fn=scrape_fn)

    assert count == 1
    out_path = tmp_path / "r" / "proc_example_com" / "scrape" / "linkedin.jsonl"
    lines = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["title"] == "ML Engineer"


# ---------------------------------------------------------------------------
# run_worker — end-to-end claim loop + failure isolation
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_run_worker_processes_all_pending_and_marks_succeeded(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _seed_user_with_runs_dir(
            conn,
            tmp_path,
            email="worker@example.com",
            run_id="r",
        )
        enqueue(conn, run_id="r", user_id=uid, source="linkedin", query_payload={})
        enqueue(conn, run_id="r", user_id=uid, source="jobspy", query_payload={})

        scrape_fn = _fake_scrape_factory([{"title": "ML Engineer", "company": "Acme"}])
        result = run_worker(conn, runs_dir=tmp_path, scrape_fn=scrape_fn)

        assert result == {"succeeded": 2, "failed": 0}

        rows = conn.execute(
            "SELECT source, status, posting_count, error "
            "FROM pipe.scrape_jobs WHERE run_id = 'r' ORDER BY source"
        ).fetchall()
    assert [(s, st, c, err) for s, st, c, err in rows] == [
        ("jobspy", "succeeded", 1, None),
        ("linkedin", "succeeded", 1, None),
    ]


@skip_if_no_docker
def test_run_worker_isolates_failures_and_continues(migrated_pg, tmp_path):
    """One job's scrape_fn raises; the other completes. The failed row gets
    the traceback in pipe.scrape_jobs.error, the run keeps going."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _seed_user_with_runs_dir(
            conn,
            tmp_path,
            email="iso@example.com",
            run_id="r",
        )
        enqueue(conn, run_id="r", user_id=uid, source="linkedin", query_payload={})
        enqueue(conn, run_id="r", user_id=uid, source="jobspy", query_payload={})

        good_jobs = [{"title": "ML Eng", "company": "Acme"}]

        def selective(source: str, query_payload: dict, conn=None):
            if source == "linkedin":
                raise RuntimeError("LinkedIn rate-limit-pocalypse")
            return list(good_jobs)

        result = run_worker(conn, runs_dir=tmp_path, scrape_fn=selective)
        assert result == {"succeeded": 1, "failed": 1}

        rows = dict(
            conn.execute(
                "SELECT source, status FROM pipe.scrape_jobs WHERE run_id = 'r'"
            ).fetchall()
        )
        assert rows == {"linkedin": "failed", "jobspy": "succeeded"}

        err = conn.execute(
            "SELECT error FROM pipe.scrape_jobs WHERE source = 'linkedin'"
        ).fetchone()
        assert err is not None
        assert "RuntimeError: LinkedIn rate-limit-pocalypse" in (err[0] or "")
        assert "Traceback" in (err[0] or "")


@skip_if_no_docker
def test_run_worker_with_empty_queue_returns_zero_counts(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        result = run_worker(
            conn,
            runs_dir=tmp_path,
            scrape_fn=_raising_scrape_fn,
        )
    assert result == {"succeeded": 0, "failed": 0}
