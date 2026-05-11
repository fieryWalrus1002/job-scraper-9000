from typing import Literal

from pydantic import BaseModel, Field


class RemoteAnalysis(BaseModel):
    """Structured analysis of a job posting's remote work policy."""

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

    travel_description: str | None = Field(
        None,
        description="Verbatim or close-to-verbatim phrase from the posting about travel. None if not mentioned.",
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

    confidence: Literal["high", "medium", "low"]

    reasoning: str = Field(
        description="2-3 sentence explanation of the classification, citing specific text from the posting.",
    )

    key_phrases: list[str] = Field(
        default_factory=list,
        description="2-5 verbatim excerpts from the posting that directly support the classification.",
    )


class UserPreferences(BaseModel):
    """Filter policy — what the user will tolerate."""

    max_travel: Literal["none", "quarterly", "monthly"] = "quarterly"
    unclear_routing: Literal["pass", "reject"] = "pass"
    user_location: str = "USA"


class EvalRecord(BaseModel):
    """A human-labeled job posting for eval suite use."""

    sample_id: str
    title: str
    company: str
    description: str

    expected_classification: str
    expected_should_pass_filter: bool
    expected_travel_days_range: tuple[int, int] | None
    key_phrases: list[str] = []
    notes: str
