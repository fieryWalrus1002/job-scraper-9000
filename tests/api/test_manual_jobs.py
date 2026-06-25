"""Endpoint tests for POST /api/jobs (manual job entry).

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import _make_cursor

FAKE_MANUAL_APP_ROW: dict[str, Any] = {
    "dedup_hash": "a" * 64,
    "status": "maybe",
    "applied_at": None,
    "created_at": datetime(2026, 6, 3, 10, 0, 0),
    "updated_at": datetime(2026, 6, 3, 10, 0, 0),
    "title": "Staff Engineer",
    "company": "Initech",
    "fit_score": 3,
    "source_url": "https://example.com/jobs/staff",
}

_BODY = {
    "title": "Staff Engineer",
    "fit_score": 3,
    "company": "Initech",
    "source_url": "https://example.com/jobs/staff",
    "location": "Remote",
    "posted_at": "2026-06-01",
    "status": "maybe",
}


def _three_cursors(
    app_row: dict[str, Any],
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    """Return (posting_insert, score_insert, app_insert) cursors."""
    posting_cur = _make_cursor()
    posting_cur.rowcount = 1
    score_cur = _make_cursor()
    score_cur.rowcount = 1
    app_cur = _make_cursor(app_row)
    return posting_cur, score_cur, app_cur


# ---------------------------------------------------------------------------
# POST /api/jobs
# ---------------------------------------------------------------------------


async def test_create_manual_job_success(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(side_effect=_three_cursors(FAKE_MANUAL_APP_ROW))
    resp = await client.post("/api/jobs", json=_BODY)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "maybe"
    assert data["title"] == "Staff Engineer"
    assert data["company"] == "Initech"
    assert fake_conn.execute.call_count == 3


async def test_create_manual_job_duplicate_for_this_user(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """409 only when *this user's* score row already exists."""
    posting_cur = _make_cursor()
    posting_cur.rowcount = 0  # posting already exists — not a conflict by itself
    score_cur = _make_cursor()
    score_cur.rowcount = 0  # user already has this job
    fake_conn.execute = AsyncMock(side_effect=[posting_cur, score_cur])
    resp = await client.post("/api/jobs", json=_BODY)
    assert resp.status_code == 409
    assert fake_conn.execute.call_count == 2


async def test_create_manual_job_existing_posting_other_user(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """A posting another user already has still succeeds for this user."""
    posting_cur = _make_cursor()
    posting_cur.rowcount = 0  # shared posting already present
    score_cur = _make_cursor()
    score_cur.rowcount = 1  # but this user's score row is new
    app_cur = _make_cursor(FAKE_MANUAL_APP_ROW)
    fake_conn.execute = AsyncMock(side_effect=[posting_cur, score_cur, app_cur])
    resp = await client.post("/api/jobs", json=_BODY)
    assert resp.status_code == 201
    assert fake_conn.execute.call_count == 3


async def test_create_manual_job_missing_title(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.post("/api/jobs", json={"company": "Initech", "fit_score": 3})
    assert resp.status_code == 422


async def test_create_manual_job_missing_fit_score(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.post("/api/jobs", json={"title": "Staff Engineer"})
    assert resp.status_code == 422


async def test_create_manual_job_with_applied_status(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    row = {**FAKE_MANUAL_APP_ROW, "status": "applied"}
    fake_conn.execute = AsyncMock(side_effect=_three_cursors(row))
    resp = await client.post("/api/jobs", json={**_BODY, "status": "applied"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "applied"
    assert fake_conn.execute.call_count == 3


async def test_create_manual_job_fit_score_stored(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    row = {**FAKE_MANUAL_APP_ROW, "fit_score": 5}
    fake_conn.execute = AsyncMock(side_effect=_three_cursors(row))
    resp = await client.post("/api/jobs", json={**_BODY, "fit_score": 5})
    assert resp.status_code == 201
    assert resp.json()["fit_score"] == 5


async def test_create_manual_job_posted_at_provided(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """When posted_at is in the body, it is passed through unchanged."""
    fake_conn.execute = AsyncMock(side_effect=_three_cursors(FAKE_MANUAL_APP_ROW))
    resp = await client.post("/api/jobs", json=_BODY)  # _BODY has posted_at
    assert resp.status_code == 201
    # The first call to execute is the posting INSERT — check its params
    call_args = fake_conn.execute.call_args_list[0]
    params = call_args[0][1]  # second positional arg is the params dict
    assert params["posted_at"] == date(2026, 6, 1)


async def test_create_manual_job_posted_at_missing_defaults_to_today(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """When posted_at is omitted, it defaults to today's date."""
    body_without_posted_at = {
        "title": "Staff Engineer",
        "fit_score": 3,
        "company": "Initech",
        "source_url": "https://example.com/jobs/staff",
        "location": "Remote",
        "status": "maybe",
    }
    fake_conn.execute = AsyncMock(side_effect=_three_cursors(FAKE_MANUAL_APP_ROW))
    resp = await client.post("/api/jobs", json=body_without_posted_at)
    assert resp.status_code == 201
    call_args = fake_conn.execute.call_args_list[0]
    params = call_args[0][1]
    assert params["posted_at"] == date.today()
