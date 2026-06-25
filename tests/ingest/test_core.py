"""Unit tests for src/ingest/core.py pure functions — no DB required."""

from __future__ import annotations

from datetime import date

import json
from unittest.mock import MagicMock

import pytest

from ingest.core import _extract_row, _strip_nul, resolve_user_ids


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
    assert "fit_score" not in detail
    assert "confidence" not in detail
    assert "score_rationale" not in detail
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
    assert "run_id" not in leftover
    assert "model" not in leftover


def test_extract_row_pipeline_metadata_json() -> None:
    row = _extract_row(_make_record())
    pm = json.loads(row["pipeline_metadata"])
    assert pm["prefilter_result"] == "remote_filter_candidate"


def test_extract_row_carries_user_email() -> None:
    row = _extract_row(_make_record(user_email="friend@example.com"))
    assert row["user_email"] == "friend@example.com"


def test_extract_row_posted_at_present() -> None:
    row = _extract_row(_make_record())
    assert row["posted_at"] == "2026-05-01"


def test_extract_row_posted_at_missing_falls_back_to_scraped_at() -> None:
    record = _make_record()
    del record["posted_at"]
    row = _extract_row(record)
    assert row["posted_at"] == "2026-05-31T08:00:00Z"


def test_extract_row_posted_at_empty_string_falls_back_to_scraped_at() -> None:
    row = _extract_row(_make_record(posted_at=""))
    assert row["posted_at"] == "2026-05-31T08:00:00Z"


def test_extract_row_posted_at_both_missing_defaults_to_today() -> None:
    """When both posted_at and scraped_at are missing, default to today's
    date so the NOT NULL constraint on raw.job_postings.posted_at (#431) is
    never violated."""
    record = _make_record()
    del record["posted_at"]
    del record["scraped_at"]
    row = _extract_row(record)
    assert row["posted_at"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# _strip_nul
# ---------------------------------------------------------------------------


def test_strip_nul_removes_from_text_field() -> None:
    record = _make_record(description="Build\x00 great things.")
    row = _extract_row(record)
    assert "\x00" not in row["description"]
    assert row["description"] == "Build great things."


def test_strip_nul_removes_from_nested_jsonb_field() -> None:
    # Mirrors the real failure: NUL buried in ai_fit.top_matches lands in the
    # ai_fit_detail jsonb column as a U+0000 escape that Postgres rejects.
    record = _make_record()
    record["ai_fit"]["top_matches"] = ["Docker, CI/CD, and \x00*nix"]
    row = _extract_row(record)
    assert "\\u0000" not in row["ai_fit_detail"]
    detail = json.loads(row["ai_fit_detail"])
    assert detail["top_matches"] == ["Docker, CI/CD, and *nix"]


def test_strip_nul_warns_with_count(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    record = {"dedup_hash": "h1", "title": "a\x00b\x00c"}
    with caplog.at_level(logging.WARNING):
        _strip_nul(record)
    assert "Stripped 2 NUL byte(s)" in caplog.text
    assert "h1" in caplog.text


def test_strip_nul_noop_when_clean() -> None:
    record = _make_record()
    cleaned = _strip_nul(record)
    assert cleaned == record


# ---------------------------------------------------------------------------
# resolve_user_ids
# ---------------------------------------------------------------------------


def _conn_returning(email_id_pairs: list[tuple[str, str]]) -> MagicMock:
    """Fake psycopg connection whose cursor returns the given (email, id) rows."""
    cur = MagicMock()
    cur.fetchall.return_value = email_id_pairs
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cur)
    cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cm
    return conn


def test_resolve_user_ids_attaches_ids() -> None:
    rows = [
        {"dedup_hash": "h1", "user_email": "A@Example.com"},
        {"dedup_hash": "h2", "user_email": None},
    ]
    conn = _conn_returning([("a@example.com", "id-a"), ("default@example.com", "id-d")])

    resolve_user_ids(conn, rows, default_user_email="default@example.com")

    assert rows[0]["user_id"] == "id-a"  # lowercased before lookup
    assert rows[1]["user_id"] == "id-d"  # default filled the gap


def test_resolve_user_ids_fails_without_email_or_default() -> None:
    rows = [{"dedup_hash": "h1", "user_email": None}]
    with pytest.raises(ValueError, match="no user_email"):
        resolve_user_ids(_conn_returning([]), rows, default_user_email=None)


def test_resolve_user_ids_fails_on_unknown_email() -> None:
    rows = [{"dedup_hash": "h1", "user_email": "ghost@example.com"}]
    with pytest.raises(ValueError, match="ghost@example.com"):
        resolve_user_ids(_conn_returning([]), rows, default_user_email=None)
