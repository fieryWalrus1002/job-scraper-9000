"""Unit tests for the eval corrections export script.

Focused on the pure record-shaping logic (build_gold_record). The DB I/O
path is left to manual integration testing — exercising it would require
either a real Postgres or a heavier mock that doesn't add much value over
the API tests in tests/api/test_eval_corrections.py.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_eval_corrections import _json_default, build_gold_record  # noqa: E402


def _make_row(**overrides) -> dict:
    base = {
        "dedup_hash": "deadbeef" * 8,
        "corrected_score": 2,
        "correction_reason": "Overweighted FPGA exp; firmware-adjacent only.",
        "original_score": 4,
        "original_model": "gpt-4o-mini",
        "profile_version": "v6",
        "corrected_at": datetime(2026, 6, 3, 18, 45),
        # ── job context ──
        "source": "sel",
        "source_job_id": "2026-20441",
        "source_url": "https://example.com/jobs/2026-20441",
        "title": "Senior Software Engineer",
        "company": "SEL",
        "location": "Pullman, WA",
        "posted_at": date(2026, 5, 28),
        "description": "Design firmware …",
        "scraped_at": datetime(2026, 6, 1, 8, 0),
        "remote_classification": "location_restricted",
        "salary_min_usd": 130000,
        "salary_max_usd": 180000,
        "salary_period": "yearly",
        # ── AI scoring output ──
        "fit_score": 4,
        "confidence": "medium",
        "score_rationale": "Strong on Python; some firmware crossover.",
        "ai_fit_detail": {
            "top_matches": ["Python", "embedded"],
            "gaps": ["FPGA depth"],
            "hard_concerns": [],
            "core_job_duties": ["firmware development"],
        },
        "run_id": "skillsfit_20260602_011412_c4f1",
        "scored_at": datetime(2026, 6, 2, 1, 14),
        "scored_model": "gpt-4o-mini",
        "provider": "openai",
        "scored_profile_version": "v6",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# build_gold_record
# ---------------------------------------------------------------------------


def test_build_gold_record_full_row() -> None:
    rec = build_gold_record(_make_row())

    # Scraped job context preserved
    assert rec["dedup_hash"] == "deadbeef" * 8
    assert rec["title"] == "Senior Software Engineer"
    assert rec["company"] == "SEL"
    assert rec["description"] == "Design firmware …"

    # AI output exposed under _skills_fit_*
    assert rec["_skills_fit_score"] == 4
    assert rec["_skills_fit_confidence"] == "medium"
    assert rec["_skills_fit_rationale"] == "Strong on Python; some firmware crossover."
    assert rec["_skills_fit_top_matches"] == ["Python", "embedded"]
    assert rec["_skills_fit_gaps"] == ["FPGA depth"]
    assert rec["_skills_fit_metadata"]["model"] == "gpt-4o-mini"

    # Human gold label from correction
    assert rec["_human_fit_score"] == 2
    assert rec["_human_notes"] == "Overweighted FPGA exp; firmware-adjacent only."
    assert rec["_human_source"] == "dashboard"
    # Unsupplied human fields default to empty
    assert rec["_human_confidence"] is None
    assert rec["_human_top_matches"] == []
    assert rec["_human_gaps"] == []
    assert rec["_human_hard_concerns"] == []

    # Correction snapshot
    assert rec["_correction_metadata"]["original_score"] == 4
    assert rec["_correction_metadata"]["original_model"] == "gpt-4o-mini"
    assert rec["_correction_metadata"]["profile_version"] == "v6"


def test_build_gold_record_missing_reason_uses_empty_string() -> None:
    rec = build_gold_record(_make_row(correction_reason=None))
    assert rec["_human_notes"] == ""


def test_build_gold_record_missing_ai_fit_detail() -> None:
    """Some jobs may have ai_fit_detail = None — defaults must be empty lists."""
    rec = build_gold_record(_make_row(ai_fit_detail=None))
    assert rec["_skills_fit_top_matches"] == []
    assert rec["_skills_fit_gaps"] == []
    assert rec["_skills_fit_hard_concerns"] == []
    assert rec["_skills_fit_core_job_duties"] == []


def test_build_gold_record_non_dict_ai_fit_detail_treated_as_empty() -> None:
    """Defensive: if ai_fit_detail is e.g. a string, treat as empty."""
    rec = build_gold_record(_make_row(ai_fit_detail="something weird"))
    assert rec["_skills_fit_top_matches"] == []


def test_build_gold_record_serialises_through_json_dumps() -> None:
    """The record (with datetime values) must round-trip through json.dumps
    using _json_default — the export writes JSONL with this helper."""
    rec = build_gold_record(_make_row())
    line = json.dumps(rec, default=_json_default)
    round_tripped = json.loads(line)
    assert round_tripped["dedup_hash"] == "deadbeef" * 8
    assert round_tripped["posted_at"] == "2026-05-28"
    assert round_tripped["scraped_at"].startswith("2026-06-01T08:00")
    assert round_tripped["_correction_metadata"]["corrected_at"].startswith(
        "2026-06-03T18:45"
    )


# ---------------------------------------------------------------------------
# _json_default
# ---------------------------------------------------------------------------


def test_json_default_handles_datetime() -> None:
    assert _json_default(datetime(2026, 6, 3, 18, 45)) == "2026-06-03T18:45:00"


def test_json_default_handles_date() -> None:
    assert _json_default(date(2026, 5, 28)) == "2026-05-28"


def test_json_default_rejects_unknown_types() -> None:
    with pytest.raises(TypeError):
        _json_default(object())
