"""Pydantic models for the human-facing user config format (Phase 12).

These freeze the intake-template format (``config/job_search_template*.yml``,
``config/profile/candidate_profile.yml.template``) into validated models —
the single source of truth for the API settings endpoints, the push/pull
admin scripts, and (Phase 13) the queue builder.
See specs/configs_in_db_design.md §3.

Every model rejects unknown keys (``extra="forbid"``): these payloads are
hand-filled YAML or form output, and a typo'd key that validation silently
ignored would be a silent config no-op. Fail fast instead.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Mirrors the raw.remote_classification Postgres enum and the query Literal in
# api/routes/jobs.py. Deliberately a SUPERSET: the canonical taxonomy is the
# 3-way axis remote/hybrid/onsite (specs/remote_filter_taxonomy.md), while legacy
# labels remain valid so stored user policies and historical job rows still
# validate. Phase 32 (#524) retired ``unclear`` from the classifier axis, so it
# is legacy here too. New intent (derive_policies) emits only canonical values.
RemoteClassification = Literal[
    "remote",  # canonical (taxonomy)
    "onsite",  # canonical (taxonomy)
    "hybrid",  # canonical
    "unclear",  # legacy (Phase 32) — retired from classifier axis
    "fully_remote",  # legacy → remote
    "onsite_disguised",  # legacy → onsite
    "location_restricted",  # legacy → remote
    "remote_with_quarterly_travel",  # legacy (pre-3.0)
    "remote_with_monthly_travel",  # legacy
    "remote_with_frequent_travel",  # legacy
]

REMOTE_CLASSIFICATIONS: tuple[RemoteClassification, ...] = get_args(
    RemoteClassification
)

# Non-canonical remote classifications retained for stored policies and
# historical rows, but not emitted by derive_policies for new user intent.
LEGACY_REMOTE_CLASSIFICATIONS: tuple[RemoteClassification, ...] = (
    "unclear",
    "fully_remote",
    "onsite_disguised",
    "location_restricted",
    "remote_with_quarterly_travel",
    "remote_with_monthly_travel",
    "remote_with_frequent_travel",
)

# Keys of job_scraper JOBTYPE_MAP — duplicated as a Literal rather than
# imported so user_config stays decoupled from the scraper package (#91
# direction); the transform contract tests run load_config() over our output,
# which catches any drift loudly.
EmploymentType = Literal["fulltime", "parttime", "contract"]

# LinkedIn salary-floor buckets (in $k) the scraper's f_SB2 filter supports.
# Duplicated from job_scraper.config._VALID_SALARY_K (keys of
# query.SALARY_FLOOR // 1000) to keep user_config decoupled from the scraper
# package, mirroring EmploymentType above. tests/user_config asserts the two
# stay in sync, so a new scraper tier fails loudly here.
SalaryFloorK = Literal[40, 60, 80, 100, 120]

# LinkedIn experience-level codes (f_E param): 1=intern 2=entry 3=assoc
# 4=mid-senior 5=director 6=exec. The default mirrors the scraper's
# _LinkedInSection.experience default ("2,3,4,5").
LinkedInExperienceCode = Literal["1", "2", "3", "4", "5", "6"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Search config (job_search_template*.yml shape)
# ---------------------------------------------------------------------------


class HomeLocation(_Strict):
    city: str
    region: str
    country: str = "US"


class UserSection(_Strict):
    display_name: str
    email: str
    home_location: HomeLocation | None = None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError(f"not a plausible email address: {v!r}")
        return v


class SearchProfileMeta(_Strict):
    name: str
    status: Literal["active", "paused"] = "active"
    goal_summary: str = ""
    search_mode: Literal["focused", "balanced", "broad"] = "balanced"


class TargetTitles(_Strict):
    preferred: list[str] = Field(min_length=1)
    exploratory: list[str] = Field(default_factory=list)


class Roles(_Strict):
    target_titles: TargetTitles
    excluded_titles: list[str] = Field(default_factory=list)


class WorkArrangement(_Strict):
    acceptable: bool = True
    preferred: bool = False
    required: bool = False


class WorkArrangements(_Strict):
    # Permissive defaults (spec §1.6): an unstated arrangement is acceptable.
    remote: WorkArrangement = Field(default_factory=WorkArrangement)
    hybrid: WorkArrangement = Field(default_factory=WorkArrangement)
    onsite: WorkArrangement = Field(default_factory=WorkArrangement)

    @model_validator(mode="after")
    def _at_least_one_acceptable(self) -> "WorkArrangements":
        if not (
            self.remote.acceptable or self.hybrid.acceptable or self.onsite.acceptable
        ):
            raise ValueError(
                "no acceptable work arrangement — at least one of "
                "remote/hybrid/onsite must have acceptable: true"
            )
        return self


class EmploymentTypes(_Strict):
    acceptable: list[EmploymentType] = Field(
        default_factory=lambda: ["fulltime"], min_length=1
    )


class WorkConstraints(_Strict):
    employment_types: EmploymentTypes = Field(default_factory=EmploymentTypes)
    work_arrangements: WorkArrangements = Field(default_factory=WorkArrangements)
    # Retained travel tolerance input for back-compat. derive_policies still
    # threads it into policies.remote.max_travel_days so stored policy blobs
    # keep validating, but travel is display-only and no longer gated per
    # specs/remote_filter_taxonomy.md decision 2.
    max_travel_days: int | None = Field(default=None, ge=0, le=365)


class Location(_Strict):
    city: str
    region: str
    country: str = "US"


class Relocation(_Strict):
    willing: bool = False


class Locations(_Strict):
    acceptable: list[Location] = Field(default_factory=list)
    preferred: list[Location] = Field(default_factory=list)
    excluded: list[Location] = Field(default_factory=list)
    relocation: Relocation = Field(default_factory=Relocation)


class Organizations(_Strict):
    target_companies: list[str] = Field(default_factory=list)
    similar_to: list[str] = Field(default_factory=list)
    preferred_organization_types: list[str] = Field(default_factory=list)


class IndustriesAndDomains(_Strict):
    preferred: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


class Keywords(_Strict):
    required_any: list[str] = Field(default_factory=list)
    required_all: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


class ScrapePreferences(_Strict):
    include_remote_national_searches: bool = True
    include_local_searches: bool = True
    include_company_board_searches: bool = True
    include_general_job_boards: bool = True
    max_results_per_task: int = Field(default=50, ge=1, le=200)
    freshness_hours: int = Field(default=48, ge=1, le=24 * 31)
    cadence: Literal["daily", "weekly"] = "daily"
    # LinkedIn-only scrape filters. salary_floor_k None = no floor; the empty
    # experience list = fall back to the scraper's default (see transform).
    salary_floor_k: SalaryFloorK | None = None
    linkedin_experience_codes: list[LinkedInExperienceCode] = Field(
        default_factory=lambda: ["2", "3", "4", "5"]
    )


class SearchConfigInput(_Strict):
    """One user's filled-in job_search_template.yml."""

    user: UserSection
    search_profile: SearchProfileMeta
    roles: Roles
    work_constraints: WorkConstraints = Field(default_factory=WorkConstraints)
    locations: Locations = Field(default_factory=Locations)
    organizations: Organizations = Field(default_factory=Organizations)
    industries_and_domains: IndustriesAndDomains = Field(
        default_factory=IndustriesAndDomains
    )
    keywords: Keywords = Field(default_factory=Keywords)
    scrape_preferences: ScrapePreferences = Field(default_factory=ScrapePreferences)


# ---------------------------------------------------------------------------
# Candidate profile (candidate_profile.yml.template shape)
# ---------------------------------------------------------------------------


class Constraints(_Strict):
    hard: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)


class EvidenceProject(BaseModel):
    # Evidence sections are stored, not yet consumed by the pipeline, so they
    # validate loosely (extra allowed) while the shape settles.
    model_config = ConfigDict(extra="allow")
    name: str
    summary: str = ""
    evidence_of: list[str] = Field(default_factory=list)


class EvidenceWriting(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str
    evidence_of: list[str] = Field(default_factory=list)


class EvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    evidence_of: list[str] = Field(default_factory=list)


class Evidence(_Strict):
    projects: list[EvidenceProject] = Field(default_factory=list)
    publications_or_writing_samples: list[EvidenceWriting] = Field(default_factory=list)
    engineering_artifacts: list[EvidenceArtifact] = Field(default_factory=list)


class CandidateProfileInput(_Strict):
    """One user's filled-in candidate_profile.yml.template.

    ``profile_version`` is accepted (the template carries the field, so
    filled-in copies will have it) but ignored everywhere: the authoritative
    version is the content hash computed on save (spec §2).

    ``evidence`` and ``scoring_notes`` are stored but not yet emitted into
    the pipeline profile — wiring them into the skills_fit prompt is a
    scoring-contract change that needs its own eval pass.
    """

    profile_version: str | None = None
    summary: str = Field(min_length=20)
    level: str = Field(min_length=10)
    education: list[str] = Field(default_factory=list)
    core_skills: list[str] = Field(min_length=1)
    adjacent_skills: list[str] = Field(default_factory=list)
    growth_skills: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    avoided_domains: list[str] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    evidence: Evidence | None = None
    scoring_notes: str | None = None


# ---------------------------------------------------------------------------
# Per-user policies (spec §6) — derived from the search config, stored in
# user_search_configs.policies. Empty/default = permissive.
# ---------------------------------------------------------------------------


class RemotePolicy(_Strict):
    acceptable_classifications: list[RemoteClassification] = Field(
        default_factory=lambda: list(REMOTE_CLASSIFICATIONS)
    )
    # Derived from work_constraints.max_travel_days for back-compat, but no
    # longer gated: travel is display-only per
    # specs/remote_filter_taxonomy.md decision 2. Retained so stored policies
    # blobs still validate under extra="forbid".
    max_travel_days: int | None = Field(default=None, ge=0, le=365)


class PrefilterPolicy(_Strict):
    excluded_title_terms: list[str] = Field(default_factory=list)
    # System defaults live in config/agent/companies_prefilter.yml. These are
    # deliberately optional so a user only overrides that system policy when
    # they need a hand-tuned companies-pool veto.
    embedding_veto_depth: float | None = Field(default=None, ge=0, le=1)
    embedding_veto_enabled: bool | None = None

    @field_validator("embedding_veto_depth", mode="before")
    @classmethod
    def _reject_bool_veto_depth(cls, value: object) -> object:
        # Pydantic would coerce YAML `true`/`false` to 1.0/0.0, silently turning
        # a fat-fingered depth into a full-pool (or no-op) veto. Fail fast.
        if isinstance(value, bool):
            raise ValueError(
                "embedding_veto_depth must be a number in [0, 1], not a boolean"
            )
        return value


class RelocationPolicy(_Strict):
    allow_required_relocation: bool = False
    allow_local_presence_required: bool = False
    acceptable_locations: list[Location] = Field(default_factory=list)


class UserPolicies(_Strict):
    remote: RemotePolicy = Field(default_factory=RemotePolicy)
    prefilter: PrefilterPolicy = Field(default_factory=PrefilterPolicy)
    relocation: RelocationPolicy = Field(default_factory=RelocationPolicy)
