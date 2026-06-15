"""Integration tests for ``src/pipeline/scoring.py`` — the per-user
skills_fit fan-out (Phase 13 slice 6; produce-only per Phase 15 D1).

A fake ``score_fn`` keeps the LLM out of the loop; the real work under test
is the per-user policy gate over the classified union and the routing of
each user's survivors to their own ``scored.jsonl``. The phase is
produce-only — it never touches ``job_scores`` (Phase 15 D1). Consolidation
state is seeded against a real Postgres so the inverted ``requested_by``
query runs its actual SQL.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Json

from pipeline.consolidation import PASS_NAME, TRASH_NAME, consolidated_dir
from pipeline.planner import _slug
from pipeline.scoring import SCORED_NAME, score_run, skills_fit_dir

from .conftest import seed_user, skip_if_no_docker

pytestmark = pytest.mark.docker

RUN_ID = "overnight-2026-06-12"
RUN_DATE = "2026-06-12"


# ---------------------------------------------------------------------------
# Helpers — seed consolidated_postings + the classified union on disk, and
# materialize the per-user profile the planner would have written.
# ---------------------------------------------------------------------------


def _seed_consolidated(
    conn: psycopg.Connection, *, dedup_hash: str, requested_by: list[str]
) -> None:
    conn.execute(
        """
        INSERT INTO pipe.consolidated_postings
            (run_id, dedup_hash, requested_by, posting_ref)
        VALUES (%s, %s, %s, %s)
        """,
        (RUN_ID, dedup_hash, [uuid.UUID(u) for u in requested_by], "ref"),
    )


def _write_classified(
    runs_dir: Path, *, passed: list[dict], trashed: list[dict] | None = None
) -> None:
    out_dir = consolidated_dir(runs_dir, RUN_ID)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PASS_NAME).write_text("".join(json.dumps(r) + "\n" for r in passed))
    if trashed:
        (out_dir / TRASH_NAME).write_text(
            "".join(json.dumps(r) + "\n" for r in trashed)
        )


def _materialize_profile(runs_dir: Path, email: str) -> None:
    profile = runs_dir / RUN_ID / _slug(email) / "candidate_profile.yml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("profile_version: test\n")


def _classified(dedup_hash: str, classification: str) -> dict:
    return {
        "dedup_hash": dedup_hash,
        "title": "Eng",
        "description": "d",
        "_remote_analysis": {"remote_classification": classification},
    }


def _set_policy(conn: psycopg.Connection, user_id: str, acceptable: list[str]) -> None:
    conn.execute(
        "UPDATE app.user_search_configs SET policies = %s WHERE user_id = %s::uuid",
        (Json({"remote": {"acceptable_classifications": acceptable}}), user_id),
    )


def _score_factory(calls: list[dict]):
    def _fn(*, input_path, output_path, profile_file, run_date, parent_run_id):
        lines = [ln for ln in input_path.read_text().splitlines() if ln.strip()]
        output_path.write_text("".join(ln + "\n" for ln in lines))
        calls.append(
            {
                "input_path": input_path,
                "profile_file": profile_file,
                "run_date": run_date,
                "hashes": [json.loads(ln)["dedup_hash"] for ln in lines],
            }
        )
        return {"scored": len(lines)}

    return _fn


def _scored_hashes(runs_dir: Path, email: str) -> list[str]:
    """dedup_hashes in a user's written ``scored.jsonl`` (the fake score_fn
    copies its input through, so this is the user's scored survivors)."""
    path = skills_fit_dir(runs_dir, email, RUN_ID) / SCORED_NAME
    return sorted(
        json.loads(ln)["dedup_hash"]
        for ln in path.read_text().splitlines()
        if ln.strip()
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_scores_each_user_against_their_own_profile(migrated_pg, tmp_path):
    """Two users sharing a posting each get their own skills_fit batch
    pointed at their own materialized profile."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")
        _seed_consolidated(conn, dedup_hash="h-shared", requested_by=[u1, u2])
        _seed_consolidated(conn, dedup_hash="h-alice", requested_by=[u1])

    _materialize_profile(tmp_path, "alice@example.com")
    _materialize_profile(tmp_path, "bob@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-shared", "fully_remote"),
            _classified("h-alice", "fully_remote"),
        ],
    )

    score_calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(score_calls),
        )

    assert summary["users_scored"] == 2
    assert summary["postings_scored"] == 3  # alice: 2, bob: 1

    by_email = {
        c["profile_file"].parts[-2]: c  # <run_id>/<slug>/candidate_profile.yml
        for c in score_calls
    }
    alice = by_email[_slug("alice@example.com")]
    bob = by_email[_slug("bob@example.com")]
    assert sorted(alice["hashes"]) == ["h-alice", "h-shared"]
    assert bob["hashes"] == ["h-shared"]
    assert alice["run_date"] == RUN_DATE
    # Produce-only: each user's survivors land in their own scored.jsonl.
    assert _scored_hashes(tmp_path, "alice@example.com") == ["h-alice", "h-shared"]
    assert _scored_hashes(tmp_path, "bob@example.com") == ["h-shared"]


@skip_if_no_docker
def test_gates_postings_by_each_users_remote_policy(migrated_pg, tmp_path):
    """A posting classified ``fully_remote`` reaches a user who accepts only
    that; a ``remote_with_frequent_travel`` posting is gated out for them."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "strict@example.com")
        _set_policy(conn, u1, ["fully_remote"])
        _seed_consolidated(conn, dedup_hash="h-ok", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-travel", requested_by=[u1])

    _materialize_profile(tmp_path, "strict@example.com")
    _write_classified(
        tmp_path,
        passed=[_classified("h-ok", "fully_remote")],
        trashed=[_classified("h-travel", "remote_with_frequent_travel")],
    )

    score_calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(score_calls),
        )

    assert summary["postings_scored"] == 1
    assert score_calls[0]["hashes"] == ["h-ok"]


@skip_if_no_docker
def test_default_policy_accepts_all_classifications(migrated_pg, tmp_path):
    """An empty/default policy is permissive — every classification passes."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "permissive@example.com")  # policies = {}
        _seed_consolidated(conn, dedup_hash="h1", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h2", requested_by=[u1])

    _materialize_profile(tmp_path, "permissive@example.com")
    _write_classified(
        tmp_path,
        passed=[_classified("h1", "fully_remote")],
        trashed=[_classified("h2", "remote_with_frequent_travel")],
    )

    score_calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(score_calls),
        )

    assert summary["postings_scored"] == 2


@skip_if_no_docker
def test_skips_user_with_no_surviving_postings(migrated_pg, tmp_path):
    """A user whose every posting is gated out is skipped — no skills_fit
    batch, no ingest — and counted in the summary."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "nomatch@example.com")
        _set_policy(conn, u1, ["fully_remote"])
        _seed_consolidated(conn, dedup_hash="h-travel", requested_by=[u1])

    _materialize_profile(tmp_path, "nomatch@example.com")
    _write_classified(
        tmp_path, passed=[_classified("h-travel", "remote_with_frequent_travel")]
    )

    score_calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(score_calls),
        )

    assert summary["users_scored"] == 0
    assert summary["users_skipped_no_postings"] == 1
    assert score_calls == []
    # No input or scored file written for a skipped user.
    assert not (skills_fit_dir(tmp_path, "nomatch@example.com", RUN_ID)).exists()


@skip_if_no_docker
def test_counts_postings_with_no_classification(migrated_pg, tmp_path):
    """A requested posting absent from the classified union (e.g. classifier
    dropped it) is counted as unclassified, not scored."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "gap@example.com")
        _seed_consolidated(conn, dedup_hash="h-have", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-missing", requested_by=[u1])

    _materialize_profile(tmp_path, "gap@example.com")
    _write_classified(tmp_path, passed=[_classified("h-have", "fully_remote")])

    score_calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(score_calls),
        )

    assert summary["postings_scored"] == 1
    assert summary["postings_unclassified"] == 1
    assert score_calls[0]["hashes"] == ["h-have"]


@skip_if_no_docker
def test_isolates_a_failing_user_and_finishes_the_rest(migrated_pg, tmp_path):
    """Spec §7: one user's skills_fit exception is isolated — logged,
    recorded ``failed`` in the summary — and the run finishes for everyone
    else. Here the failure surfaces as a missing materialized profile (a
    broken planner contract), but any raise inside the per-user step is
    treated the same way."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u_bad = seed_user(conn, "noprofile@example.com")
        u_ok = seed_user(conn, "fine@example.com")
        _seed_consolidated(conn, dedup_hash="h-bad", requested_by=[u_bad])
        _seed_consolidated(conn, dedup_hash="h-ok", requested_by=[u_ok])

    _materialize_profile(tmp_path, "fine@example.com")
    # deliberately do NOT materialize noprofile@example.com's profile
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-bad", "fully_remote"),
            _classified("h-ok", "fully_remote"),
        ],
    )

    score_calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(score_calls),
        )

    assert summary["users_scored"] == 1
    assert summary["users_failed"] == 1
    # The good user still got scored — their scored.jsonl is written.
    assert _scored_hashes(tmp_path, "fine@example.com") == ["h-ok"]
    failed = [u for u in summary["per_user"] if u.get("failed")]
    assert len(failed) == 1
    assert failed[0]["email"] == "noprofile@example.com"
    assert "profile" in failed[0]["error"]
