"""Pure helpers for remote-filter HITL review.

The Streamlit app imports these so label derivation can be tested without
executing Streamlit at import time.
"""

from __future__ import annotations

from typing import Any

from agents.remote_filter.models import REMOTE_CLASSIFICATIONS

ACTIVE_LABELS = tuple(REMOTE_CLASSIFICATIONS)

# Historical teacher/bootstrap labels that may still exist in old staging files or
# reviewed gold. New saves must use ACTIVE_LABELS only.
LEGACY_TO_ACTIVE = {
    "fully_remote": "remote",
    "remote_with_quarterly_travel": "remote",
    "remote_with_monthly_travel": "remote",
    "remote_with_frequent_travel": "remote",
    "remote_with_occasional_travel": "remote",
    "location_restricted": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "onsite_disguised": "onsite",
}


class MissingAnalysisError(ValueError):
    """Raised when a review record has no parseable remote analysis."""


def extract_remote_analysis(job: dict[str, Any]) -> dict[str, Any]:
    """Extract the production RemoteAnalysis proposal from a review row."""
    analysis = job.get("_remote_analysis")
    if isinstance(analysis, dict):
        return analysis
    raise MissingAnalysisError("review record is missing production _remote_analysis")


def normalize_classification(value: Any) -> str | None:
    """Return the active 3-way label for a proposed classification, if possible."""
    if not isinstance(value, str):
        return None
    if value in ACTIVE_LABELS:
        return value
    return LEGACY_TO_ACTIVE.get(value)


def proposed_classification(analysis: dict[str, Any]) -> str | None:
    return normalize_classification(analysis.get("remote_classification"))


def suggested_verdict(classification: str | None) -> str:
    """Legacy pass/trash suggestion retained for gold compatibility.

    Remote-filter eval now scores ``_human_classification``. ``_human_verdict`` is
    still written because older reports and local gold tooling expect it.
    """
    if classification == "remote":
        return "pass"
    if classification in {"hybrid", "onsite"}:
        return "trash"
    return "unknown"


def validate_active_label(label: str) -> None:
    if label not in ACTIVE_LABELS:
        raise ValueError(
            f"remote-filter review labels must use the active 3-way axis; got {label!r}"
        )
