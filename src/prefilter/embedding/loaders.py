"""Validated JSONL loaders for postings and skills-fit scores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import Posting
from .reference import normalize_text


def _require_non_empty_string(value: object, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{context}: required field {field!r} must be a non-empty string"
        )
    return value


def parse_postings_jsonl(text: str, path: Path) -> list[Posting]:
    """Validate JSONL posting content with path and line context."""
    postings: list[Posting] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        context = f"Malformed input {path} line {line_number}"
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{context}: invalid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{context}: expected a JSON object")
        title = _require_non_empty_string(record.get("title"), "title", context)
        company = _require_non_empty_string(record.get("company"), "company", context)
        dedup_hash = _require_non_empty_string(
            record.get("dedup_hash"), "dedup_hash", context
        )
        description_value = record.get("description", "")
        if description_value is None:
            description_value = ""
        if not isinstance(description_value, str):
            raise ValueError(f"{context}: description must be a string when present")
        source_url = record.get("source_url", "")
        if source_url is None:
            source_url = ""
        if not isinstance(source_url, str):
            raise ValueError(f"{context}: source_url must be a string when present")
        description_fallback = not bool(normalize_text(description_value))
        postings.append(
            Posting(
                title=normalize_text(title),
                company=normalize_text(company),
                dedup_hash=dedup_hash.strip(),
                description=normalize_text(description_value),
                source_url=source_url,
                description_fallback=description_fallback,
            )
        )
    return postings


def _unpack_ai_fit(value: object, context: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        if 1 <= value <= 5:
            return value
        raise ValueError(f"{context}: ai_fit ordinal must be in 1..5")
    candidates: list[int] = []

    def find_scores(node: object) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "fit_score":
                    if isinstance(child, bool) or not isinstance(child, int):
                        raise ValueError(
                            f"{context}: ai_fit.fit_score must be an ordinal"
                        )
                    candidates.append(child)
                else:
                    find_scores(child)
        elif isinstance(node, list):
            for child in node:
                find_scores(child)

    find_scores(value)
    if not candidates or any(not 1 <= score <= 5 for score in candidates):
        raise ValueError(f"{context}: ai_fit is not unpackable to an ordinal")
    if len(set(candidates)) != 1:
        raise ValueError(f"{context}: ai_fit contains conflicting ordinals")
    return candidates[0]


def parse_skills_fit_jsonl(text: str, path: Path) -> dict[str, int | None]:
    scores: dict[str, int | None] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        context = f"Malformed skills-fit input {path} line {line_number}"
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{context}: invalid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{context}: expected a JSON object")
        dedup_hash = _require_non_empty_string(
            record.get("dedup_hash"), "dedup_hash", context
        )
        if dedup_hash in scores:
            raise ValueError(f"{context}: duplicate dedup_hash {dedup_hash!r}")
        scores[dedup_hash] = _unpack_ai_fit(record.get("ai_fit"), context)
    return scores


def _mean_or_none(values: Iterable[int | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None
