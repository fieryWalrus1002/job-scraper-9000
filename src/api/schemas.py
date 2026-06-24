from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field


class JobSummary(BaseModel):
    dedup_hash: str
    source: str | None
    source_url: str | None
    title: str | None
    company: str | None
    location: str | None
    posted_at: date | None
    remote_classification: str | None
    salary_min_usd: int | None
    salary_max_usd: int | None
    salary_period: str | None
    fit_score: int | None
    confidence: str | None
    score_rationale: str | None
    failure_reason: str | None
    scored_at: datetime


class AiFitDetail(BaseModel):
    fit_score: int | None = None
    confidence: str | None = None
    score_rationale: str | None = None
    top_matches: list[str] = []
    gaps: list[str] = []
    hard_concerns: list[str] = []
    core_job_duties: list[str] = []

    model_config = {"extra": "allow"}


class JobDetail(BaseModel):
    dedup_hash: str
    source: str | None
    source_job_id: str | None
    source_url: str | None
    title: str | None
    company: str | None
    location: str | None
    posted_at: date | None
    description: str | None
    scraped_at: datetime | None
    remote_classification: str | None
    salary_min_usd: int | None
    salary_max_usd: int | None
    salary_period: str | None
    fit_score: int | None
    confidence: str | None
    score_rationale: str | None
    ai_fit_detail: AiFitDetail | None
    pipeline_metadata: dict[str, Any]
    run_id: str
    scored_at: datetime
    model: str
    provider: str
    profile_version: str
    failure_reason: str | None
    metadata: dict[str, Any]
    ingested_at: datetime


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[JobSummary]


ApplicationStatus = Literal[
    "maybe",
    "to_apply",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "candidate_withdrew",
    "hired",
    "ghosted",
    "passed",
]

APPLICATION_STATUSES: tuple[str, ...] = get_args(ApplicationStatus)


class LatestEvent(BaseModel):
    """Most-recent activity for a job — display-only summary for the
    Tracking list. Inert: rendered, never queried."""

    kind: Literal["status_change", "event"]
    occurred_at: datetime
    body: str | None = None  # note text; null for status_change
    to_status: ApplicationStatus | None = None  # null for events


class Application(BaseModel):
    dedup_hash: str
    status: ApplicationStatus
    applied_at: date | None
    created_at: datetime
    updated_at: datetime
    # joined from raw.job_postings + the user's own raw.job_scores row
    title: str | None = None
    company: str | None = None
    fit_score: int | None = None
    source_url: str | None = None
    latest_event: LatestEvent | None = None


class ApplicationCreate(BaseModel):
    dedup_hash: str
    status: ApplicationStatus = "maybe"
    applied_at: date | None = None


class ManualJobCreate(BaseModel):
    title: str
    fit_score: int = Field(ge=1, le=5)
    company: str | None = None
    source_url: str | None = None
    description: str | None = None
    location: str | None = None
    posted_at: date | None = None
    status: ApplicationStatus = "maybe"


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    applied_at: date | None = None


# ---------------------------------------------------------------------------
# Eval corrections — dashboard-sourced gold set for skills_fit
# ---------------------------------------------------------------------------


class EvalCorrectionIn(BaseModel):
    dedup_hash: str
    corrected_score: int = Field(ge=1, le=5)
    correction_reason: str | None = None


class EvalCorrectionOut(BaseModel):
    dedup_hash: str
    corrected_score: int
    correction_reason: str | None
    # snapshot at correction time — what the AI thought when the human corrected
    original_score: int | None
    original_model: str
    profile_version: str
    corrected_at: datetime


# ---------------------------------------------------------------------------
# Users — multi-user phase (app.users)
# ---------------------------------------------------------------------------


class User(BaseModel):
    id: UUID
    email: str
    display_name: str | None = None
    role: Literal["admin", "member"]


# ---------------------------------------------------------------------------
# Application events — activity log (app.application_events)
# ---------------------------------------------------------------------------


class StatusChangeEvent(BaseModel):
    """Auto-emitted on every status transition. {from, to} is load-bearing
    for Phase 21 alerts (derive timing from it)."""

    kind: Literal["status_change"] = "status_change"
    from_status: ApplicationStatus | None = Field(default=None, alias="from")
    to_status: ApplicationStatus = Field(alias="to")
    # Omitted → DB default now() (auto-events are not backdatable, set by the caller).
    occurred_at: datetime | None = None

    model_config = {"populate_by_name": True}


class GenericEvent(BaseModel):
    """Free-form event — meaning carried by tags[] (ECS-style)."""

    kind: Literal["event"] = "event"
    body: str | None = None
    tags: list[str] = []
    metadata: dict[str, object] = {}
    # Omitted → DB default now(); set explicitly to backdate a manual note (§3.2.3).
    occurred_at: datetime | None = None


# Discriminated union — importable by #380 (endpoints) directly
ApplicationEventPayload = Annotated[
    StatusChangeEvent | GenericEvent,
    Field(discriminator="kind"),
]


class ApplicationEventUpdate(BaseModel):
    """PATCH payload — all fields optional; only those set are written
    (``model_dump(exclude_unset=True)``). Typed so bad shapes fail at the edge."""

    occurred_at: datetime | None = None
    body: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None


class ApplicationEvent(BaseModel):
    """Full output model returned by the API (all stored columns)."""

    id: UUID
    dedup_hash: str
    kind: Literal["status_change", "event"]
    occurred_at: datetime
    body: str | None
    tags: list[str]
    metadata: dict[str, object]
    created_at: datetime


# ---------------------------------------------------------------------------
# Upcoming steps — alert output models
# ---------------------------------------------------------------------------


class StaleToApplyAlertOut(BaseModel):
    """Jobs sitting in *to_apply* longer than threshold without moving to *applied*."""

    kind: Literal["stale_to_apply"] = "stale_to_apply"
    message: str
    count: int
    dedup_hashes: list[str]
    days: int


class PostInterviewAlertOut(BaseModel):
    """Jobs that entered *interview* and haven't progressed past threshold."""

    kind: Literal["post_interview"] = "post_interview"
    message: str
    count: int
    dedup_hashes: list[str]
    days: int


class InactivityAlertOut(BaseModel):
    """No *applied* event across the pipeline for > threshold days."""

    kind: Literal["inactivity"] = "inactivity"
    message: str
    days: int


class PostApplicationAlertOut(BaseModel):
    """Jobs in *applied*/*screening* with no follow-up for > threshold days."""

    kind: Literal["post_application"] = "post_application"
    message: str
    count: int
    dedup_hashes: list[str]
    days: int


UpcomingStepAlert = Annotated[
    StaleToApplyAlertOut
    | PostInterviewAlertOut
    | InactivityAlertOut
    | PostApplicationAlertOut,
    Field(discriminator="kind"),
]


class UpcomingStepsResponse(BaseModel):
    """List of time-based alerts derived from the user's application events."""

    alerts: list[UpcomingStepAlert]
