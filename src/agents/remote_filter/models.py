from typing import Literal

from pydantic import BaseModel, Field

# Bump SCHEMA_VERSION (semver) when RemoteAnalysis fields change in a way that
# makes old eval records structurally incompatible with new ones.
# Prompt identity is tracked by hashing the prompt file on disk via
# utils.git_info.get_prompt_hash() — no manual constant to keep in sync.
SCHEMA_VERSION = "2.0.0"


class RemoteAnalysis(BaseModel):
    """Structured analysis of a job posting's remote work policy."""

    reasoning_trace: str = Field(
        description="Step-by-step logic: quote the posting, analyze location/travel, and debate any ambiguity.",
    )

    remote_classification: Literal[
        "fully_remote",
        "remote_with_quarterly_travel",
        "remote_with_monthly_travel",
        "remote_with_frequent_travel",
        "hybrid",
        "onsite_disguised",
        "location_restricted",
        "unclear",
    ]

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
