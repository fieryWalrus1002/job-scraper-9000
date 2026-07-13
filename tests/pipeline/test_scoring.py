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
import logging
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Json

from ingest.core import ingest, read_jsonl
from pipeline.consolidation import PASS_NAME, TRASH_NAME, consolidated_dir
from pipeline.planner import _slug
from pipeline.scoring import (
    SCORED_NAME,
    BatchScoreFns,
    _location_matches,
    iter_run_user_outputs,
    score_run,
    skills_fit_dir,
)
from user_config.models import Location

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


def _classified(
    dedup_hash: str, classification: str, *, travel_days: int | None = None
) -> dict:
    return {
        "dedup_hash": dedup_hash,
        "title": "Eng",
        "description": "d",
        "_remote_analysis": {
            "remote_classification": classification,
            "estimated_travel_days_per_year": travel_days,
        },
    }


def _set_policy(
    conn: psycopg.Connection,
    user_id: str,
    acceptable: list[str],
    *,
    max_travel_days: int | None = None,
) -> None:
    remote: dict = {"acceptable_classifications": acceptable}
    if max_travel_days is not None:
        remote["max_travel_days"] = max_travel_days
    conn.execute(
        "UPDATE app.user_search_configs SET policies = %s WHERE user_id = %s::uuid",
        (Json({"remote": remote}), user_id),
    )


def _classified_with_relocation(
    dedup_hash: str,
    classification: str,
    *,
    requires_relocation: bool = False,
    requires_local_presence: bool = False,
    location: str | None = None,
) -> dict:
    rec = {
        "dedup_hash": dedup_hash,
        "title": "Eng",
        "description": "d",
        "_remote_analysis": {
            "remote_classification": classification,
            "estimated_travel_days_per_year": None,
            "requires_relocation": requires_relocation,
            "requires_local_presence": requires_local_presence,
        },
    }
    if location is not None:
        rec["location"] = location
    return rec


def _set_full_policy(
    conn: psycopg.Connection,
    user_id: str,
    acceptable: list[str],
    *,
    max_travel_days: int | None = None,
    allow_required_relocation: bool = False,
    allow_local_presence_required: bool = False,
    acceptable_locations: list[dict] | None = None,
) -> None:
    remote: dict = {"acceptable_classifications": acceptable}
    if max_travel_days is not None:
        remote["max_travel_days"] = max_travel_days
    relocation: dict = {
        "allow_required_relocation": allow_required_relocation,
        "allow_local_presence_required": allow_local_presence_required,
    }
    if acceptable_locations is not None:
        relocation["acceptable_locations"] = acceptable_locations
    conn.execute(
        "UPDATE app.user_search_configs SET policies = %s WHERE user_id = %s::uuid",
        (
            Json(
                {
                    "remote": remote,
                    "relocation": relocation,
                }
            ),
            user_id,
        ),
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


class _FakeBatchSubmission:
    def __init__(
        self,
        *,
        hashes: list[str],
        input_path: Path,
        output_path: Path,
        batch_id: str | None,
    ) -> None:
        self.hashes = hashes
        self.input_path = input_path
        self.output_path = output_path
        self.batch_id = batch_id
        self.client = object()
        self.poll_interval = 0.01
        self.aborted: list[BaseException] = []

    def abort(self, exc: BaseException) -> None:
        self.aborted.append(exc)


def _batch_score_fns(
    events: list[tuple[str, tuple[str, ...]]],
    submissions: list[_FakeBatchSubmission],
    *,
    fail_submit_for: set[str] | None = None,
    fail_collect_for: set[str] | None = None,
    local_only_for: set[str] | None = None,
) -> BatchScoreFns:
    fail_submit_for = fail_submit_for or set()
    fail_collect_for = fail_collect_for or set()
    local_only_for = local_only_for or set()

    def _submit(*, input_path, output_path, profile_file, run_date, parent_run_id):
        lines = [ln for ln in input_path.read_text().splitlines() if ln.strip()]
        hashes = [json.loads(ln)["dedup_hash"] for ln in lines]
        events.append(("submit", tuple(hashes)))
        if fail_submit_for.intersection(hashes):
            raise RuntimeError(f"submit failed for {hashes}")
        batch_id = None if local_only_for.intersection(hashes) else f"batch-{hashes[0]}"
        submission = _FakeBatchSubmission(
            hashes=hashes,
            input_path=input_path,
            output_path=output_path,
            batch_id=batch_id,
        )
        submissions.append(submission)
        return submission

    def _collect(submission, batch):
        events.append(("collect", tuple(submission.hashes)))
        if fail_collect_for.intersection(submission.hashes):
            raise RuntimeError(f"collect failed for {submission.hashes}")
        lines = [
            ln for ln in submission.input_path.read_text().splitlines() if ln.strip()
        ]
        submission.output_path.write_text("".join(ln + "\n" for ln in lines))
        return {"scored": len(lines)}

    return BatchScoreFns(submit=_submit, collect=_collect)


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


def test_location_matches_requires_city_and_region_token():
    acceptable = [Location(city="Portland", region="OR", country="US")]

    assert _location_matches("Portland, OR", acceptable) is True
    assert _location_matches("Portland, ME", acceptable) is False
    assert _location_matches("Seattle, WA", acceptable) is False
    assert _location_matches("", acceptable) is False
    assert _location_matches(None, acceptable) is False


def test_location_matches_city_as_substring_region_as_token():
    acceptable = [Location(city="Seattle", region="WA", country="US")]

    assert _location_matches("Greater Seattle Area, WA", acceptable) is True
    assert _location_matches("Seattle, Washington", acceptable) is False


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
def test_two_phase_batch_submits_all_then_collects_in_user_order(
    migrated_pg, tmp_path, monkeypatch
):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")
        _seed_consolidated(conn, dedup_hash="h-alice", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-bob", requested_by=[u2])

    _materialize_profile(tmp_path, "alice@example.com")
    _materialize_profile(tmp_path, "bob@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-alice", "fully_remote"),
            _classified("h-bob", "fully_remote"),
        ],
    )

    events: list[tuple[str, tuple[str, ...]]] = []
    submissions: list[_FakeBatchSubmission] = []

    def fake_poll_all(client, batch_ids, poll_interval):
        events.append(("poll", tuple(batch_ids)))
        return {batch_id: object() for batch_id in batch_ids}

    monkeypatch.setattr("pipeline.scoring.poll_all_until_done", fake_poll_all)

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            batch_score_fns=_batch_score_fns(events, submissions),
        )

    assert summary["users_scored"] == 2
    assert summary["postings_scored"] == 2
    assert _scored_hashes(tmp_path, "alice@example.com") == ["h-alice"]
    assert _scored_hashes(tmp_path, "bob@example.com") == ["h-bob"]
    assert {
        r["user_email"] for r in _scored_records(tmp_path, "alice@example.com")
    } == {"alice@example.com"}
    assert {r["user_email"] for r in _scored_records(tmp_path, "bob@example.com")} == {
        "bob@example.com"
    }
    assert [event[0] for event in events] == [
        "submit",
        "submit",
        "poll",
        "collect",
        "collect",
    ]
    assert max(i for i, event in enumerate(events) if event[0] == "submit") < min(
        i for i, event in enumerate(events) if event[0] == "collect"
    )


@skip_if_no_docker
def test_two_phase_batch_isolates_submit_failure(migrated_pg, tmp_path, monkeypatch):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")
        _seed_consolidated(conn, dedup_hash="h-alice", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-bob", requested_by=[u2])

    _materialize_profile(tmp_path, "alice@example.com")
    _materialize_profile(tmp_path, "bob@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-alice", "fully_remote"),
            _classified("h-bob", "fully_remote"),
        ],
    )

    events: list[tuple[str, tuple[str, ...]]] = []
    submissions: list[_FakeBatchSubmission] = []
    monkeypatch.setattr(
        "pipeline.scoring.poll_all_until_done",
        lambda client, batch_ids, poll_interval: {
            batch_id: object() for batch_id in batch_ids
        },
    )

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            batch_score_fns=_batch_score_fns(
                events, submissions, fail_submit_for={"h-alice"}
            ),
        )

    assert summary["users_scored"] == 1
    assert summary["users_failed"] == 1
    assert _scored_hashes(tmp_path, "bob@example.com") == ["h-bob"]
    assert not (
        skills_fit_dir(tmp_path, "alice@example.com", RUN_ID) / SCORED_NAME
    ).exists()
    assert ("collect", ("h-bob",)) in events
    assert ("collect", ("h-alice",)) not in events


@skip_if_no_docker
def test_two_phase_batch_isolates_collect_failure(migrated_pg, tmp_path, monkeypatch):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")
        _seed_consolidated(conn, dedup_hash="h-alice", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-bob", requested_by=[u2])

    _materialize_profile(tmp_path, "alice@example.com")
    _materialize_profile(tmp_path, "bob@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-alice", "fully_remote"),
            _classified("h-bob", "fully_remote"),
        ],
    )

    events: list[tuple[str, tuple[str, ...]]] = []
    submissions: list[_FakeBatchSubmission] = []
    monkeypatch.setattr(
        "pipeline.scoring.poll_all_until_done",
        lambda client, batch_ids, poll_interval: {
            batch_id: object() for batch_id in batch_ids
        },
    )

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            batch_score_fns=_batch_score_fns(
                events, submissions, fail_collect_for={"h-alice"}
            ),
        )

    assert summary["users_scored"] == 1
    assert summary["users_failed"] == 1
    assert _scored_hashes(tmp_path, "bob@example.com") == ["h-bob"]
    by_hash = {submission.hashes[0]: submission for submission in submissions}
    assert len(by_hash["h-alice"].aborted) == 1
    assert by_hash["h-bob"].aborted == []


@skip_if_no_docker
def test_two_phase_batch_marks_pending_users_failed_when_polling_dies(
    migrated_pg, tmp_path, monkeypatch
):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")
        _seed_consolidated(conn, dedup_hash="h-alice", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-bob", requested_by=[u2])

    _materialize_profile(tmp_path, "alice@example.com")
    _materialize_profile(tmp_path, "bob@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-alice", "fully_remote"),
            _classified("h-bob", "fully_remote"),
        ],
    )

    events: list[tuple[str, tuple[str, ...]]] = []
    submissions: list[_FakeBatchSubmission] = []

    def fail_poll(client, batch_ids, poll_interval):
        raise RuntimeError("poll died")

    monkeypatch.setattr("pipeline.scoring.poll_all_until_done", fail_poll)

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            batch_score_fns=_batch_score_fns(events, submissions),
        )

    assert summary["users_scored"] == 0
    assert summary["users_failed"] == 2
    assert all(len(submission.aborted) == 1 for submission in submissions)
    assert [event for event in events if event[0] == "collect"] == []


@skip_if_no_docker
def test_two_phase_batch_summary_shape_matches_serial_path(
    migrated_pg, tmp_path, monkeypatch
):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        _seed_consolidated(conn, dedup_hash="h-alice", requested_by=[u1])

    _materialize_profile(tmp_path, "alice@example.com")
    _write_classified(tmp_path, passed=[_classified("h-alice", "fully_remote")])

    events: list[tuple[str, tuple[str, ...]]] = []
    submissions: list[_FakeBatchSubmission] = []
    monkeypatch.setattr(
        "pipeline.scoring.poll_all_until_done",
        lambda client, batch_ids, poll_interval: {
            batch_id: object() for batch_id in batch_ids
        },
    )

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            batch_score_fns=_batch_score_fns(events, submissions),
        )

    assert set(summary) == {
        "users_scored",
        "users_skipped_no_postings",
        "users_failed",
        "postings_scored",
        "postings_unclassified",
        "per_user",
    }


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
def test_gates_postings_by_each_users_max_travel_days(migrated_pg, tmp_path):
    """A fully_remote posting whose estimated travel exceeds the user's
    max_travel_days is dropped before skills_fit; one at/under it survives."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "lowtravel@example.com")
        _set_policy(conn, u1, ["fully_remote"], max_travel_days=15)
        _seed_consolidated(conn, dedup_hash="h-near", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-far", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-unknown", requested_by=[u1])

    _materialize_profile(tmp_path, "lowtravel@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified("h-near", "fully_remote", travel_days=15),
            _classified("h-far", "fully_remote", travel_days=40),
            # No numeric estimate → not dropped by the travel gate.
            _classified("h-unknown", "fully_remote", travel_days=None),
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

    assert summary["postings_scored"] == 2
    assert score_calls[0]["hashes"] == ["h-near", "h-unknown"]


@skip_if_no_docker
def test_no_max_travel_days_does_not_filter_on_travel(migrated_pg, tmp_path):
    """Unset max_travel_days preserves current behavior: a high-travel posting
    whose classification is acceptable is still scored."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "anytravel@example.com")
        _set_policy(conn, u1, ["fully_remote"])  # no max_travel_days
        _seed_consolidated(conn, dedup_hash="h-far", requested_by=[u1])

    _materialize_profile(tmp_path, "anytravel@example.com")
    _write_classified(
        tmp_path, passed=[_classified("h-far", "fully_remote", travel_days=200)]
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
    assert score_calls[0]["hashes"] == ["h-far"]


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


# ---------------------------------------------------------------------------
# Phase 15 G2 — user_email stamping + iter_run_user_outputs walk
# ---------------------------------------------------------------------------


def _scored_records(runs_dir: Path, email: str) -> list[dict]:
    path = skills_fit_dir(runs_dir, email, RUN_ID) / SCORED_NAME
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


@skip_if_no_docker
def test_stamps_user_email_into_scored_records(migrated_pg, tmp_path):
    """Every scored record carries its owning user_email so the file
    self-routes on ingest (Phase 15 G2) — even though the consolidated
    postings the scorer saw were profile-free."""
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

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory([]),
        )

    alice = _scored_records(tmp_path, "alice@example.com")
    bob = _scored_records(tmp_path, "bob@example.com")
    assert {r["user_email"] for r in alice} == {"alice@example.com"}
    assert {r["user_email"] for r in bob} == {"bob@example.com"}


@skip_if_no_docker
def test_iter_run_user_outputs_walks_a_run(migrated_pg, tmp_path):
    """The shared walk yields one (user_email, slug, scored_path) per user
    with scored output, reads user_email back from the stamped file, and
    skips the shared _consolidated stage dir."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        u2 = seed_user(conn, "bob@example.com")
        _seed_consolidated(conn, dedup_hash="h-shared", requested_by=[u1, u2])

    _materialize_profile(tmp_path, "alice@example.com")
    _materialize_profile(tmp_path, "bob@example.com")
    _write_classified(tmp_path, passed=[_classified("h-shared", "fully_remote")])

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory([]),
        )

    outputs = list(iter_run_user_outputs(tmp_path, RUN_ID))
    assert [o.user_email for o in outputs] == ["alice@example.com", "bob@example.com"]
    assert [o.slug for o in outputs] == [
        _slug("alice@example.com"),
        _slug("bob@example.com"),
    ]
    for o in outputs:
        assert (
            o.scored_path
            == skills_fit_dir(tmp_path, o.user_email, RUN_ID) / SCORED_NAME
        )
        assert o.scored_path.exists()


@skip_if_no_docker
def test_scored_records_round_trip_through_ingest(migrated_pg, tmp_path):
    """End-to-end of the self-routing contract: a stamped scored file ingests
    with no default user — each record routes to its own user purely on its
    embedded user_email (Phase 15 G2)."""

    def _scored_output_fn(
        *, input_path, output_path, profile_file, run_date, parent_run_id
    ):
        # Emit ingest-shaped records: the runner stamps metadata.scored_at,
        # which raw.job_scores requires NOT NULL.
        with output_path.open("w") as f:
            for ln in input_path.read_text().splitlines():
                if not ln.strip():
                    continue
                rec = json.loads(ln)
                rec["metadata"] = {"scored_at": "2026-06-12T00:00:00+00:00"}
                f.write(json.dumps(rec) + "\n")
        return {"scored": 0}

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

    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_scored_output_fn,
        )

    # Ingest each user's file with NO default_user_email — routing must come
    # entirely from the stamped records.
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        for out in iter_run_user_outputs(tmp_path, RUN_ID):
            ingest(read_jsonl(out.scored_path), conn=conn, default_user_email=None)

        rows = conn.execute(
            """
            SELECT u.email, s.dedup_hash
            FROM raw.job_scores s
            JOIN app.users u ON u.id = s.user_id
            ORDER BY u.email, s.dedup_hash
            """
        ).fetchall()

    assert set(rows) == {
        ("alice@example.com", "h-alice"),
        ("alice@example.com", "h-shared"),
        ("bob@example.com", "h-shared"),
    }


# ---------------------------------------------------------------------------
# Relocation gate tests
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_local_presence_gate_keeps_acceptable_location_when_unwilling(
    migrated_pg, tmp_path
):
    """willing=False: local-presence jobs in acceptable locations survive."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "alice@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=False,
            allow_local_presence_required=False,
            acceptable_locations=[{"city": "Seattle", "region": "WA", "country": "US"}],
        )
        _seed_consolidated(conn, dedup_hash="h-local", requested_by=[u1])

    _materialize_profile(tmp_path, "alice@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-local",
                "fully_remote",
                requires_local_presence=True,
                location="Seattle, WA",
            )
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 1
    assert calls[0]["hashes"] == ["h-local"]


@skip_if_no_docker
def test_local_presence_gate_drops_out_of_area_when_unwilling(
    migrated_pg, tmp_path, caplog
):
    """willing=False: local-presence jobs outside acceptable locations drop."""
    caplog.set_level(logging.INFO, logger="pipeline.scoring")
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "outofarea@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=False,
            allow_local_presence_required=False,
            acceptable_locations=[{"city": "Seattle", "region": "WA", "country": "US"}],
        )
        _seed_consolidated(conn, dedup_hash="h-portland", requested_by=[u1])

    _materialize_profile(tmp_path, "outofarea@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-portland",
                "fully_remote",
                requires_local_presence=True,
                location="Portland, OR",
            )
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 0
    assert summary["users_skipped_no_postings"] == 1
    assert calls == []
    assert "requires local presence outside acceptable locations" in caplog.text
    assert "1 local-presence-out-of-area" in caplog.text


@skip_if_no_docker
def test_local_presence_gate_no_acceptable_locations_logs_distinct_reason(
    migrated_pg, tmp_path, caplog
):
    """willing=False with an empty acceptable_locations set (e.g. a user whose
    policy predates the field) still drops local-presence jobs, but the drop is
    logged as a policy-data gap — not 'out of area' — so the fix (a settings
    re-save) is obvious (spec §8.5)."""
    caplog.set_level(logging.INFO, logger="pipeline.scoring")
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "nopolicy@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=False,
            allow_local_presence_required=False,
            # acceptable_locations omitted → empty set (pre-backfill user)
        )
        _seed_consolidated(conn, dedup_hash="h-seattle", requested_by=[u1])

    _materialize_profile(tmp_path, "nopolicy@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-seattle",
                "fully_remote",
                requires_local_presence=True,
                location="Seattle, WA",
            )
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 0
    assert summary["users_skipped_no_postings"] == 1
    assert calls == []
    assert "no acceptable locations in policy" in caplog.text
    assert "1 local-presence-no-policy" in caplog.text
    # A pre-backfill drop must NOT be mislabeled as out-of-area.
    assert "requires local presence outside acceptable locations" not in caplog.text


@skip_if_no_docker
def test_relocation_gate_still_drops_relocation_required_when_unwilling(
    migrated_pg, tmp_path, caplog
):
    """requires_relocation remains a clean veto for unwilling users."""
    caplog.set_level(logging.INFO, logger="pipeline.scoring")
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "relocation@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=False,
            allow_local_presence_required=False,
            acceptable_locations=[{"city": "Seattle", "region": "WA", "country": "US"}],
        )
        _seed_consolidated(conn, dedup_hash="h-relo", requested_by=[u1])
        _seed_consolidated(conn, dedup_hash="h-ok", requested_by=[u1])

    _materialize_profile(tmp_path, "relocation@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-relo", "fully_remote", requires_relocation=True
            ),
            _classified_with_relocation("h-ok", "fully_remote"),
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 1
    assert calls[0]["hashes"] == ["h-ok"]
    assert "relocation not allowed" in caplog.text


@skip_if_no_docker
def test_local_presence_gate_drops_missing_location_as_ambiguous(
    migrated_pg, tmp_path, caplog
):
    """willing=False: local-presence jobs with no posting location drop as ambiguous."""
    caplog.set_level(logging.INFO, logger="pipeline.scoring")
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "ambiguous@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=False,
            allow_local_presence_required=False,
            acceptable_locations=[{"city": "Seattle", "region": "WA", "country": "US"}],
        )
        _seed_consolidated(conn, dedup_hash="h-missing", requested_by=[u1])

    _materialize_profile(tmp_path, "ambiguous@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-missing", "fully_remote", requires_local_presence=True
            )
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 0
    assert summary["users_skipped_no_postings"] == 1
    assert calls == []
    assert "posting location missing/ambiguous" in caplog.text
    assert "1 local-presence-ambiguous" in caplog.text


@skip_if_no_docker
def test_local_presence_gate_passes_any_location_when_willing(migrated_pg, tmp_path):
    """willing=True: local-presence jobs survive regardless of posting location."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "willing@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=True,
            allow_local_presence_required=True,
            acceptable_locations=[{"city": "Seattle", "region": "WA", "country": "US"}],
        )
        _seed_consolidated(conn, dedup_hash="h-local", requested_by=[u1])

    _materialize_profile(tmp_path, "willing@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-local",
                "fully_remote",
                requires_local_presence=True,
                location="Portland, OR",
            )
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 1
    assert calls[0]["hashes"] == ["h-local"]


@skip_if_no_docker
def test_fully_remote_jobs_do_not_use_location_gate(migrated_pg, tmp_path):
    """Location only gates jobs flagged requires_local_presence."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        u1 = seed_user(conn, "remote@example.com")
        _set_full_policy(
            conn,
            u1,
            ["fully_remote"],
            allow_required_relocation=False,
            allow_local_presence_required=False,
            acceptable_locations=[{"city": "Seattle", "region": "WA", "country": "US"}],
        )
        _seed_consolidated(conn, dedup_hash="h-remote", requested_by=[u1])

    _materialize_profile(tmp_path, "remote@example.com")
    _write_classified(
        tmp_path,
        passed=[
            _classified_with_relocation(
                "h-remote", "fully_remote", location="Portland, OR"
            )
        ],
    )
    calls: list[dict] = []
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        summary = score_run(
            conn,
            run_id=RUN_ID,
            run_date=RUN_DATE,
            runs_dir=tmp_path,
            score_fn=_score_factory(calls),
        )
    assert summary["users_scored"] == 1
    assert calls[0]["hashes"] == ["h-remote"]
