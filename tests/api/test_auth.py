"""Tests for the auth dependency (current_principal) and route gating."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from api import auth
from api.dependencies import get_pool
from api.main import app

from .conftest import _FakePool, _make_cursor


def _make_header(email: str, roles: list[str] | None = None, **extra) -> str:
    claims = {"userDetails": email, "userRoles": roles or [], **extra}
    return base64.b64encode(json.dumps(claims).encode()).decode()


def _allow(*emails: str) -> None:
    auth.init([auth.AuthUser(email=e, role="member") for e in emails])


def _pool_with_empty_jobs(provision_user: bool = False) -> _FakePool:
    """Fake pool that returns count=0, rows=[] for list_jobs.

    With provision_user=True, the first execute returns a user row — needed
    by tests that reach the route handler, since CurrentUser resolves the
    principal against app.users before the jobs queries run.
    """
    conn = AsyncMock()
    cursors = []
    if provision_user:
        cursors.append(
            _make_cursor(
                {
                    "id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
                    "email": "allowed@example.com",
                    "display_name": None,
                    "role": "member",
                    # Already provisioned and seeded → ensure_starter_set
                    # short-circuits without extra queries.
                    "starter_seeded_at": datetime(2026, 6, 11, 12, 0, 0),
                }
            )
        )
    count_cur = _make_cursor({"n": 0})
    list_cur = AsyncMock()
    list_cur.fetchall = AsyncMock(return_value=[])
    cursors += [count_cur, list_cur]
    conn.execute = AsyncMock(side_effect=cursors)
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
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs(
        provision_user=True
    )
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
    _allow("allowed@example.com")
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
    _allow("allowed@example.com")
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs(
        provision_user=True
    )
    try:
        status = await _get_jobs(
            {
                "X-MS-CLIENT-PRINCIPAL": _make_header(
                    "allowed@example.com", identityProvider="aad", userId="swa-1"
                )
            }
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 200


@pytest.mark.asyncio
async def test_enforced_non_allowlisted_email_returns_403():
    _allow("allowed@example.com")
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
    _allow("allowed@example.com")
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs()
    finally:
        app.dependency_overrides.clear()
    assert status == 401


@pytest.mark.asyncio
async def test_enforced_malformed_base64_returns_401():
    _allow("allowed@example.com")
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs()
    try:
        status = await _get_jobs({"X-MS-CLIENT-PRINCIPAL": "not!!valid!!base64"})
    finally:
        app.dependency_overrides.clear()
    assert status == 401


@pytest.mark.asyncio
async def test_email_matching_is_case_insensitive():
    _allow("Allowed@Example.Com")
    app.dependency_overrides[get_pool] = lambda: _pool_with_empty_jobs(
        provision_user=True
    )
    try:
        status = await _get_jobs(
            {
                "X-MS-CLIENT-PRINCIPAL": _make_header(
                    "allowed@example.com", identityProvider="aad", userId="swa-1"
                )
            }
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 200


# ---------------------------------------------------------------------------
# Health is always public
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_public_no_header_enforced_mode():
    _allow("allowed@example.com")
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


# ---------------------------------------------------------------------------
# Config loading (users format)
# ---------------------------------------------------------------------------


def _write_config(tmp_path, monkeypatch, content: str) -> None:
    cfg = tmp_path / "auth.yml"
    cfg.write_text(content)
    monkeypatch.setattr(auth, "_CONFIG_PATH", cfg)


def test_load_auth_config_parses_users(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        "users:\n"
        "  - email: Owner@Example.com\n"
        "    role: admin\n"
        "  - email: friend@example.com\n",
    )
    users = auth.load_auth_config()
    assert users == [
        auth.AuthUser(email="owner@example.com", role="admin"),
        auth.AuthUser(email="friend@example.com", role="member"),
    ]


def test_load_auth_config_rejects_legacy_format(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "allowed_emails:\n  - a@example.com\n")
    with pytest.raises(RuntimeError, match="legacy"):
        auth.load_auth_config()


def test_load_auth_config_rejects_bad_role(tmp_path, monkeypatch):
    _write_config(
        tmp_path, monkeypatch, "users:\n  - email: a@example.com\n    role: root\n"
    )
    with pytest.raises(RuntimeError, match="invalid role"):
        auth.load_auth_config()


def test_load_auth_config_rejects_duplicate_emails(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        "users:\n  - email: a@example.com\n  - email: A@example.com\n",
    )
    with pytest.raises(RuntimeError, match="duplicate"):
        auth.load_auth_config()


def test_load_auth_config_rejects_empty_users(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "users: []\n")
    with pytest.raises(RuntimeError, match="non-empty"):
        auth.load_auth_config()


# ---------------------------------------------------------------------------
# Stable external id extraction (Entra oid preferred, SWA userId fallback)
# ---------------------------------------------------------------------------

_OID_URI = "http://schemas.microsoft.com/identity/claims/objectidentifier"


def test_external_id_prefers_entra_oid():
    claims = {
        "userId": "swa-hash",
        "claims": [{"typ": _OID_URI, "val": "oid-123"}],
    }
    assert auth._extract_external_id(claims) == "oid-123"


def test_external_id_accepts_short_oid_typ():
    claims = {"userId": "swa-hash", "claims": [{"typ": "oid", "val": "oid-456"}]}
    assert auth._extract_external_id(claims) == "oid-456"


def test_external_id_falls_back_to_swa_user_id():
    assert auth._extract_external_id({"userId": "swa-hash"}) == "swa-hash"


def test_external_id_never_falls_back_to_email():
    claims = {"userDetails": "user@example.com"}
    assert auth._extract_external_id(claims) is None


def test_allowlist_rejection_logs_the_rejected_identity(caplog):
    _allow("allowed@example.com")
    header = _make_header("guest_gmail.com#EXT#@tenant", identityProvider="aad")
    request = Request(
        {"type": "http", "headers": [(b"x-ms-client-principal", header.encode())]}
    )

    with caplog.at_level("WARNING", logger="api.auth"):
        with pytest.raises(Exception) as exc:
            auth.current_principal(request)

    assert getattr(exc.value, "status_code", None) == 403
    assert any(
        "guest_gmail.com#ext#@tenant" in r.message and "aad" in r.message
        for r in caplog.records
    )


def test_principal_carries_external_id_and_provider():
    _allow("allowed@example.com")
    header = _make_header(
        "allowed@example.com",
        identityProvider="aad",
        userId="swa-hash",
        claims=[{"typ": _OID_URI, "val": "oid-789"}],
    )
    request = Request(
        {"type": "http", "headers": [(b"x-ms-client-principal", header.encode())]}
    )

    principal = auth.current_principal(request)

    assert principal.email == "allowed@example.com"
    assert principal.external_id == "oid-789"
    assert principal.identity_provider == "aad"
