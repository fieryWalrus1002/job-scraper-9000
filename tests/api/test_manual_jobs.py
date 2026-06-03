"""Endpoint tests for POST /api/jobs (manual job entry).

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import _make_cursor

FAKE_MANUAL_APP_ROW: dict[str, Any] = {
    "dedup_hash": "a" * 64,
    "status": "saved",
    "applied_at": None,
    "notes": None,
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
    "status": "saved",
}


def _two_cursors(app_row: dict[str, Any]) -> tuple[AsyncMock, AsyncMock]:
    """Return (job_insert_cursor, app_insert_cursor) pair."""
    job_cur = _make_cursor()
    job_cur.rowcount = 1
    app_cur = _make_cursor(app_row)
    return job_cur, app_cur


# ---------------------------------------------------------------------------
# POST /api/jobs
# ---------------------------------------------------------------------------


async def test_create_manual_job_success(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    job_cur, app_cur = _two_cursors(FAKE_MANUAL_APP_ROW)
    fake_conn.execute = AsyncMock(side_effect=[job_cur, app_cur])
    resp = await client.post("/api/jobs", json=_BODY)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "saved"
    assert data["title"] == "Staff Engineer"
    assert data["company"] == "Initech"
    assert fake_conn.execute.call_count == 2


async def test_create_manual_job_duplicate(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    job_cur = _make_cursor()
    job_cur.rowcount = 0  # ON CONFLICT DO NOTHING — row already exists
    fake_conn.execute = AsyncMock(return_value=job_cur)
    resp = await client.post("/api/jobs", json=_BODY)
    assert resp.status_code == 409
    assert fake_conn.execute.call_count == 1


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
    job_cur, app_cur = _two_cursors(row)
    fake_conn.execute = AsyncMock(side_effect=[job_cur, app_cur])
    resp = await client.post("/api/jobs", json={**_BODY, "status": "applied"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "applied"
    assert fake_conn.execute.call_count == 2


async def test_create_manual_job_fit_score_stored(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    row = {**FAKE_MANUAL_APP_ROW, "fit_score": 5}
    job_cur, app_cur = _two_cursors(row)
    fake_conn.execute = AsyncMock(side_effect=[job_cur, app_cur])
    resp = await client.post("/api/jobs", json={**_BODY, "fit_score": 5})
    assert resp.status_code == 201
    assert resp.json()["fit_score"] == 5
