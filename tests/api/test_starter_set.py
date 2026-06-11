"""Tests for starter-set seeding (api/starter_set.py)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.starter_set import STARTER_RUN_ID, ensure_starter_set, seed_starter_set

from .conftest import _make_cursor

_USER_ID = uuid.uuid4()


def _user(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": _USER_ID,
        "email": "friend@example.com",
        "display_name": None,
        "role": "member",
        "starter_seeded_at": None,
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_seed_inserts_scores_for_example_postings():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=_make_cursor())

    await seed_starter_set(conn, _USER_ID)

    sql, params = conn.execute.await_args.args
    assert "INSERT INTO raw.job_scores" in sql
    assert "example-%" in sql
    assert "ON CONFLICT (user_id, dedup_hash) DO NOTHING" in sql
    assert params["run_id"] == STARTER_RUN_ID
    assert params["user_id"] == _USER_ID


@pytest.mark.asyncio
async def test_member_with_empty_feed_is_seeded_then_marked():
    conn = AsyncMock()
    marked = datetime(2026, 6, 11, 12, 0, 0)
    conn.execute = AsyncMock(
        side_effect=[
            _make_cursor(),  # has-scores check: empty
            _make_cursor(),  # seed insert
            _make_cursor({"starter_seeded_at": marked}),  # mark
        ]
    )

    user = _user()
    await ensure_starter_set(conn, user)

    assert conn.execute.await_count == 3
    assert "INSERT INTO raw.job_scores" in conn.execute.await_args_list[1].args[0]
    assert "UPDATE app.users" in conn.execute.await_args_list[2].args[0]
    assert user["starter_seeded_at"] == marked


@pytest.mark.asyncio
async def test_member_with_existing_scores_is_marked_not_seeded():
    conn = AsyncMock()
    conn.execute = AsyncMock(
        side_effect=[
            _make_cursor({"?column?": 1}),  # has-scores check: hit
            _make_cursor({"starter_seeded_at": datetime(2026, 6, 11)}),  # mark
        ]
    )

    await ensure_starter_set(conn, _user())

    # No seed insert between the check and the mark.
    assert conn.execute.await_count == 2
    assert "UPDATE app.users" in conn.execute.await_args_list[1].args[0]
    assert all(
        "INSERT INTO raw.job_scores" not in c.args[0]
        for c in conn.execute.await_args_list
    )


@pytest.mark.asyncio
async def test_admin_is_never_seeded():
    conn = AsyncMock()
    conn.execute = AsyncMock()

    await ensure_starter_set(conn, _user(role="admin"))

    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_marked_member_is_skipped():
    conn = AsyncMock()
    conn.execute = AsyncMock()

    await ensure_starter_set(conn, _user(starter_seeded_at=datetime(2026, 6, 1)))

    conn.execute.assert_not_awaited()
