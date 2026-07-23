from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from .models import JobPosting

log = logging.getLogger(__name__)


class ScrapeQualityError(ValueError):
    """Raised when a scraper's output violates the post-scrape contract."""


@dataclass(frozen=True)
class ScrapeQualityThresholds:
    enabled: bool = True
    min_jobs: int = 1
    min_desc_chars: int = 100
    min_complete_pct: float = 0.5
    min_posted_at_pct: float = 0.25
    check_workplace: bool = False
    min_workplace_pct: float = 0.9


@dataclass(frozen=True)
class ScrapeQualityConfig:
    global_defaults: ScrapeQualityThresholds = ScrapeQualityThresholds()
    source_overrides: dict[str, ScrapeQualityThresholds] | None = None

    def thresholds_for(self, source: str) -> ScrapeQualityThresholds:
        """Return thresholds for ``source``, falling back from exact to family."""
        overrides = self.source_overrides or {}
        family = source.split(":", 1)[0]
        return overrides.get(source) or overrides.get(family) or self.global_defaults


def check_scrape(
    source: str, jobs: list[JobPosting], thresholds: ScrapeQualityThresholds
) -> None:
    """Raise ``ScrapeQualityError`` if scraped jobs violate quality thresholds.

    The gate is intentionally small and deterministic: it inspects only the
    in-memory ``JobPosting`` list returned by one scraper and either returns or
    raises a source-named error before degraded output can reach storage/agents.
    """
    if not thresholds.enabled:
        log.info("%s quality gate disabled", source)
        return

    failures: list[str] = []
    total = len(jobs)

    _check_minimum(
        source=source,
        metric="min job count",
        observed=total,
        threshold=thresholds.min_jobs,
        failures=failures,
    )

    complete_count = sum(
        1
        for job in jobs
        if job.description and len(job.description.strip()) >= thresholds.min_desc_chars
    )
    complete_pct = _fraction(complete_count, total)
    _check_minimum(
        source=source,
        metric="description completeness pct",
        observed=complete_pct,
        threshold=thresholds.min_complete_pct,
        failures=failures,
        fmt="pct",
    )

    posted_at_count = sum(1 for job in jobs if job.posted_at is not None)
    posted_at_pct = _fraction(posted_at_count, total)
    _check_minimum(
        source=source,
        metric="posted_at pct",
        observed=posted_at_pct,
        threshold=thresholds.min_posted_at_pct,
        failures=failures,
        fmt="pct",
    )

    if thresholds.check_workplace:
        workplace_count = sum(1 for job in jobs if job.search_params.get("workplace"))
        workplace_pct = _fraction(workplace_count, total)
        _check_minimum(
            source=source,
            metric="workplace provenance pct",
            observed=workplace_pct,
            threshold=thresholds.min_workplace_pct,
            failures=failures,
            fmt="pct",
        )
    else:
        log.info("%s quality workplace provenance check disabled", source)

    if failures:
        raise ScrapeQualityError("; ".join(failures))


def merge_thresholds(
    base: ScrapeQualityThresholds, overrides: dict[str, Any]
) -> ScrapeQualityThresholds:
    """Return ``base`` with YAML override values applied and coerced."""
    values = {
        "enabled": base.enabled,
        "min_jobs": base.min_jobs,
        "min_desc_chars": base.min_desc_chars,
        "min_complete_pct": base.min_complete_pct,
        "min_posted_at_pct": base.min_posted_at_pct,
        "check_workplace": base.check_workplace,
        "min_workplace_pct": base.min_workplace_pct,
    }
    unknown = set(overrides) - set(values)
    if unknown:
        raise ValueError(f"unknown quality gate key(s): {sorted(unknown)}")

    for key, value in overrides.items():
        if key in {"enabled", "check_workplace"}:
            values[key] = bool(value)
        elif key in {"min_jobs", "min_desc_chars"}:
            values[key] = int(value)
        else:
            values[key] = float(value)

    updated = replace(base, **values)
    _validate_thresholds(updated)
    return updated


def _validate_thresholds(thresholds: ScrapeQualityThresholds) -> None:
    if thresholds.min_jobs < 0:
        raise ValueError("quality gate min_jobs must be >= 0")
    if thresholds.min_desc_chars < 0:
        raise ValueError("quality gate min_desc_chars must be >= 0")
    for field_name in (
        "min_complete_pct",
        "min_posted_at_pct",
        "min_workplace_pct",
    ):
        value = getattr(thresholds, field_name)
        if not 0 <= value <= 1:
            raise ValueError(f"quality gate {field_name} must be between 0 and 1")


def _fraction(count: int, total: int) -> float:
    return count / total if total else 0.0


def _check_minimum(
    *,
    source: str,
    metric: str,
    observed: int | float,
    threshold: int | float,
    failures: list[str],
    fmt: str = "raw",
) -> None:
    log.info(
        "%s quality %s observed=%s threshold=%s",
        source,
        metric,
        _format(observed, fmt),
        _format(threshold, fmt),
    )
    if observed < threshold:
        failures.append(
            f"{source} quality gate failed {metric}: "
            f"observed={_format(observed, fmt)} threshold={_format(threshold, fmt)}"
        )


def _format(value: int | float, fmt: str) -> str:
    if fmt == "pct":
        return f"{float(value):.1%}"
    return str(value)
