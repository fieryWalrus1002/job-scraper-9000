"""Unit tests for scripts/db_ingest.py pure functions.

Tests run without a database connection — only _extract_row,
resolve_input_path, and ingest(dry_run=True) are exercised here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# db_ingest.py lives in scripts/, not a package, so add it to sys.path via
# the import below (same pattern used inside the script itself).
import sys

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from db_ingest import _extract_row, resolve_input_path  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(**overrides) -> dict:
    base = {
        "dedup_hash": "abc123",
        "source": "linkedin",
        "source_job_id": "job-1",
        "source_url": "https://example.com/jobs/1",
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Remote, USA",
        "posted_at": "2026-05-01",
        "description": "Build great things.",
        "scraped_at": "2026-05-31T08:00:00Z",
        "remote_classification": "fully_remote",
        "ai_fit": {
            "fit_score": 4,
            "confidence": "high",
            "score_rationale": "Good match.",
            "top_matches": ["Python"],
            "gaps": ["Kubernetes"],
            "hard_concerns": [],
            "core_job_duties": ["write code"],
        },
        "pipeline_metadata": {"prefilter_result": "remote_filter_candidate"},
        "metadata": {
            "run_id": "run-xyz",
            "scored_at": "2026-06-01T12:00:00Z",
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "profile_version": "v2",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _extract_row
# ---------------------------------------------------------------------------


def test_extract_row_promotes_scalars() -> None:
    row = _extract_row(_make_record())
    assert row["dedup_hash"] == "abc123"
    assert row["fit_score"] == 4
    assert row["confidence"] == "high"
    assert row["score_rationale"] == "Good match."


def test_extract_row_promotes_metadata_fields() -> None:
    row = _extract_row(_make_record())
    assert row["run_id"] == "run-xyz"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["provider"] == "anthropic"
    assert row["profile_version"] == "v2"


def test_extract_row_ai_fit_detail_excludes_promoted_keys() -> None:
    row = _extract_row(_make_record())
    detail = json.loads(row["ai_fit_detail"])
    # fit_score, confidence, score_rationale are promoted — not in detail blob
    assert "fit_score" not in detail
    assert "confidence" not in detail
    assert "score_rationale" not in detail
    # non-promoted keys stay in the blob
    assert "top_matches" in detail
    assert "gaps" in detail


def test_extract_row_ai_fit_detail_none_when_only_promoted_keys() -> None:
    record = _make_record()
    record["ai_fit"] = {"fit_score": 3, "confidence": "low", "score_rationale": "Weak."}
    row = _extract_row(record)
    assert row["ai_fit_detail"] is None


def test_extract_row_missing_ai_fit_yields_none_scalars() -> None:
    record = _make_record()
    del record["ai_fit"]
    row = _extract_row(record)
    assert row["fit_score"] is None
    assert row["confidence"] is None
    assert row["score_rationale"] is None
    assert row["ai_fit_detail"] is None


def test_extract_row_null_ai_fit_yields_none_scalars() -> None:
    row = _extract_row(_make_record(ai_fit=None))
    assert row["fit_score"] is None


def test_extract_row_failure_reason_present() -> None:
    record = _make_record()
    record["metadata"]["failure_reason"] = "timeout"
    row = _extract_row(record)
    assert row["failure_reason"] == "timeout"


def test_extract_row_failure_reason_absent() -> None:
    row = _extract_row(_make_record())
    assert row["failure_reason"] is None


def test_extract_row_leftover_metadata_json() -> None:
    record = _make_record()
    record["metadata"]["extra_key"] = "extra_value"
    row = _extract_row(record)
    leftover = json.loads(row["metadata"])
    assert leftover["extra_key"] == "extra_value"
    # promoted keys should NOT appear in the leftover blob
    assert "run_id" not in leftover
    assert "model" not in leftover


def test_extract_row_pipeline_metadata_json() -> None:
    row = _extract_row(_make_record())
    pm = json.loads(row["pipeline_metadata"])
    assert pm["prefilter_result"] == "remote_filter_candidate"


# ---------------------------------------------------------------------------
# resolve_input_path
# ---------------------------------------------------------------------------


def test_resolve_with_run_date() -> None:
    path = resolve_input_path(run_date="2026-06-01", input_path=None)
    assert str(path) == "data/scored/2026-06-01/skills_fit_scored.jsonl"


def test_resolve_with_input_path() -> None:
    path = resolve_input_path(run_date=None, input_path="some/other.jsonl")
    assert str(path) == "some/other.jsonl"


def test_resolve_input_path_prefers_input_path_over_run_date() -> None:
    path = resolve_input_path(run_date="2026-06-01", input_path="explicit.jsonl")
    assert str(path) == "explicit.jsonl"


def test_resolve_raises_without_either() -> None:
    with pytest.raises(ValueError, match="--run-date or --input"):
        resolve_input_path(run_date=None, input_path=None)
