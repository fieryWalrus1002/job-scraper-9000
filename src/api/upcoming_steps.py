"""Pure rule engine for upcoming-steps alerts.

Takes already-fetched event rows and threshold values, derives time-based
alerts, and returns alert objects. No I/O — everything is in-process so the
functions are unit-testable without a database.

FAIL FAST: malformed status_change metadata (missing ``to_status``) raises
``ValueError`` rather than silently dropping the row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Alert data types
# ---------------------------------------------------------------------------


@dataclass
class StaleToApplyAlert:
    """Jobs sitting in *to_apply* longer than the threshold without moving
    to *applied*."""

    kind: str = "stale_to_apply"
    count: int = 0
    dedup_hashes: list[str] = field(default_factory=list)
    days: int = 0  # max days stale among the batch


@dataclass
class PostInterviewAlert:
    """Jobs that entered *interview* and haven't moved for > threshold days."""

    kind: str = "post_interview"
    count: int = 0
    dedup_hashes: list[str] = field(default_factory=list)
    days: int = 0  # max days since last interview event


@dataclass
class InactivityAlert:
    """No *applied* event across the entire pipeline for > threshold days."""

    kind: str = "inactivity"
    days: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_STALE_DAYS = 3
_DEFAULT_INTERVIEW_DAYS = 7
_DEFAULT_INACTIVITY_DAYS = 14


def _parse_status_change_metadata(row: dict[str, Any]) -> str:
    """Extract ``to_status`` from a status_change event's metadata.

    Raises ``ValueError`` if the metadata is missing ``to_status`` — malformed
    rows are fatal per FAIL FAST.
    """
    metadata: dict[str, Any] | None = row.get("metadata")
    if metadata is None:
        raise ValueError(
            f"status_change event (dedup_hash={row.get('dedup_hash')!r}) "
            "has null metadata — expected {{'to_status': …}}"
        )
    to_status = metadata.get("to_status")
    if to_status is None:
        raise ValueError(
            f"status_change event (dedup_hash={row.get('dedup_hash')!r}) "
            f"metadata missing 'to_status': {metadata}"
        )
    return to_status


# ---------------------------------------------------------------------------
# Rule functions
# ---------------------------------------------------------------------------


def check_stale_to_apply(
    events: list[dict[str, Any]],
    now: datetime,
    threshold_days: int = _DEFAULT_STALE_DAYS,
) -> StaleToApplyAlert | None:
    """Return an alert for jobs stuck in *to_apply* beyond the threshold.

    A job is stale if:
    1. Its latest ``to_status == "to_apply"`` event has no later
       ``to_status == "applied"`` event.
    2. ``now - occurred_at > threshold_days``.

    Returns ``None`` when no stale jobs are found.
    """
    deadline = now - timedelta(days=threshold_days)

    # Group events by dedup_hash, keeping only status_change rows
    by_job: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        dh = row["dedup_hash"]
        by_job.setdefault(dh, []).append(row)

    stale_hashes: list[str] = []
    max_days = 0

    for dh, rows in by_job.items():
        # Sort chronologically so "latest" = last element
        rows.sort(key=lambda r: r["occurred_at"])

        # Find the latest to_apply event
        latest_to_apply: datetime | None = None
        for r in rows:
            to_status = _parse_status_change_metadata(r)
            if to_status == "to_apply":
                latest_to_apply = r["occurred_at"]

        if latest_to_apply is None:
            continue

        # Check if there's a later "applied" event (cancels the alert)
        has_later_applied = False
        for r in rows:
            if r["occurred_at"] > latest_to_apply:
                to_status = _parse_status_change_metadata(r)
                if to_status == "applied":
                    has_later_applied = True
                    break

        if has_later_applied:
            continue

        # Check if past threshold
        if latest_to_apply < deadline:
            stale_hashes.append(dh)
            days_stale = (now - latest_to_apply).days
            if days_stale > max_days:
                max_days = days_stale

    if not stale_hashes:
        return None

    return StaleToApplyAlert(
        count=len(stale_hashes),
        dedup_hashes=stale_hashes,
        days=max_days,
    )


def check_post_interview(
    events: list[dict[str, Any]],
    now: datetime,
    threshold_days: int = _DEFAULT_INTERVIEW_DAYS,
) -> PostInterviewAlert | None:
    """Return an alert for jobs that entered *interview* and stalled.

    Per job, find the latest ``to_status == "interview"`` event. If
    ``now - occurred_at > threshold_days``, include it.

    Returns ``None`` when no interview-nudge jobs are found.
    """
    deadline = now - timedelta(days=threshold_days)

    by_job: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        dh = row["dedup_hash"]
        by_job.setdefault(dh, []).append(row)

    nudge_hashes: list[str] = []
    max_days = 0

    for dh, rows in by_job.items():
        rows.sort(key=lambda r: r["occurred_at"])

        latest_interview: datetime | None = None
        for r in rows:
            to_status = _parse_status_change_metadata(r)
            if to_status == "interview":
                latest_interview = r["occurred_at"]

        if latest_interview is None:
            continue

        if latest_interview < deadline:
            nudge_hashes.append(dh)
            days_since = (now - latest_interview).days
            if days_since > max_days:
                max_days = days_since

    if not nudge_hashes:
        return None

    return PostInterviewAlert(
        count=len(nudge_hashes),
        dedup_hashes=nudge_hashes,
        days=max_days,
    )


def check_inactivity(
    events: list[dict[str, Any]],
    now: datetime,
    threshold_days: int = _DEFAULT_INACTIVITY_DAYS,
) -> InactivityAlert | None:
    """Return an alert if no *applied* event has occurred in the window.

    Looks at ``max(occurred_at)`` across all ``to_status == "applied"`` events.
    If that max is older than ``threshold_days``, or if there are no applied
    events at all, emit an alert.

    Returns ``None`` when activity is within threshold.
    """
    deadline = now - timedelta(days=threshold_days)

    latest_applied: datetime | None = None
    for row in events:
        to_status = _parse_status_change_metadata(row)
        if to_status == "applied":
            occurred = row["occurred_at"]
            if latest_applied is None or occurred > latest_applied:
                latest_applied = occurred

    if latest_applied is None:
        # No applications at all — report as very stale
        return InactivityAlert(days=threshold_days)

    if latest_applied < deadline:
        return InactivityAlert(days=(now - latest_applied).days)

    return None
