from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


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
    ai_fit_detail: dict[str, Any] | None
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
