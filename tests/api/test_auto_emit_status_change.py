"""Tests for auto-emit of status_change events on triage mutations.

Verifies that PATCH and POST on /api/applications insert status_change events
atomically (same transaction) when status actually changes, and emit nothing
when status is unchanged or when only notes/applied_at are updated.

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from tests.api.conftest import FAKE_JOB_ROW, _make_cursor

DEDUP = FAKE_JOB_ROW["dedup_hash"]

FAKE_APP_ROW: dict[str, Any] = {
    "dedup_hash": DEDUP,
    "status": "maybe",
    "applied_at": None,
    "notes": None,
    "created_at": datetime(2026, 6, 1, 12, 0, 0),
    "updated_at": datetime(2026, 6, 1, 12, 0, 0),
    "title": FAKE_JOB_ROW["title"],
    "company": FAKE_JOB_ROW["company"],
    "fit_score": FAKE_JOB_ROW["fit_score"],
    "source_url": FAKE_JOB_ROW["source_url"],
}

FAKE_EVENT_ROW: dict[str, Any] = {
    "id": _uuid.uuid4(),
    "dedup_hash": DEDUP,
    "kind": "status_change",
    "occurred_at": datetime(2026, 6, 10, 10, 0, 0),
    "body": None,
    "tags": [],
    "metadata": {"from_status": "maybe", "to_status": "applied"},
    "created_at": datetime(2026, 6, 10, 10, 0, 0),
}


def _make_txn_ctx(conn: AsyncMock) -> MagicMock:
    """Build an async-context-manager mock for conn.transaction()."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=True)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# PATCH /api/applications/{dedup_hash} — status change emits event
# ---------------------------------------------------------------------------


async def test_patch_status_change_emits_event(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Changing status via PATCH inserts exactly one status_change event."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    # 1st execute: SELECT old status → returns old row
    # 2nd execute: UPDATE → returns updated row
    # 3rd execute: INSERT event → returns event row
    old_status_row = {"status": "maybe"}
    updated_row = {**FAKE_APP_ROW, "status": "applied"}
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(old_status_row),
            _make_cursor(updated_row),
            _make_cursor(FAKE_EVENT_ROW),
        ]
    )

    resp = await client.patch(
        f"/api/applications/{DEDUP}",
        json={"status": "applied"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"

    # Verify 3 queries were run: SELECT, UPDATE, INSERT event
    assert fake_conn.execute.call_count == 3

    # Verify the event INSERT has correct payload. metadata is wrapped in
    # psycopg Json(...) (jsonb adapter); the wrapped dict lives on .obj.
    event_sql, event_params = fake_conn.execute.call_args_list[2].args
    assert "INSERT INTO app.application_events" in event_sql
    assert "'status_change'" in event_sql
    assert event_params["metadata"].obj == {
        "from_status": "maybe",
        "to_status": "applied",
    }

    # Verify transaction was used
    fake_conn.transaction.assert_called_once()


async def test_patch_same_status_no_event(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """A no-op status update (same value) inserts no event."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    old_status_row = {"status": "maybe"}
    unchanged_row = {**FAKE_APP_ROW, "status": "maybe"}
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(old_status_row),
            _make_cursor(unchanged_row),
        ]
    )

    resp = await client.patch(
        f"/api/applications/{DEDUP}",
        json={"status": "maybe"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "maybe"

    # Only 2 queries: SELECT old + UPDATE (no event INSERT)
    assert fake_conn.execute.call_count == 2
    fake_conn.transaction.assert_called_once()


async def test_patch_notes_only_no_event(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """A notes-only update inserts no event."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    old_status_row = {"status": "maybe"}
    updated_row = {**FAKE_APP_ROW, "notes": "Added a note"}
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(old_status_row),
            _make_cursor(updated_row),
        ]
    )

    resp = await client.patch(
        f"/api/applications/{DEDUP}",
        json={"notes": "Added a note"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Added a note"

    # Only 2 queries: SELECT old + UPDATE (no event INSERT)
    assert fake_conn.execute.call_count == 2
    fake_conn.transaction.assert_called_once()


async def test_patch_status_change_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """PATCH on non-existent application returns 404, no event emitted."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(None),  # SELECT old status → not found
        ]
    )

    resp = await client.patch(
        "/api/applications/nonexistent",
        json={"status": "applied"},
    )
    assert resp.status_code == 404
    # Only the SELECT ran
    assert fake_conn.execute.call_count == 1


# ---------------------------------------------------------------------------
# POST /api/applications — new row emits event with from=null
# ---------------------------------------------------------------------------


async def test_create_new_application_emits_event(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Creating a new application inserts a status_change event with from=null."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    # 1st execute: SELECT old status → no row (new application)
    # 2nd execute: INSERT application → returns new row
    # 3rd execute: INSERT event → returns event row
    new_app_row = {**FAKE_APP_ROW, "status": "to_apply"}
    new_event_row = {
        **FAKE_EVENT_ROW,
        "metadata": {"from_status": None, "to_status": "to_apply"},
    }
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(None),  # no existing row
            _make_cursor(new_app_row),
            _make_cursor(new_event_row),
        ]
    )

    resp = await client.post(
        "/api/applications",
        json={"dedup_hash": DEDUP, "status": "to_apply"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "to_apply"

    # 3 queries: SELECT, INSERT app, INSERT event
    assert fake_conn.execute.call_count == 3

    # Verify event INSERT has from=null
    _, event_params = fake_conn.execute.call_args_list[2].args
    assert event_params["metadata"].obj == {
        "from_status": None,
        "to_status": "to_apply",
    }

    fake_conn.transaction.assert_called_once()


async def test_create_upsert_status_change_emits_event(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Upsert onto existing row with different status emits status_change event."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    # 1st execute: SELECT old status → existing row with "maybe"
    # 2nd execute: INSERT … ON CONFLICT → returns updated row
    # 3rd execute: INSERT event
    old_status = "maybe"
    updated_row = {**FAKE_APP_ROW, "status": "applied"}
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor({"status": old_status}),
            _make_cursor(updated_row),
            _make_cursor(FAKE_EVENT_ROW),
        ]
    )

    resp = await client.post(
        "/api/applications",
        json={"dedup_hash": DEDUP, "status": "applied"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "applied"
    assert fake_conn.execute.call_count == 3

    _, event_params = fake_conn.execute.call_args_list[2].args
    assert event_params["metadata"].obj == {
        "from_status": "maybe",
        "to_status": "applied",
    }


async def test_create_upsert_same_status_no_event(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Upsert onto existing row with same status emits no event."""
    fake_conn.transaction = MagicMock(return_value=_make_txn_ctx(fake_conn))

    updated_row = {**FAKE_APP_ROW, "status": "maybe"}
    fake_conn.execute = AsyncMock(
        side_effect=[
            _make_cursor({"status": "maybe"}),
            _make_cursor(updated_row),
        ]
    )

    resp = await client.post(
        "/api/applications",
        json={"dedup_hash": DEDUP, "status": "maybe"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "maybe"

    # Only 2 queries: SELECT + INSERT (no event)
    assert fake_conn.execute.call_count == 2
    fake_conn.transaction.assert_called_once()
