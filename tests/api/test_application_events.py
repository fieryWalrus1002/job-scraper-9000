"""Endpoint tests for /api/applications/{dedup_hash}/events.

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import FAKE_JOB_ROW, _make_cursor

DEDUP = FAKE_JOB_ROW["dedup_hash"]
EVENT_ID = str(_uuid.uuid4())

FAKE_EVENT_ROW: dict[str, Any] = {
    "id": _uuid.UUID(EVENT_ID),
    "dedup_hash": DEDUP,
    "kind": "event",
    "occurred_at": datetime(2026, 6, 10, 10, 0, 0),
    "body": "Test event body",
    "tags": ["test", "manual"],
    "metadata": {"source": "test"},
    "created_at": datetime(2026, 6, 10, 10, 0, 0),
}

FAKE_STATUS_EVENT_ROW: dict[str, Any] = {
    "id": _uuid.UUID(str(_uuid.uuid4())),
    "dedup_hash": DEDUP,
    "kind": "status_change",
    "occurred_at": datetime(2026, 6, 10, 12, 0, 0),
    "body": None,
    "tags": [],
    "metadata": {"from_status": "maybe", "to_status": "applied"},
    "created_at": datetime(2026, 6, 10, 12, 0, 0),
}


# ---------------------------------------------------------------------------
# GET /api/applications/{dedup_hash}/events
# ---------------------------------------------------------------------------


async def test_list_events_empty(client: AsyncClient, fake_conn: AsyncMock) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor())
    resp = await client.get(f"/api/applications/{DEDUP}/events")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_events_returns_rows(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(
        return_value=_make_cursor(FAKE_STATUS_EVENT_ROW, FAKE_EVENT_ROW)
    )
    resp = await client.get(f"/api/applications/{DEDUP}/events")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # ORDER BY occurred_at DESC — status_change (12:00) before event (10:00)
    assert data[0]["kind"] == "status_change"
    assert data[1]["kind"] == "event"


async def test_list_events_scoped_to_user(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_EVENT_ROW))
    resp = await client.get(f"/api/applications/{DEDUP}/events")
    assert resp.status_code == 200

    sql, params = fake_conn.execute.await_args.args
    assert "user_id = %(user_id)s" in sql
    assert "dedup_hash = %(dedup_hash)s" in sql


# ---------------------------------------------------------------------------
# POST /api/applications/{dedup_hash}/events
# ---------------------------------------------------------------------------


async def test_create_event_generic(client: AsyncClient, fake_conn: AsyncMock) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_EVENT_ROW))
    resp = await client.post(
        f"/api/applications/{DEDUP}/events",
        json={
            "kind": "event",
            "body": "Test event body",
            "tags": ["test", "manual"],
            "metadata": {"source": "test"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["kind"] == "event"
    assert data["body"] == "Test event body"
    assert data["tags"] == ["test", "manual"]


async def test_create_event_status_change(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_STATUS_EVENT_ROW))
    resp = await client.post(
        f"/api/applications/{DEDUP}/events",
        json={
            "kind": "status_change",
            "from": "maybe",
            "to": "applied",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["kind"] == "status_change"
    assert data["metadata"]["from_status"] == "maybe"
    assert data["metadata"]["to_status"] == "applied"


async def test_create_event_bad_kind_rejected(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.post(
        f"/api/applications/{DEDUP}/events",
        json={
            "kind": "not_a_real_kind",
            "body": "should fail",
        },
    )
    assert resp.status_code == 422
    fake_conn.execute.assert_not_called()


async def test_create_event_missing_required_field_rejected(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """status_change without 'to' field → 422"""
    resp = await client.post(
        f"/api/applications/{DEDUP}/events",
        json={
            "kind": "status_change",
            "from": "maybe",
            # missing "to"
        },
    )
    assert resp.status_code == 422
    fake_conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH /api/applications/{dedup_hash}/events/{event_id}
# ---------------------------------------------------------------------------


async def test_update_event_body(client: AsyncClient, fake_conn: AsyncMock) -> None:
    updated = {**FAKE_EVENT_ROW, "body": "Updated body"}
    fake_conn.execute = AsyncMock(return_value=_make_cursor(updated))
    resp = await client.patch(
        f"/api/applications/{DEDUP}/events/{EVENT_ID}",
        json={"body": "Updated body"},
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "Updated body"


async def test_update_event_tags(client: AsyncClient, fake_conn: AsyncMock) -> None:
    updated = {**FAKE_EVENT_ROW, "tags": ["updated", "tags"]}
    fake_conn.execute = AsyncMock(return_value=_make_cursor(updated))
    resp = await client.patch(
        f"/api/applications/{DEDUP}/events/{EVENT_ID}",
        json={"tags": ["updated", "tags"]},
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["updated", "tags"]


async def test_update_event_metadata(client: AsyncClient, fake_conn: AsyncMock) -> None:
    updated = {**FAKE_EVENT_ROW, "metadata": {"key": "value"}}
    fake_conn.execute = AsyncMock(return_value=_make_cursor(updated))
    resp = await client.patch(
        f"/api/applications/{DEDUP}/events/{EVENT_ID}",
        json={"metadata": {"key": "value"}},
    )
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"key": "value"}


async def test_update_event_empty_body_rejected(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.patch(
        f"/api/applications/{DEDUP}/events/{EVENT_ID}",
        json={},
    )
    assert resp.status_code == 422


async def test_update_event_unrecognized_fields_ignored(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Fields not in the allowed set are ignored; if nothing valid remains → 422."""
    resp = await client.patch(
        f"/api/applications/{DEDUP}/events/{EVENT_ID}",
        json={"kind": "event", "dedup_hash": "x"},
    )
    assert resp.status_code == 422


async def test_update_event_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(None))
    resp = await client.patch(
        f"/api/applications/{DEDUP}/events/{EVENT_ID}",
        json={"body": "new"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/applications/{dedup_hash}/events/{event_id}
# ---------------------------------------------------------------------------


async def test_delete_event(client: AsyncClient, fake_conn: AsyncMock) -> None:
    cur = _make_cursor()
    cur.rowcount = 1
    fake_conn.execute = AsyncMock(return_value=cur)
    resp = await client.delete(f"/api/applications/{DEDUP}/events/{EVENT_ID}")
    assert resp.status_code == 204
    assert resp.content == b""


async def test_delete_event_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    cur = _make_cursor()
    cur.rowcount = 0
    fake_conn.execute = AsyncMock(return_value=cur)
    resp = await client.delete(f"/api/applications/{DEDUP}/events/{EVENT_ID}")
    assert resp.status_code == 404
