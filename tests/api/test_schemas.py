"""Pydantic model validation tests for api.schemas."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from api.schemas import (
    ApplicationEvent,
    ApplicationEventPayload,
    GenericEvent,
    JobDetail,
    JobListResponse,
    JobSummary,
    StatusChangeEvent,
)
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
    assert d.ai_fit_detail is not None
    assert d.ai_fit_detail.top_matches == ["Python", "data pipelines"]
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


# ---------------------------------------------------------------------------
# Application events — discriminated union + alias round-trip
# ---------------------------------------------------------------------------


def test_status_change_event_from_to_aliases() -> None:
    """from/to JSON keys round-trip via from_status/to_status field aliases."""
    data = {"kind": "status_change", "from": "maybe", "to": "to_apply"}
    evt = StatusChangeEvent.model_validate(data)
    assert evt.from_status == "maybe"
    assert evt.to_status == "to_apply"

    # model_dump(by_alias=True) → keys are "from" / "to"
    dumped = evt.model_dump(by_alias=True)
    assert dumped["from"] == "maybe"
    assert dumped["to"] == "to_apply"


def test_status_change_event_from_can_be_none() -> None:
    """Initial transitions (e.g. job first tracked) have no prior status."""
    evt = StatusChangeEvent.model_validate({"to": "maybe"})
    assert evt.from_status is None
    assert evt.to_status == "maybe"


def test_status_change_event_invalid_status_rejected() -> None:
    with pytest.raises(ValidationError):
        StatusChangeEvent.model_validate({"to": "invalid_status"})


def test_generic_event_defaults() -> None:
    evt = GenericEvent.model_validate({"kind": "event"})
    assert evt.body is None
    assert evt.tags == []
    assert evt.metadata == {}


def test_generic_event_full() -> None:
    evt = GenericEvent.model_validate(
        {
            "kind": "event",
            "body": "Had a call with recruiter",
            "tags": ["contact", "phone"],
            "metadata": {"contact_email": "recruiter@example.com"},
        }
    )
    assert evt.body == "Had a call with recruiter"
    assert evt.tags == ["contact", "phone"]


def test_application_event_payload_discriminated_union() -> None:
    """The discriminated union routes on the kind field."""
    sc: ApplicationEventPayload = StatusChangeEvent.model_validate(
        {"from": "to_apply", "to": "applied"}
    )
    assert sc.kind == "status_change"
    assert sc.to_status == "applied"

    ge: ApplicationEventPayload = GenericEvent.model_validate(
        {"kind": "event", "tags": ["note"]}
    )
    assert ge.kind == "event"


def test_application_event_output_model() -> None:
    from uuid import uuid4

    uid = uuid4()
    now = datetime(2026, 6, 23, 12, 0, 0)
    evt = ApplicationEvent(
        id=uid,
        dedup_hash="abc123",
        kind="status_change",
        occurred_at=now,
        body=None,
        tags=[],
        metadata={"from": "maybe", "to": "to_apply"},
        created_at=now,
    )
    assert evt.id == uid
    assert evt.kind == "status_change"
