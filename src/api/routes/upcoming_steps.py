"""GET /api/upcoming-steps — synchronous rules engine endpoint.

Derives time-based alerts over the current user's application events and
returns a structured alert list. Plain request/response — no async, no
background jobs, no stored alerts.

Thresholds are read from ``app.user_search_configs`` (set via #386). Falls
back to defaults (3 / 7 / 14 days) when no config row exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter

from ..dependencies import CurrentUser, Pool
from ..schemas import (
    InactivityAlertOut,
    PostInterviewAlertOut,
    StaleToApplyAlertOut,
    UpcomingStepsResponse,
)
from ..upcoming_steps import (
    check_inactivity,
    check_post_interview,
    check_stale_to_apply,
)

router = APIRouter(prefix="/upcoming-steps", tags=["Upcoming Steps"])

_DEFAULT_STALE_DAYS = 3
_DEFAULT_INTERVIEW_DAYS = 7
_DEFAULT_INACTIVITY_DAYS = 14


def _build_messages(alerts):
    """Attach human-readable messages to each alert dataclass and convert
    to Pydantic output models."""
    out = []
    for alert in alerts:
        if alert.kind == "stale_to_apply":
            out.append(
                StaleToApplyAlertOut(
                    message=(
                        f"{alert.count} job(s) have been in 'to apply' for "
                        f"{alert.days} day(s) without moving forward."
                    ),
                    count=alert.count,
                    dedup_hashes=alert.dedup_hashes,
                    days=alert.days,
                )
            )
        elif alert.kind == "post_interview":
            out.append(
                PostInterviewAlertOut(
                    message=(
                        f"{alert.count} job(s) haven't progressed past "
                        f"interview for {alert.days} day(s)."
                    ),
                    count=alert.count,
                    dedup_hashes=alert.dedup_hashes,
                    days=alert.days,
                )
            )
        elif alert.kind == "inactivity":
            out.append(
                InactivityAlertOut(
                    message=(
                        f"No applications submitted in the last {alert.days} days."
                    ),
                    days=alert.days,
                )
            )
        else:
            # FAIL FAST: an alert kind the engine produced but this builder
            # doesn't handle would otherwise vanish silently from the response.
            raise ValueError(f"unhandled upcoming-steps alert kind: {alert.kind!r}")
    return out


@router.get("", response_model=UpcomingStepsResponse)
async def get_upcoming_steps(
    pool: Pool,
    user: CurrentUser,
) -> UpcomingStepsResponse:
    # 1. Fetch status_change events for the user (chronological order)
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT dedup_hash, occurred_at, metadata
            FROM app.application_events
            WHERE user_id = %(user_id)s AND kind = 'status_change'
            ORDER BY occurred_at
            """,
            {"user_id": user.id},
        )
        events = cast("list[dict[str, Any]]", await cur.fetchall())

        # 2. Fetch threshold settings (with defaults if no config row)
        row = cast(
            "dict[str, Any] | None",
            await (
                await conn.execute(
                    "SELECT stale_to_apply_days, post_interview_nudge_days, inactivity_days "
                    "FROM app.user_search_configs WHERE user_id = %(user_id)s",
                    {"user_id": user.id},
                )
            ).fetchone(),
        )

    stale_days = row["stale_to_apply_days"] if row else _DEFAULT_STALE_DAYS
    interview_days = (
        row["post_interview_nudge_days"] if row else _DEFAULT_INTERVIEW_DAYS
    )
    inactivity_days = row["inactivity_days"] if row else _DEFAULT_INACTIVITY_DAYS

    # 3. Run pure rule functions
    now = datetime.now(timezone.utc)
    alerts = []
    stale = check_stale_to_apply(events, now, stale_days)
    if stale:
        alerts.append(stale)
    interview = check_post_interview(events, now, interview_days)
    if interview:
        alerts.append(interview)
    inactive = check_inactivity(events, now, inactivity_days)
    if inactive:
        alerts.append(inactive)

    # 4. Build response with human-readable messages
    return UpcomingStepsResponse(alerts=_build_messages(alerts))
