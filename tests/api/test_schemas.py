"""Pydantic model validation tests for api.schemas."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from api.schemas import JobDetail, JobListResponse, JobSummary
from tests.api.conftest import FAKE_DETAIL_ROW, FAKE_JOB_ROW


# ---------------------------------------------------------------------------
# JobSummary
# ---------------------------------------------------------------------------


def test_job_summary_validates_full_row() -> None:
    s = JobSummary.model_validate(FAKE_JOB_ROW)
    assert s.dedup_hash == FAKE_JOB_ROW["dedup_hash"]
    assert s.fit_score == 4
    assert s.remote_classification == "fully_remote"
    assert s.confidence == "high"


def test_job_summary_allows_null_optional_fields() -> None:
    minimal = {
        "dedup_hash": "abc",
        "scored_at": datetime(2026, 6, 1),
        "source": None,
        "source_url": None,
        "title": None,
        "company": None,
        "location": None,
        "posted_at": None,
        "remote_classification": None,
        "salary_min_usd": None,
        "salary_max_usd": None,
        "salary_period": None,
        "fit_score": None,
        "confidence": None,
        "score_rationale": None,
        "failure_reason": None,
    }
    s = JobSummary.model_validate(minimal)
    assert s.fit_score is None
    assert s.title is None


def test_job_summary_requires_dedup_hash() -> None:
    data = {**FAKE_JOB_ROW}
    del data["dedup_hash"]
    with pytest.raises(ValidationError):
        JobSummary.model_validate(data)


def test_job_summary_requires_scored_at() -> None:
    data = {**FAKE_JOB_ROW}
    del data["scored_at"]
    with pytest.raises(ValidationError):
        JobSummary.model_validate(data)


def test_job_summary_parses_date_string() -> None:
    s = JobSummary.model_validate(FAKE_JOB_ROW)
    assert s.posted_at == date(2026, 5, 1)


# ---------------------------------------------------------------------------
# JobDetail
# ---------------------------------------------------------------------------


def test_job_detail_validates_full_row() -> None:
    d = JobDetail.model_validate(FAKE_DETAIL_ROW)
    assert d.dedup_hash == FAKE_DETAIL_ROW["dedup_hash"]
    assert d.source == "linkedin"
    assert d.model == "claude-sonnet-4-6"
    assert isinstance(d.ai_fit_detail, dict)
    assert isinstance(d.pipeline_metadata, dict)
    assert isinstance(d.metadata, dict)


def test_job_detail_ai_fit_detail_can_be_none() -> None:
    row = {**FAKE_DETAIL_ROW, "ai_fit_detail": None}
    d = JobDetail.model_validate(row)
    assert d.ai_fit_detail is None


def test_job_detail_requires_run_id() -> None:
    data = {**FAKE_DETAIL_ROW}
    del data["run_id"]
    with pytest.raises(ValidationError):
        JobDetail.model_validate(data)


# ---------------------------------------------------------------------------
# JobListResponse
# ---------------------------------------------------------------------------


def test_job_list_response_validates() -> None:
    items = [JobSummary.model_validate(FAKE_JOB_ROW)]
    resp = JobListResponse(total=1, limit=50, offset=0, items=items)
    assert resp.total == 1
    assert len(resp.items) == 1


def test_job_list_response_empty_items() -> None:
    resp = JobListResponse(total=0, limit=50, offset=0, items=[])
    assert resp.items == []
