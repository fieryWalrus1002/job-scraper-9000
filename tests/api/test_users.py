"""Tests for app.users provisioning (JIT linking) and GET /api/me."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.auth import Principal
from api.users import get_or_provision_user

from .conftest import _make_cursor

_USER_ID = uuid.uuid4()

FAKE_USER_ROW: dict[str, Any] = {
    "id": _USER_ID,
    "external_id": "oid-123",
    "identity_provider": "aad",
    "email": "allowed@example.com",
    "display_name": None,
    "role": "member",
    "created_at": datetime(2026, 6, 10, 12, 0, 0),
    "last_login_at": datetime(2026, 6, 10, 12, 0, 0),
}


def _principal(**overrides) -> Principal:
    defaults = dict(
        email="allowed@example.com",
        roles=["authenticated"],
        external_id="oid-123",
        identity_provider="aad",
    )
    return Principal(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# get_or_provision_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_row_matched_by_external_id():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=_make_cursor(FAKE_USER_ROW))

    row = await get_or_provision_user(conn, _principal())

    assert row == FAKE_USER_ROW
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_jit_links_by_email_on_first_login():
    conn = AsyncMock()
    linked = {**FAKE_USER_ROW, "last_login_at": datetime(2026, 6, 10, 13, 0, 0)}
    conn.execute = AsyncMock(side_effect=[_make_cursor(None), _make_cursor(linked)])

    row = await get_or_provision_user(conn, _principal())

    assert row == linked
    # 1st query: select by external id (miss); 2nd: UPDATE ... WHERE email
    assert conn.execute.await_count == 2
    update_sql = conn.execute.await_args_list[1].args[0]
    assert "external_id IS NULL" in update_sql


@pytest.mark.asyncio
async def test_unprovisioned_user_gets_403():
    """Allowlisted but no app.users row: sync and auth.yml disagree."""
    conn = AsyncMock()
    conn.execute = AsyncMock(
        side_effect=[_make_cursor(None), _make_cursor(None), _make_cursor(None)]
    )

    with pytest.raises(HTTPException) as exc:
        await get_or_provision_user(conn, _principal())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_already_linked_to_other_id_gets_403_not_rebound():
    """A row linked to a different external id must never be silently rebound."""
    conn = AsyncMock()
    existing = {"external_id": "other-oid", "identity_provider": "aad"}
    conn.execute = AsyncMock(
        side_effect=[_make_cursor(None), _make_cursor(None), _make_cursor(existing)]
    )

    with pytest.raises(HTTPException) as exc:
        await get_or_provision_user(conn, _principal())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_principal_without_external_id_gets_403():
    conn = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_or_provision_user(conn, _principal(external_id=None))
    assert exc.value.status_code == 403
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_dev_bypass_upserts_dev_admin():
    conn = AsyncMock()
    dev_row = {
        **FAKE_USER_ROW,
        "email": "dev@localhost",
        "external_id": "dev-bypass",
        "identity_provider": "dev",
        "role": "admin",
    }
    conn.execute = AsyncMock(return_value=_make_cursor(dev_row))

    principal = _principal(
        email="dev@localhost", external_id="dev-bypass", identity_provider="dev"
    )
    row = await get_or_provision_user(conn, principal)

    assert row["role"] == "admin"
    insert_sql = conn.execute.await_args_list[0].args[0]
    assert "ON CONFLICT (email)" in insert_sql


# ---------------------------------------------------------------------------
# GET /api/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_returns_current_user(client, fake_conn):
    dev_row = {
        **FAKE_USER_ROW,
        "email": "dev@localhost",
        "external_id": "dev-bypass",
        "identity_provider": "dev",
        "role": "admin",
    }
    fake_conn.execute = AsyncMock(return_value=_make_cursor(dev_row))

    resp = await client.get("/api/me")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "id": str(_USER_ID),
        "email": "dev@localhost",
        "display_name": None,
        "role": "admin",
    }
