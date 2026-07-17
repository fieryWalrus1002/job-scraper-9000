from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime
from typing import Any, Literal, get_args

# Bump SCHEMA_VERSION (semver) when SkillsFitAnalysis fields change in a way
# that makes old eval records structurally incompatible with new ones.
#
#   PATCH (1.0.x) — field description text changed; no structural impact
#   MINOR (1.x.0) — new optional field added; old records missing it are still valid
#   MAJOR (x.0.0) — field removed, renamed, or type changed (including adding or
#                   removing a value from FitScore or Confidence); old records may
#                   fail validation against the new schema
SCHEMA_VERSION = "1.0.0"

FitScore = Literal[1, 2, 3, 4, 5]
Confidence = Literal["low", "medium", "high"]
InputSource = Literal["remote_filter_pass", "local_candidate"]
# Echoes the stored remote_filter classification onto ScoredJobPosting for
# display. Kept a SUPERSET: the canonical 4-way taxonomy is
# remote/hybrid/onsite/unclear (specs/remote_filter_taxonomy.md); legacy labels
# (fully_remote, onsite_disguised, location_restricted, remote_with_*_travel)
# are no longer produced but historical job rows still carry them and must
# validate here.
RemoteClassification = Literal[
    "remote",  # canonical (taxonomy)
    "onsite",  # canonical (taxonomy)
    "hybrid",  # canonical
    "unclear",  # canonical
    "fully_remote",  # legacy → remote
    "onsite_disguised",  # legacy → onsite
    "location_restricted",  # legacy → remote
    "remote_with_quarterly_travel",  # legacy (pre-3.0)
    "remote_with_monthly_travel",  # legacy
    "remote_with_frequent_travel",  # legacy
]

FIT_SCORES: list[int] = list(get_args(FitScore))
CONFIDENCE_LEVELS: list[str] = list(get_args(Confidence))


class SkillsFitAnalysis(BaseModel):
    """Structured analysis of how well a job posting matches the candidate profile.

    Band definitions live in the system prompt and the Calibration section of
    specs/skills_fit_agent_plan.md — kept terse here to avoid duplication drift.
    """

    fit_score: FitScore = Field(
        description=(
            "1 = reject; 2 = weak fit; 3 = possible fit; "
            "4 = good fit; 5 = strong fit. "
            "Score core-requirement coverage, not raw JD-line overlap."
        )
    )

    confidence: Confidence = Field(
        description=(
            "How confident the model is that the posting contains enough reliable "
            "information to judge the fit. low = vague/contradictory JD; high = clear and specific."
        ),
    )

    score_rationale: str = Field(
        description=(
            "Concise evidence-based explanation of the score. "
            "Identify the core matches, material gaps, and why this score band was chosen. "
            "Not a step-by-step CoT — an auditable summary suitable for the review UI and mismatch logs."
        ),
    )

    top_matches: list[str] = Field(
        default_factory=list,
        description="2-5 specific overlaps between the posting and the candidate profile (skills, domain, level).",
    )

    gaps: list[str] = Field(
        default_factory=list,
        description="2-5 missing requirements, weak matches, or role misalignments. Required for scores 1-4.",
    )

    hard_concerns: list[str] = Field(
        default_factory=list,
        description=(
            "Hard or near-hard blockers — clearance, location, credential, seniority, salary, "
            "work authorization, contract type. Dispatcher uses this to filter/flag even high-scoring matches."
        ),
    )

    core_job_duties: list[str] = Field(
        default_factory=list,
        description=(
            "The 4-5 most important job duties or responsibilities, ideally quoted verbatim from the JD. Used in"
            "mismatch analysis and review UI to focus attention on the heart of the role."
        ),
    )


class JobMetadata(BaseModel):
    run_id: str
    scored_at: datetime
    config_file: str
    prompt_file: str
    prompt_hash: str
    profile_file: str
    profile_hash: str
    profile_version: str
    provider: str
    model: str
    temperature: float | None = None
    skills_fit_schema_version: str = SCHEMA_VERSION
    commit: str
    dirty: bool
    input_source: InputSource
    input_path: str
    failure_reason: str | None = None


class ScoredJobPosting(BaseModel):
    dedup_hash: str
    source: str | None = None
    source_job_id: str | None = None
    source_url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    posted_at: date | None = None
    description: str | None = None
    scraped_at: datetime | None = None
    remote_classification: RemoteClassification | None = None
    salary_min_usd: int | None = None
    salary_max_usd: int | None = None
    salary_period: str | None = None
    pipeline_metadata: dict[str, Any] = Field(default_factory=dict)
    ai_fit: SkillsFitAnalysis | None = None
    metadata: JobMetadata

    @field_validator("posted_at", mode="before")
    @classmethod
    def coerce_nan_date(cls, v: object) -> object:
        return None if v in (None, "", "nan") else v

    @field_validator("location", mode="before")
    @classmethod
    def coerce_empty_location(cls, v: object) -> object:
        return v if v else None
