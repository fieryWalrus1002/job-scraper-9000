from typing import Literal, get_args

from pydantic import BaseModel, Field

# Bump SCHEMA_VERSION (semver) when RemoteAnalysis fields change in a way that
# makes old eval records structurally incompatible with new ones.
# Prompt identity is tracked by hashing the prompt file on disk via
# utils.git_info.get_prompt_hash() — no manual constant to keep in sync.
# Bump SCHEMA_VERSION (semver) when RemoteAnalysis fields change in a way that
# makes old eval records structurally incompatible with new ones. Specifically:
#
#   PATCH (2.0.x) — field description text changed; no structural impact
#   MINOR (2.x.0) — new optional field added; old records missing it are still valid
#   MAJOR (x.0.0) — field removed, renamed, or type changed (including adding or
#                   removing a value from RemoteClassification); old records may
#                   fail validation against the new schema
#
# Do NOT bump for:
#   - Refactoring how the Literal or constants are expressed in code
#   - Changes to LEGACY_CLASSIFICATIONS (UI-only, never produced by the LLM)
#   - Prompt edits (prompt identity is tracked separately via prompt_hash)
SCHEMA_VERSION = "5.0.0"

# Remote-ness axis only. The LLM is a pure extractor: travel, geography,
# relocation, and local-presence details live in dedicated fields instead of
# classification buckets. See specs/remote_filter_taxonomy.md.
#
# 3-way as of Phase 32 (specs/remote_filter_classifier_tuning.md §2): `unclear`
# was retired — it conflated "posting states no location" (a prefilter/data
# concern) with model uncertainty, and its "surface borderline" role is now a
# gate decision, not a classifier label. Zero-signal postings get an honest home
# via the "named-city → onsite" rule (or are dropped upstream).
RemoteClassification = Literal[
    "remote",
    "hybrid",
    "onsite",
]

REMOTE_CLASSIFICATIONS: list[str] = list(get_args(RemoteClassification))

# Values the LLM no longer produces. RemoteAnalysis is strict (3-way axis), so
# these do NOT validate against RemoteAnalysis itself — they exist for
# back-compat consumers *outside* the strict schema: display/normalization code
# and reading historical eval records / DB rows that still carry them.
LEGACY_CLASSIFICATIONS: list[str] = [
    "unclear",  # retired Phase 32: no longer a classifier label (still on historical rows)
    "fully_remote",  # pre-taxonomy: renamed to "remote"
    "onsite_disguised",  # pre-taxonomy: collapsed into "onsite"
    "location_restricted",  # pre-taxonomy: folded into "remote" + location_restrictions
    "remote_with_quarterly_travel",  # pre-3.0: travel collapsed into numeric days
    "remote_with_monthly_travel",  # pre-3.0
    "remote_with_frequent_travel",  # pre-3.0
    "remote_with_occasional_travel",  # pre-2.0 teacher runs
]


class RemoteAnalysis(BaseModel):
    """Structured analysis of a job posting's remote work policy."""

    reasoning_trace: str = Field(
        description="Step-by-step logic: quote the posting, analyze location/travel, and debate any ambiguity.",
    )

    remote_classification: "RemoteClassification"

    estimated_travel_days_per_year: int | None = Field(
        None,
        description="Best estimate of travel days/year. None if not determinable.",
    )

    location_restrictions: list[str] = Field(
        default_factory=list,
        description="E.g. 'US-only', 'must reside in CA/NY/TX', 'Pacific timezone overlap required'.",
    )

    requires_relocation: bool = Field(
        False,
        description="True if the posting says or strongly implies eventual relocation is expected.",
    )

    requires_local_presence: bool = Field(
        False,
        description="True if candidate must live within commuting distance of an office, even if labeled remote.",
    )

    timezone_requirements: list[str] = Field(
        default_factory=list,
        description="Explicit timezone requirements from the posting, e.g. 'EST', 'Pacific timezone overlap required'. Empty if none stated.",
    )

    key_phrases: list[str] = Field(
        default_factory=list,
        description="2-5 verbatim excerpts from the posting that directly support the classification.",
    )
