"""Integration tests for ``src/pipeline/consolidation.py`` + the full overnight
wiring (plan → scrape → consolidate → classify → score; produce-only).

Fake ``classify_fn`` / ``score_fn`` are injected so no test touches an LLM,
mirroring how the worker tests inject ``scrape_fn``. The pipeline is
produce-only (Phase 15 D1) — scoring writes per-user JSONL and never ingests.
Consolidation still talks to a real Postgres so the upsert and the
succeeded-rows query exercise their actual SQL.
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
    dest = runs_dir / run_id / slug / "scrape" / f"{source}.jsonl"
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


def _fake_classify_factory(calls: list[dict], *, classification: str = "fully_remote"):
    """Records its call and writes every input posting to ``pass_path`` tagged
    with ``_remote_analysis.remote_classification`` — the shape the scoring
    phase reads back."""

    def _fn(*, input_path: Path, pass_path: Path, trash_path: Path, parent_run_id: str):
        calls.append(
            {
                "input_path": input_path,
                "pass_path": pass_path,
                "trash_path": trash_path,
                "parent_run_id": parent_run_id,
            }
        )
        lines = [ln for ln in input_path.read_text().splitlines() if ln.strip()]
        with pass_path.open("w", encoding="utf-8") as f:
            for ln in lines:
                rec = json.loads(ln)
                rec["_remote_analysis"] = {"remote_classification": classification}
                f.write(json.dumps(rec) + "\n")
        n = len(lines)
        return {"pass": n, "trash": 0, "skipped": 0, "total": n}

    return _fn


def _fake_score_factory(calls: list[dict]):
    """Echoes the per-user input to the scored output and records the call."""

    def _fn(
        *,
        input_path: Path,
        output_path: Path,
        profile_file: Path,
        run_date,
        parent_run_id,
    ):
        lines = [ln for ln in input_path.read_text().splitlines() if ln.strip()]
        output_path.write_text("".join(ln + "\n" for ln in lines))
        calls.append(
            {
                "input_path": input_path,
                "output_path": output_path,
                "profile_file": profile_file,
                "run_date": run_date,
                "parent_run_id": parent_run_id,
                "n": len(lines),
            }
        )
        return {"scored": len(lines)}

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
# run_overnight wiring — plan → scrape → consolidate → classify → score
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_run_overnight_runs_full_pipeline_through_scoring(migrated_pg, tmp_path):
    """End-to-end with fakes at every injection point. Every phase from plan
    through per-user scoring must complete, and the per-user score tail must
    see the right profile and write the user's scored JSONL (produce-only —
    no ingest)."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        seed_user(conn, "e2e@example.com")

    posting = {
        "dedup_hash": "h-e2e",
        "title": "ML Engineer",
        "company": "Acme",
        "description": "d",
    }
    classify_calls: list[dict] = []
    score_calls: list[dict] = []

    summary = run_overnight(
        run_date="2026-06-12",
        run_id="overnight-2026-06-12",
        runs_dir=tmp_path,
        database_url=migrated_pg,
        scrape_fn=lambda source, payload: [posting],
        classify_fn=_fake_classify_factory(classify_calls),
        score_fn=_fake_score_factory(score_calls),
    )

    with psycopg.connect(migrated_pg) as conn:
        rows = _consolidated_rows(conn, "overnight-2026-06-12")
    assert set(rows) == {"h-e2e"}

    # Classification ran once over the union file (same posting scraped for
    # every source collapses to one line).
    assert len(classify_calls) == 1
    assert len(classify_calls[0]["input_path"].read_text().splitlines()) == 1
    assert classify_calls[0]["parent_run_id"] == "overnight-2026-06-12"

    # Scoring fanned back out to the one user, against their materialized
    # profile, tagged with the run's date.
    assert summary["scoring"]["users_scored"] == 1
    assert summary["scoring"]["postings_scored"] == 1
    assert len(score_calls) == 1
    assert score_calls[0]["run_date"] == "2026-06-12"
    assert score_calls[0]["profile_file"] == (
        tmp_path / "overnight-2026-06-12" / "e2e_example_com" / "candidate_profile.yml"
    )
    assert score_calls[0]["parent_run_id"] == "overnight-2026-06-12"

    # Produce-only: the scored JSONL lands under the user's run dir and
    # carries their survivor (the fake score_fn copies input through).
    scored_path = score_calls[0]["output_path"]
    assert scored_path == (
        tmp_path
        / "overnight-2026-06-12"
        / "e2e_example_com"
        / "skills_fit"
        / "scored.jsonl"
    )
    scored_lines = [ln for ln in scored_path.read_text().splitlines() if ln.strip()]
    assert [json.loads(ln)["dedup_hash"] for ln in scored_lines] == ["h-e2e"]

    # End-of-run summary is attached and reflects the one successful user.
    rs = summary["run_summary"]
    assert rs["all_failed"] is False
    assert rs["users_ok"] == 1
    assert "e2e@example.com — OK" in rs["text"]


@skip_if_no_docker
def test_run_overnight_all_scrapes_failed_is_all_failed(migrated_pg, tmp_path):
    """Every user's scrape raising → nothing consolidated, and the run
    summary's verdict is all-failed (the CLI exits non-zero on it)."""

    def _boom(source, payload):
        raise RuntimeError("scraper exploded")

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        seed_user(conn, "doomed@example.com")

    summary = run_overnight(
        run_date="2026-06-12",
        run_id="overnight-2026-06-12",
        runs_dir=tmp_path,
        database_url=migrated_pg,
        scrape_fn=_boom,
        classify_fn=_fake_classify_factory([]),
        score_fn=_fake_score_factory([]),
    )

    # Nothing consolidated (the failed scrape produced no JSONL), so the tail
    # is skipped — but the run summary still renders the per-user verdict.
    assert summary["scoring"] is None
    rs = summary["run_summary"]
    assert rs["all_failed"] is True
    assert "doomed@example.com — FAILED" in rs["text"]
    assert "scraper exploded" in rs["text"]


@skip_if_no_docker
def test_run_overnight_skips_tail_when_nothing_consolidated(migrated_pg, tmp_path):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        seed_user(conn, "quiet@example.com")

    classify_calls: list[dict] = []
    score_calls: list[dict] = []

    summary = run_overnight(
        run_date="2026-06-12",
        run_id="overnight-2026-06-12",
        runs_dir=tmp_path,
        database_url=migrated_pg,
        scrape_fn=lambda source, payload: [],
        classify_fn=_fake_classify_factory(classify_calls),
        score_fn=_fake_score_factory(score_calls),
    )

    assert classify_calls == []  # empty union never reaches the classifier
    assert score_calls == []  # nor the scorer
    assert summary["classification"] is None
    assert summary["scoring"] is None
