"""Integration tests for ``src/pipeline/consolidation.py`` + the overnight
wiring through classification.

A fake ``classify_fn`` is injected so no test touches an LLM, mirroring how
the worker tests inject ``scrape_fn``. Consolidation still talks to a real
Postgres so the upsert and the succeeded-rows query exercise their actual SQL.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from pipeline.consolidation import (
    classify_consolidated,
    consolidate_run,
    consolidated_dir,
)
from pipeline.overnight import run_overnight
from pipeline.queue import enqueue

from .conftest import seed_user, skip_if_no_docker

pytestmark = pytest.mark.docker


def _seed_scrape_job(
    conn: psycopg.Connection,
    runs_dir: Path,
    *,
    run_id: str,
    user_id: str,
    email: str,
    source: str,
    postings: list[dict] | None,
    status: str = "succeeded",
) -> None:
    """Enqueue a job, force it to ``status``, and (unless ``postings`` is
    None) write its scrape JSONL the way the worker would have."""
    enqueue(conn, run_id=run_id, user_id=user_id, source=source, query_payload={})
    conn.execute(
        "UPDATE pipe.scrape_jobs SET status = %s "
        "WHERE run_id = %s AND user_id = %s::uuid AND source = %s",
        (status, run_id, user_id, source),
    )
    if postings is None:
        return
    slug = email.strip().lower().replace("@", "_").replace(".", "_")
    dest = runs_dir / slug / run_id / "scrape" / f"{source}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(json.dumps(p) + "\n" for p in postings))


def _consolidated_rows(conn: psycopg.Connection, run_id: str) -> dict[str, list[str]]:
    """``{dedup_hash: [user_id, ...]}`` for the run."""
    rows = conn.execute(
        "SELECT dedup_hash, requested_by::text[] FROM pipe.consolidated_postings "
        "WHERE run_id = %s",
        (run_id,),
    ).fetchall()
    return {h: users for h, users in rows}


def _fake_classify_factory(calls: list[dict]):
    def _fn(*, input_path: Path, pass_path: Path, trash_path: Path, parent_run_id: str):
        calls.append(
            {
                "input_path": input_path,
                "pass_path": pass_path,
                "trash_path": trash_path,
                "parent_run_id": parent_run_id,
            }
        )
        n = len(input_path.read_text().splitlines())
        return {"pass": n, "trash": 0, "skipped": 0, "total": n}

    return _fn


# ---------------------------------------------------------------------------
# consolidate_run
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_consolidate_merges_requested_by_across_users(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")

        shared = {"dedup_hash": "h-shared", "title": "ML Eng", "description": "d"}
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u1,
            email="alice@example.com",
            source="linkedin",
            postings=[shared, {"dedup_hash": "h-alice", "title": "A"}],
        )
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u2,
            email="bob@example.com",
            source="jobspy",
            postings=[shared, {"dedup_hash": "h-bob", "title": "B"}],
        )

        summary = consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        rows = _consolidated_rows(conn, "r")

    assert summary["postings_read"] == 4
    assert summary["postings_consolidated"] == 3
    assert summary["duplicates_collapsed"] == 1
    assert summary["keyless_skipped"] == 0

    assert set(rows) == {"h-shared", "h-alice", "h-bob"}
    assert set(rows["h-shared"]) == {u1, u2}
    assert rows["h-alice"] == [u1]
    assert rows["h-bob"] == [u2]

    # Union JSONL holds the canonical postings, one line per dedup key.
    union_path = consolidated_dir(tmp_path, "r") / "postings.jsonl"
    assert str(union_path) == summary["union_path"]
    hashes = [
        json.loads(line)["dedup_hash"] for line in union_path.read_text().splitlines()
    ]
    assert sorted(hashes) == ["h-alice", "h-bob", "h-shared"]


@skip_if_no_docker
def test_consolidate_skips_failed_jobs(migrated_pg, tmp_path):
    """Spec §7: the run proceeds for users whose scrapes succeeded; a failed
    job's postings never enter the consolidated set, even if its JSONL
    exists on disk (e.g. the worker died between persist and mark)."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "ok@example.com")
        u2 = seed_user(conn, "boom@example.com")

        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u1,
            email="ok@example.com",
            source="linkedin",
            postings=[{"dedup_hash": "h-ok", "title": "OK"}],
        )
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u2,
            email="boom@example.com",
            source="jobspy",
            postings=[{"dedup_hash": "h-failed", "title": "Nope"}],
            status="failed",
        )

        summary = consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        rows = _consolidated_rows(conn, "r")

    assert summary["scrape_files_read"] == 1
    assert set(rows) == {"h-ok"}


@skip_if_no_docker
def test_consolidate_is_idempotent(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "rerun@example.com")
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u1,
            email="rerun@example.com",
            source="linkedin",
            postings=[{"dedup_hash": "h1", "title": "X"}],
        )

        first = consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        second = consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        rows = _consolidated_rows(conn, "r")

    assert first["postings_consolidated"] == second["postings_consolidated"] == 1
    assert rows == {"h1": [u1]}  # requested_by not duplicated by the re-run


@skip_if_no_docker
def test_consolidate_picks_up_retried_user_on_rerun(migrated_pg, tmp_path):
    """requested_by is re-derived in full: a user whose scrape failed first
    time around joins the row once their retry succeeds."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "early@example.com")
        u2 = seed_user(conn, "late@example.com")

        shared = {"dedup_hash": "h-shared", "title": "X"}
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u1,
            email="early@example.com",
            source="linkedin",
            postings=[shared],
        )
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u2,
            email="late@example.com",
            source="jobspy",
            postings=[shared],
            status="failed",
        )

        consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        assert _consolidated_rows(conn, "r") == {"h-shared": [u1]}

        # The retry succeeds; re-consolidating picks the second user up.
        conn.execute(
            "UPDATE pipe.scrape_jobs SET status = 'succeeded' WHERE user_id = %s::uuid",
            (u2,),
        )
        consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        rows = _consolidated_rows(conn, "r")

    assert set(rows["h-shared"]) == {u1, u2}


@skip_if_no_docker
def test_consolidate_raises_on_missing_jsonl_for_succeeded_row(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "gone@example.com")
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u1,
            email="gone@example.com",
            source="linkedin",
            postings=None,  # succeeded row, no file on disk
        )

        with pytest.raises(FileNotFoundError, match="succeeded"):
            consolidate_run(conn, run_id="r", runs_dir=tmp_path)


@skip_if_no_docker
def test_consolidate_skips_keyless_postings(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "keyless@example.com")
        _seed_scrape_job(
            conn,
            tmp_path,
            run_id="r",
            user_id=u1,
            email="keyless@example.com",
            source="linkedin",
            postings=[
                {"dedup_hash": "h1", "title": "keyed"},
                {"title": "no keys at all"},
                {"dedup_hash": "", "source_job_id": "sid-1", "title": "fallback"},
            ],
        )

        summary = consolidate_run(conn, run_id="r", runs_dir=tmp_path)
        rows = _consolidated_rows(conn, "r")

    assert summary["keyless_skipped"] == 1
    assert set(rows) == {"h1", "sid-1"}  # source_job_id fallback keys the row


# ---------------------------------------------------------------------------
# classify_consolidated
# ---------------------------------------------------------------------------


def test_classify_consolidated_invokes_classify_fn_with_run_paths(tmp_path):
    out_dir = consolidated_dir(tmp_path, "r")
    out_dir.mkdir(parents=True)
    (out_dir / "postings.jsonl").write_text('{"dedup_hash": "h1"}\n')

    calls: list[dict] = []
    summary = classify_consolidated(
        runs_dir=tmp_path, run_id="r", classify_fn=_fake_classify_factory(calls)
    )

    assert summary == {"pass": 1, "trash": 0, "skipped": 0, "total": 1}
    assert len(calls) == 1
    assert calls[0]["input_path"] == out_dir / "postings.jsonl"
    assert calls[0]["pass_path"] == out_dir / "classified_pass.jsonl"
    assert calls[0]["trash_path"] == out_dir / "classified_trash.jsonl"
    assert calls[0]["parent_run_id"] == "r"


# ---------------------------------------------------------------------------
# run_overnight wiring — plan → scrape → consolidate → classify
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_run_overnight_runs_through_classification_then_raises(migrated_pg, tmp_path):
    """End-to-end with fakes at both injection points. The slice-6 guard
    still fires after classification — that's asserted, not worked around —
    but every phase before it must have completed."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        seed_user(conn, "e2e@example.com")

    posting = {
        "dedup_hash": "h-e2e",
        "title": "ML Engineer",
        "company": "Acme",
        "description": "d",
    }
    calls: list[dict] = []

    with pytest.raises(NotImplementedError, match="slice 6"):
        run_overnight(
            run_date="2026-06-12",
            runs_dir=tmp_path,
            database_url=migrated_pg,
            scrape_fn=lambda source, payload: [posting],
            classify_fn=_fake_classify_factory(calls),
        )

    with psycopg.connect(migrated_pg) as conn:
        rows = _consolidated_rows(conn, "overnight-2026-06-12")
    assert set(rows) == {"h-e2e"}

    # Classification ran once over the union file (same posting scraped for
    # every source collapses to one line).
    assert len(calls) == 1
    union = calls[0]["input_path"].read_text().splitlines()
    assert len(union) == 1
    assert calls[0]["parent_run_id"] == "overnight-2026-06-12"


@skip_if_no_docker
def test_run_overnight_skips_classification_when_nothing_consolidated(
    migrated_pg, tmp_path
):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        seed_user(conn, "quiet@example.com")

    calls: list[dict] = []
    with pytest.raises(NotImplementedError):
        run_overnight(
            run_date="2026-06-12",
            runs_dir=tmp_path,
            database_url=migrated_pg,
            scrape_fn=lambda source, payload: [],
            classify_fn=_fake_classify_factory(calls),
        )

    assert calls == []  # empty union never reaches the classifier
