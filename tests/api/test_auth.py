"""Tests for the auth dependency (current_principal) and route gating."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from api import auth
from api.dependencies import get_pool
from api.main import app

from .conftest import _FakePool, _make_cursor


def _make_header(email: str, roles: list[str] | None = None) -> str:
    claims = {"userDetails": email, "userRoles": roles or []}
    return base64.b64encode(json.dumps(claims).encode()).decode()


def _pool_with_empty_jobs() -> _FakePool:
    """Fake pool that returns count=0, rows=[] for list_jobs."""
    conn = AsyncMock()
    count_cur = _make_cursor({"n": 0})
    list_cur = AsyncMock()
    list_cur.fetchall = AsyncMock(return_value=[])
    conn.execute = AsyncMock(side_effect=[count_cur, list_cur])
    return _FakePool(conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_jobs(headers: dict | None = None) -> int:
    """Hit GET /api/jobs and return the status code."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/jobs", headers=headers or {})
    return resp.status_code


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_auth(monkeypatch):
    """Ensure each test starts with clean auth state with bypass disabled."""
    monkeypatch.delenv(auth.BYPASS_VAR, raising=False)
    auth.init([])
    yield
    auth.init([])


# ---------------------------------------------------------------------------
# Bypass mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bypass_mode_passes_without_header(monkeypatch):
    monkeypatch.setenv(auth.BYPASS_VAR, "1")
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs()
    finally:
        app.dependency_overrides.clear()
    assert status == 200


@pytest.mark.asyncio
async def test_health_public_in_bypass_mode(monkeypatch):
    monkeypatch.setenv(auth.BYPASS_VAR, "1")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Bypass disabled (AUTH_BYPASS=0 must not bypass)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bypass_zero_string_enforces_auth(monkeypatch):
    monkeypatch.setenv(auth.BYPASS_VAR, "0")
    auth.init(["allowed@example.com"])
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs()
    finally:
        app.dependency_overrides.clear()
    assert status == 401


# ---------------------------------------------------------------------------
# Enforced mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforced_valid_allowlisted_email_returns_200():
    auth.init(["allowed@example.com"])
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs(
            {"X-MS-CLIENT-PRINCIPAL": _make_header("allowed@example.com")}
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 200


@pytest.mark.asyncio
async def test_enforced_non_allowlisted_email_returns_403():
    auth.init(["allowed@example.com"])
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs(
            {"X-MS-CLIENT-PRINCIPAL": _make_header("other@example.com")}
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 403


@pytest.mark.asyncio
async def test_enforced_missing_header_returns_401():
    auth.init(["allowed@example.com"])
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs()
    finally:
        app.dependency_overrides.clear()
    assert status == 401


@pytest.mark.asyncio
async def test_enforced_malformed_base64_returns_401():
    auth.init(["allowed@example.com"])
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs({"X-MS-CLIENT-PRINCIPAL": "not!!valid!!base64"})
    finally:
        app.dependency_overrides.clear()
    assert status == 401


@pytest.mark.asyncio
async def test_email_matching_is_case_insensitive():
    auth.init(["Allowed@Example.Com"])
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs(
            {"X-MS-CLIENT-PRINCIPAL": _make_header("allowed@example.com")}
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 200


# ---------------------------------------------------------------------------
# Health is always public
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_public_no_header_enforced_mode():
    auth.init(["allowed@example.com"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_public_with_empty_allowlist():
    auth.init([])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200
