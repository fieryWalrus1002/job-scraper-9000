"""Canonical embedding reference and job text builders."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, cast

from .models import Posting

REFERENCE_SCHEMA = "reference-v1"
TITLE_SCHEMA = "job-title-v1"
TITLE_DESCRIPTION_SCHEMA = "job-title-description-500-v1"
NOMIC_REFERENCE_SCHEMA = "reference-nomic-v1"
NOMIC_TITLE_SCHEMA = "job-title-nomic-v1"
NOMIC_TITLE_DESCRIPTION_SCHEMA = "job-title-description-500-nomic-v1"
SCHEMAS_BY_PREFIX_SCHEME = {
    "none": {
        "reference": REFERENCE_SCHEMA,
        "title": TITLE_SCHEMA,
        "title_description_500": TITLE_DESCRIPTION_SCHEMA,
    },
    "nomic": {
        "reference": NOMIC_REFERENCE_SCHEMA,
        "title": NOMIC_TITLE_SCHEMA,
        "title_description_500": NOMIC_TITLE_DESCRIPTION_SCHEMA,
    },
}
VARIANT_SCHEMAS = {
    "title": TITLE_SCHEMA,
    "title_description_500": TITLE_DESCRIPTION_SCHEMA,
}
ALL_SCHEMA_VERSIONS = frozenset(
    schema
    for schemas in SCHEMAS_BY_PREFIX_SCHEME.values()
    for schema in schemas.values()
)


def normalize_text(value: str) -> str:
    """Strip text and collapse all whitespace runs to one space."""
    return " ".join(value.split())


def validate_profile(profile: object, path: Path) -> dict[str, object]:
    """Validate only the materialized-profile fields used by reference-v1."""
    if not isinstance(profile, dict):
        raise ValueError(f"Malformed profile {path}: expected a YAML mapping")
    summary = profile.get("summary")
    if not isinstance(summary, str):
        raise ValueError(f"Malformed profile {path}: summary must be a string")
    validated: dict[str, object] = {"summary": summary}
    for field in ("core_skills", "adjacent_skills", "preferred_domains"):
        value = profile.get(field)
        if value is None:
            validated[field] = []
            continue
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(
                f"Malformed profile {path}: {field} must be a list of strings when present"
            )
        validated[field] = value
    return validated


def _deduplicated_titles(target_titles: Sequence[str]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for title in target_titles:
        normalized = normalize_text(title)
        if not normalized:
            raise ValueError("--target-title must be a non-empty string")
        comparison_key = normalized.casefold()
        if comparison_key not in seen:
            seen.add(comparison_key)
            titles.append(normalized)
    if not titles:
        raise ValueError("At least one --target-title is required")
    return titles


def build_reference_text(
    profile: dict[str, object], target_titles: Sequence[str], goal_summary: str = ""
) -> str:
    """Build the exact reference-v1 canonical embedding input."""
    titles = _deduplicated_titles(target_titles)
    lines = [
        "Target job titles (highest priority): " + ", ".join(titles),
    ]
    if goal_summary:
        lines.append(f"Goal summary: {goal_summary}")
    lines.extend(
        (
            f"Candidate summary: {profile['summary']}",
            "Core skills: " + ", ".join(cast(Sequence[str], profile["core_skills"])),
            "Adjacent skills: "
            + ", ".join(cast(Sequence[str], profile["adjacent_skills"])),
            "Preferred domains: "
            + ", ".join(cast(Sequence[str], profile["preferred_domains"])),
        )
    )
    return "\n".join(lines)


def build_keywords_reference_text(target_titles: Sequence[str]) -> str:
    """Build a reference text from target titles only (no profile)."""
    titles = _deduplicated_titles(target_titles)
    return "Target job titles: " + ", ".join(titles)


def build_per_keyword_reference_texts(target_titles: Sequence[str]) -> list[str]:
    """One canonical string per deduplicated target title (order-stable)."""
    return _deduplicated_titles(target_titles)


def build_skills_reference_text(profile: dict[str, object]) -> str:
    """Build a reference text from core + adjacent skills only."""
    core = cast(Sequence[str], profile.get("core_skills") or [])
    adjacent = cast(Sequence[str], profile.get("adjacent_skills") or [])
    lines = [
        "Core skills: " + ", ".join(core),
        "Adjacent skills: " + ", ".join(adjacent),
    ]
    return "\n".join(lines)


def build_job_text(posting: Posting, variant: str) -> str:
    if variant == "title":
        return posting.title
    if variant == "title_description_500":
        if posting.description_fallback:
            return posting.title
        return f"{posting.title}\n\n{posting.description[:500]}"
    raise ValueError(f"Unknown job text variant: {variant}")


def apply_prefix_scheme(text: str, *, role: str, prefix_scheme: str) -> str:
    """Apply an explicit retrieval prefix to an already-canonical embedding input."""
    if prefix_scheme == "none":
        return text
    if prefix_scheme == "nomic":
        if role == "reference":
            return f"search_query: {text}"
        if role == "job":
            return f"search_document: {text}"
    raise ValueError(f"Unknown prefix scheme or role: {prefix_scheme!r}, {role!r}")
