"""Tests for pipeline.email_overnight — the email → blob pipeline composition.

The DB, LLM stages, and Chrome enrichment are all injected/mocked; these tests
assert the *wiring*: the scrape stage is written in the run layout, the job is
enqueued + marked succeeded, and the three overnight stages run for the email
run_id.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from job_scraper.models import JobPosting
from pipeline import email_overnight
from pipeline.email_overnight import EMAIL_SOURCE, run_email_pipeline


def _job(title="Civil Engineer") -> JobPosting:
    return JobPosting(
        source="ZipRecruiter_Email",
        source_job_id="id-" + title,
        source_url="https://www.ziprecruiter.com/km/x",
        title=title,
        company="Acme",
        location="Remote",
        posted_at="2026-06-17T00:00:00Z",
        description="real description",
        scraped_at="2026-06-18T00:00:00Z",
        enrichment_status="enriched",
    )


def _stage_mocks():
    return {
        "consolidate_fn": MagicMock(name="consolidate"),
        "classify_fn": MagicMock(name="classify"),
        "score_fn": MagicMock(name="score"),
    }


def test_composes_scrape_enqueue_and_stages(tmp_path):
    jobs = [_job("A"), _job("B")]
    run_dir = tmp_path / "run" / "slug"
    stages = _stage_mocks()

    with (
        patch.object(email_overnight, "enqueue", return_value="job-uuid") as mock_enq,
        patch.object(email_overnight, "mark_succeeded") as mock_mark,
    ):
        summary = run_email_pipeline(
            run_date="2026-06-18",
            user_email="me@example.com",
            runs_dir=tmp_path,
            run_id="2026-06-18T1200-email",
            conn=MagicMock(name="conn"),
            enrich_fn=lambda **kw: jobs,
            prepare_user_fn=lambda conn, **kw: ("user-uuid", run_dir),
            **stages,
        )

    # Scrape stage written in the worker's format under the run dir.
    scrape_file = run_dir / "scrape" / f"{EMAIL_SOURCE}.jsonl"
    lines = scrape_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["enrichment_status"] == "enriched"

    # Job recorded as a succeeded scrape so consolidation fans it in.
    mock_enq.assert_called_once()
    assert mock_enq.call_args.kwargs["source"] == EMAIL_SOURCE
    assert mock_enq.call_args.kwargs["user_id"] == "user-uuid"
    mock_mark.assert_called_once()
    assert mock_mark.call_args.kwargs["posting_count"] == 2

    # The three overnight stages run for this run_id.
    stages["consolidate_fn"].assert_called_once()
    assert (
        stages["consolidate_fn"].call_args.kwargs["run_id"] == "2026-06-18T1200-email"
    )
    stages["classify_fn"].assert_called_once_with(
        runs_dir=tmp_path, run_id="2026-06-18T1200-email"
    )
    assert stages["score_fn"].call_args.kwargs["run_date"] == "2026-06-18"

    assert summary["enriched"] == 2
    assert summary["scored_path"].endswith("scored.jsonl")


def test_no_enriched_jobs_skips_stages(tmp_path):
    run_dir = tmp_path / "run" / "slug"
    stages = _stage_mocks()

    with (
        patch.object(email_overnight, "enqueue") as mock_enq,
        patch.object(email_overnight, "mark_succeeded") as mock_mark,
    ):
        summary = run_email_pipeline(
            run_date="2026-06-18",
            user_email="me@example.com",
            runs_dir=tmp_path,
            run_id="2026-06-18T1200-email",
            conn=MagicMock(),
            enrich_fn=lambda **kw: [],
            prepare_user_fn=lambda conn, **kw: ("user-uuid", run_dir),
            **stages,
        )

    mock_enq.assert_not_called()
    mock_mark.assert_not_called()
    stages["consolidate_fn"].assert_not_called()
    stages["classify_fn"].assert_not_called()
    stages["score_fn"].assert_not_called()
    assert summary == {
        "run_id": "2026-06-18T1200-email",
        "enriched": 0,
        "scored_path": None,
    }


def test_enriched_input_bypasses_enrich_fn(tmp_path):
    """The score half of the seam: load enriched.jsonl instead of enriching."""
    from email_scraper.enrich_cli import write_enriched

    run_dir = tmp_path / "run" / "slug"
    enriched = tmp_path / "enriched.jsonl"
    write_enriched([_job("A"), _job("B")], enriched)

    enrich_fn = MagicMock(name="enrich_fn")  # must NOT be called
    stages = _stage_mocks()
    with (
        patch.object(email_overnight, "enqueue", return_value="job-uuid"),
        patch.object(email_overnight, "mark_succeeded"),
    ):
        summary = run_email_pipeline(
            run_date="2026-06-18",
            user_email="me@example.com",
            runs_dir=tmp_path,
            run_id="2026-06-18T1200-email",
            conn=MagicMock(),
            enriched_input=enriched,
            enrich_fn=enrich_fn,
            prepare_user_fn=lambda conn, **kw: ("user-uuid", run_dir),
            **stages,
        )

    enrich_fn.assert_not_called()
    assert summary["enriched"] == 2
    assert (run_dir / "scrape" / f"{EMAIL_SOURCE}.jsonl").exists()
    stages["score_fn"].assert_called_once()


def test_mints_email_suffixed_run_id(tmp_path):
    captured = {}

    def _capture_prepare(conn, **kw):
        captured["run_id"] = kw["run_id"]
        return ("user-uuid", tmp_path / "run" / "slug")

    run_email_pipeline(
        run_date="2026-06-18",
        user_email="me@example.com",
        runs_dir=tmp_path,
        conn=MagicMock(),
        enrich_fn=lambda **kw: [],
        prepare_user_fn=_capture_prepare,
        **_stage_mocks(),
    )

    assert captured["run_id"].startswith("2026-06-18T")
    assert captured["run_id"].endswith("-email")


# ---------------------------------------------------------------------------
# _load_user guards (fail fast on an unprovisioned user)
# ---------------------------------------------------------------------------


def _conn_with_rows(rows):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    return conn


def _user_row(**over):
    row = {
        "user_id": "u1",
        "email": "me@example.com",
        "profile_payload": {"x": 1},
        "profile_version": "v1",
        "search_payload": {"y": 2},
        "policies": None,
        "pipeline_enabled": True,
    }
    row.update(over)
    return row


def test_load_user_returns_match():
    conn = _conn_with_rows([_user_row()])
    assert email_overnight._load_user(conn, "me@example.com")["user_id"] == "u1"


def test_load_user_unknown_email_exits():
    conn = _conn_with_rows([_user_row()])
    with pytest.raises(SystemExit, match="No app.users row"):
        email_overnight._load_user(conn, "nobody@example.com")


def test_load_user_missing_profile_exits():
    conn = _conn_with_rows([_user_row(profile_payload=None)])
    with pytest.raises(SystemExit, match="missing a candidate profile"):
        email_overnight._load_user(conn, "me@example.com")


def test_load_user_disabled_exits():
    conn = _conn_with_rows([_user_row(pipeline_enabled=False)])
    with pytest.raises(SystemExit, match="pipeline_enabled=false"):
        email_overnight._load_user(conn, "me@example.com")
