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


@dataclass
class PostApplicationAlert:
    """Jobs in *applied*/*screening* whose last meaningful touchpoint
    (status entry or follow_up/contact event) is older than threshold."""

    kind: str = "post_application"
    count: int = 0
    dedup_hashes: list[str] = field(default_factory=list)
    days: int = 0  # max days since last touchpoint among the batch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Alert-threshold defaults — single Python source of truth
#
# These are the one runtime source for threshold defaults. The migration
# `0013` column DEFAULT literals are deliberately separate (migrations are
# immutable historical records and must not import a moving constant). The
# frontend keeps its own copy across the language boundary (see
# AlertThresholdsSection.tsx) — not worth an API round-trip for a few ints.
# ---------------------------------------------------------------------------

_DEFAULT_STALE_DAYS = 3
_DEFAULT_INTERVIEW_DAYS = 7
_DEFAULT_INACTIVITY_DAYS = 14
_DEFAULT_POST_APPLICATION_DAYS = 10


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


def check_post_application(
    status_changes: list[dict[str, Any]],
    touchpoints: list[dict[str, Any]],
    now: datetime,
    threshold_days: int = _DEFAULT_POST_APPLICATION_DAYS,
) -> PostApplicationAlert | None:
    """Return an alert for jobs in *applied*/*screening* whose last meaningful
    touchpoint is older than the threshold.

    A *touchpoint* is either the status-change event that moved the job into
    *applied*/*screening*, or a `follow_up`/`contact` event logged for that job.
    The latter acts as a snooze — it resets the clock.

    Parameters
    ----------
    status_changes:
        All ``status_change`` event rows (``dedup_hash``, ``occurred_at``,
        ``metadata``). Same shape as the other rules receive.
    touchpoints:
        ``event``-kind rows with ``follow_up`` or ``contact`` tags, pre-filtered
        by the endpoint. Each row has ``dedup_hash`` and ``occurred_at``.
    now:
        Current time.
    threshold_days:
        Number of days of silence before nudging.

    Returns ``None`` when no jobs need nudging.
    """
    deadline = now - timedelta(days=threshold_days)

    # Group status_change rows by job
    by_job: dict[str, list[dict[str, Any]]] = {}
    for row in status_changes:
        dh = row["dedup_hash"]
        by_job.setdefault(dh, []).append(row)

    # Index touchpoints by dedup_hash (keep the latest per job)
    latest_touchpoint: dict[str, datetime] = {}
    for tp in touchpoints:
        dh = tp["dedup_hash"]
        tp_time = tp["occurred_at"]
        if dh not in latest_touchpoint or tp_time > latest_touchpoint[dh]:
            latest_touchpoint[dh] = tp_time

    nudge_hashes: list[str] = []
    max_days = 0

    for dh, rows in by_job.items():
        rows.sort(key=lambda r: r["occurred_at"])

        current_to_status = _parse_status_change_metadata(rows[-1])
        if current_to_status not in ("applied", "screening"):
            continue

        # The timestamp when the job entered this stage
        stage_entry = rows[-1]["occurred_at"]

        # Last follow-up / contact touchpoint for this job (if any)
        last_followup = latest_touchpoint.get(dh)

        # The effective "last touchpoint" is the later of stage entry and
        # any follow-up event. If there is no follow-up, the stage entry
        # itself is the touchpoint.
        if last_followup is not None:
            last_touchpoint = max(stage_entry, last_followup)
        else:
            last_touchpoint = stage_entry

        if last_touchpoint < deadline:
            nudge_hashes.append(dh)
            days_since = (now - last_touchpoint).days
            if days_since > max_days:
                max_days = days_since

    if not nudge_hashes:
        return None

    return PostApplicationAlert(
        count=len(nudge_hashes),
        dedup_hashes=nudge_hashes,
        days=max_days,
    )
