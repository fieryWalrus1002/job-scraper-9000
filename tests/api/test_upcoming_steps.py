"""Endpoint tests for GET /api/upcoming-steps.

Mock pool fixture — no live Postgres. Verifies the endpoint wires together:
fetches events + thresholds, calls rule functions, and returns the response.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import _make_cursor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(dh: str, to_status: str, days_ago: int) -> dict[str, Any]:
    occurred_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "dedup_hash": dh,
        "occurred_at": occurred_at,
        "metadata": {"to_status": to_status, "from_status": None},
    }


# ---------------------------------------------------------------------------
# GET /api/upcoming-steps — empty / defaults
# ---------------------------------------------------------------------------


async def test_upcoming_steps_empty_no_events(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """No events, no config row → empty alerts list.

    A user with no events has never applied, so inactivity does NOT fire
    (inactivity = applied-then-quiet, not never-applied)."""
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(),  # events query → empty
            _make_cursor(),  # thresholds query → no row (defaults used)
        ]
    )
    resp = await client.get("/api/upcoming-steps")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"] == []


async def test_upcoming_steps_empty_no_alerts_due(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Recent applied event, no config row → defaults used, only inactivity suppressed."""
    events = [_event("job-1", "applied", 1)]
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(*events),  # events
            _make_cursor(),  # thresholds → defaults
        ]
    )
    resp = await client.get("/api/upcoming-steps")
    assert resp.status_code == 200
    data = resp.json()
    # No inactivity (applied 1 day ago < 14 default threshold)
    assert len(data["alerts"]) == 0


# ---------------------------------------------------------------------------
# GET /api/upcoming-steps — stale to_apply alert
# ---------------------------------------------------------------------------


async def test_upcoming_steps_stale_to_apply(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """to_apply event 5 days ago, threshold=3 → stale alert."""
    events = [_event("job-stale", "to_apply", 5)]
    config_row = {
        "stale_to_apply_days": 3,
        "post_interview_nudge_days": 7,
        "inactivity_days": 14,
    }
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(*events),
            _make_cursor(config_row),
        ]
    )
    resp = await client.get("/api/upcoming-steps")
    assert resp.status_code == 200
    data = resp.json()
    stale = [a for a in data["alerts"] if a["kind"] == "stale_to_apply"]
    assert len(stale) == 1
    assert stale[0]["count"] == 1
    assert "job-stale" in stale[0]["dedup_hashes"]
    assert stale[0]["days"] >= 5
    assert "to apply" in stale[0]["message"].lower()


# ---------------------------------------------------------------------------
# GET /api/upcoming-steps — post_interview alert
# ---------------------------------------------------------------------------


async def test_upcoming_steps_post_interview(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """interview event 10 days ago, threshold=7 → nudge alert."""
    events = [_event("job-interview", "interview", 10)]
    config_row = {
        "stale_to_apply_days": 3,
        "post_interview_nudge_days": 7,
        "inactivity_days": 14,
    }
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(*events),
            _make_cursor(config_row),
        ]
    )
    resp = await client.get("/api/upcoming-steps")
    assert resp.status_code == 200
    data = resp.json()
    interview = [a for a in data["alerts"] if a["kind"] == "post_interview"]
    assert len(interview) == 1
    assert interview[0]["count"] == 1
    assert "job-interview" in interview[0]["dedup_hashes"]
    assert interview[0]["days"] >= 10
    assert "interview" in interview[0]["message"].lower()


# ---------------------------------------------------------------------------
# GET /api/upcoming-steps — threshold passthrough
# ---------------------------------------------------------------------------


async def test_upcoming_steps_thresholds_passthrough(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Custom thresholds: set stale_to_apply_days=10 so a 5-day-old event
    does NOT trigger the alert."""
    events = [_event("job-1", "to_apply", 5)]
    config_row = {
        "stale_to_apply_days": 10,  # 5 < 10 → no alert
        "post_interview_nudge_days": 7,
        "inactivity_days": 14,
    }
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(*events),
            _make_cursor(config_row),
        ]
    )
    resp = await client.get("/api/upcoming-steps")
    assert resp.status_code == 200
    data = resp.json()
    stale = [a for a in data["alerts"] if a["kind"] == "stale_to_apply"]
    assert len(stale) == 0  # 5 days < 10 day threshold
