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
    """Return an alert for jobs whose current status is still *to_apply* beyond
    the threshold.

    A job is stale if:
    1. Its current status (``to_status`` of the chronologically last
       status_change event) equals ``"to_apply"``.
    2. ``now - occurred_at > threshold_days`` for that last event.

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

        # Current status = to_status of the last event
        current_to_status = _parse_status_change_metadata(rows[-1])
        if current_to_status != "to_apply":
            continue

        # Current status is to_apply; check if past threshold
        occurred_at = rows[-1]["occurred_at"]
        if occurred_at < deadline:
            stale_hashes.append(dh)
            days_stale = (now - occurred_at).days
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
    """Return an alert for jobs whose current status is still *interview* beyond
    the threshold.

    A job gets a nudge if:
    1. Its current status (``to_status`` of the chronologically last
       status_change event) equals ``"interview"``.
    2. ``now - occurred_at > threshold_days`` for that last event.

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

        # Current status = to_status of the last event
        current_to_status = _parse_status_change_metadata(rows[-1])
        if current_to_status != "interview":
            continue

        occurred_at = rows[-1]["occurred_at"]
        if occurred_at < deadline:
            nudge_hashes.append(dh)
            days_since = (now - occurred_at).days
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
    """Return an alert if applications have gone quiet beyond the window.

    Looks at ``max(occurred_at)`` across all ``to_status == "applied"`` events.
    If that max is older than ``threshold_days``, emit an alert.

    *Inactivity* means you applied before and went quiet — so when there are no
    applied events at all (e.g. a brand-new user, or one with only to_apply
    jobs) this returns ``None`` rather than firing a day-one false nudge. The
    "go apply to these" case is already covered by ``check_stale_to_apply``.

    Returns ``None`` when activity is within threshold or there's been no
    applied event at all.
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
        # Never applied — not "inactivity" (handled by stale_to_apply instead).
        return None

    if latest_applied < deadline:
        return InactivityAlert(days=(now - latest_applied).days)

    return None
