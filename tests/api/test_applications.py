"""Endpoint tests for /api/applications.

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import FAKE_JOB_ROW, _make_cursor

FAKE_APP_ROW: dict[str, Any] = {
    "dedup_hash": FAKE_JOB_ROW["dedup_hash"],
    "status": "maybe",
    "applied_at": None,
    "created_at": datetime(2026, 6, 1, 12, 0, 0),
    "updated_at": datetime(2026, 6, 1, 12, 0, 0),
    "title": FAKE_JOB_ROW["title"],
    "company": FAKE_JOB_ROW["company"],
    "fit_score": FAKE_JOB_ROW["fit_score"],
    "source_url": FAKE_JOB_ROW["source_url"],
}


# ---------------------------------------------------------------------------
# GET /api/applications
# ---------------------------------------------------------------------------


async def test_list_applications_empty(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor())
    resp = await client.get("/api/applications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_applications_returns_rows(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_APP_ROW))
    resp = await client.get("/api/applications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "maybe"
    assert data[0]["title"] == FAKE_JOB_ROW["title"]


async def test_list_applications_filters_by_status_set(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    applied = {**FAKE_APP_ROW, "dedup_hash": "cafebabe" * 8, "status": "applied"}
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_APP_ROW, applied))
    resp = await client.get(
        "/api/applications", params=[("status", "maybe"), ("status", "applied")]
    )
    assert resp.status_code == 200
    assert [row["status"] for row in resp.json()] == ["maybe", "applied"]

    sql, params = fake_conn.execute.await_args.args
    assert "a.status = ANY(%(statuses)s::text[])" in sql
    assert params["statuses"] == ["maybe", "applied"]


async def test_list_applications_invalid_status_rejected(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.get("/api/applications", params={"status": "not_real"})
    assert resp.status_code == 422
    fake_conn.execute.assert_not_called()


async def test_list_applications_latest_event_status_change(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """A status_change latest_event round-trips with to_status and null body."""
    row = {
        **FAKE_APP_ROW,
        "latest_event": {
            "kind": "status_change",
            "occurred_at": "2026-06-15T10:00:00",
            "body": None,
            "to_status": "applied",
        },
    }
    fake_conn.execute = AsyncMock(return_value=_make_cursor(row))
    resp = await client.get("/api/applications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["latest_event"]["kind"] == "status_change"
    assert data[0]["latest_event"]["to_status"] == "applied"
    assert data[0]["latest_event"]["body"] is None


async def test_list_applications_latest_event_null(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """When the row has no events, latest_event is null."""
    row = {**FAKE_APP_ROW, "latest_event": None}
    fake_conn.execute = AsyncMock(return_value=_make_cursor(row))
    resp = await client.get("/api/applications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["latest_event"] is None


async def test_list_applications_latest_event_generic(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """A generic event latest_event round-trips with body and null to_status."""
    row = {
        **FAKE_APP_ROW,
        "latest_event": {
            "kind": "event",
            "occurred_at": "2026-06-20T14:30:00",
            "body": "Reached out to recruiter",
            "to_status": None,
        },
    }
    fake_conn.execute = AsyncMock(return_value=_make_cursor(row))
    resp = await client.get("/api/applications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["latest_event"]["kind"] == "event"
    assert data[0]["latest_event"]["body"] == "Reached out to recruiter"
    assert data[0]["latest_event"]["to_status"] is None


# ---------------------------------------------------------------------------
# POST /api/applications
# ---------------------------------------------------------------------------


async def test_create_application(client: AsyncClient, fake_conn: AsyncMock) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_APP_ROW))
    resp = await client.post(
        "/api/applications",
        json={"dedup_hash": FAKE_JOB_ROW["dedup_hash"], "status": "maybe"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "maybe"


async def test_create_application_invalid_status(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.post(
        "/api/applications",
        json={
            "dedup_hash": FAKE_JOB_ROW["dedup_hash"],
            "status": "definitely_not_a_status",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/applications/{dedup_hash}
# ---------------------------------------------------------------------------


async def test_update_application_status(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    updated = {**FAKE_APP_ROW, "status": "applied"}
    fake_conn.execute = AsyncMock(return_value=_make_cursor(updated))
    resp = await client.patch(
        f"/api/applications/{FAKE_JOB_ROW['dedup_hash']}",
        json={"status": "applied"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"


async def test_update_application_null_status_rejected(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.patch(
        f"/api/applications/{FAKE_JOB_ROW['dedup_hash']}",
        json={"status": None},
    )
    assert resp.status_code == 422


async def test_update_application_no_fields_rejected(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.patch(
        f"/api/applications/{FAKE_JOB_ROW['dedup_hash']}",
        json={},
    )
    assert resp.status_code == 422


async def test_update_application_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(None))
    resp = await client.patch(
        "/api/applications/nonexistent",
        json={"status": "applied"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/applications/{dedup_hash}
# ---------------------------------------------------------------------------


async def test_delete_application(client: AsyncClient, fake_conn: AsyncMock) -> None:
    cur = _make_cursor()
    cur.rowcount = 1
    fake_conn.execute = AsyncMock(return_value=cur)
    resp = await client.delete(f"/api/applications/{FAKE_JOB_ROW['dedup_hash']}")
    assert resp.status_code == 204
    assert resp.content == b""


async def test_delete_application_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    cur = _make_cursor()
    cur.rowcount = 0
    fake_conn.execute = AsyncMock(return_value=cur)
    resp = await client.delete("/api/applications/nonexistent")
    assert resp.status_code == 404
