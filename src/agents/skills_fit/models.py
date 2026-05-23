from typing import Literal, get_args

from pydantic import BaseModel, Field

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
        ),
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
