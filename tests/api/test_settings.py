"""Endpoint tests for /api/settings (Phase 12, slice 3).

Mock pool fixture — no live Postgres. Validation behaviour (422 field errors)
is exercised through the real FastAPI/Pydantic path; the DB write is mocked.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import _make_cursor

_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.[0-9a-f]{12}$")

# Minimal payloads that satisfy the user_config models (extra="forbid",
# min_length constraints). Kept inline so the test states its own contract.
VALID_PROFILE: dict[str, Any] = {
    "summary": "Backend engineer with a decade of Python and data work.",
    "level": "senior software engineer",
    "core_skills": ["python", "postgres"],
}

VALID_SEARCH: dict[str, Any] = {
    "user": {"display_name": "Dev", "email": "dev@localhost"},
    "search_profile": {"name": "default"},
    "roles": {"target_titles": {"preferred": ["Software Engineer"]}},
}

FAKE_PROFILE_ROW: dict[str, Any] = {
    "payload": VALID_PROFILE,
    "profile_version": "2026-06-11.abcdef012345",
    "updated_at": datetime(2026, 6, 11, 12, 0, 0),
}

FAKE_SEARCH_ROW: dict[str, Any] = {
    "payload": VALID_SEARCH,
    "policies": {"remote": {"acceptable_classifications": ["fully_remote"]}},
    "updated_at": datetime(2026, 6, 11, 12, 0, 0),
}


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------


async def test_get_settings_onboarding_state(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    # Neither table has a row yet — every field comes back null.
    fake_conn.execute = AsyncMock(side_effect=[_make_cursor(), _make_cursor()])
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "profile": None,
        "profile_version": None,
        "profile_updated_at": None,
        "search": None,
        "policies": None,
        "search_updated_at": None,
    }


async def test_get_settings_configured(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(
        side_effect=[_make_cursor(FAKE_PROFILE_ROW), _make_cursor(FAKE_SEARCH_ROW)]
    )
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["profile"] == VALID_PROFILE
    assert data["profile_version"] == "2026-06-11.abcdef012345"
    assert data["search"] == VALID_SEARCH
    assert data["policies"]["remote"]["acceptable_classifications"] == ["fully_remote"]


# ---------------------------------------------------------------------------
# PUT /api/settings/profile
# ---------------------------------------------------------------------------


async def test_put_profile_recomputes_version_server_side(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    # The RETURNING row echoes whatever version the route computed; capture the
    # execute call to assert the stored version matches what we returned.
    captured: dict[str, Any] = {}

    async def _execute(sql: str, params: dict[str, Any]) -> AsyncMock:
        captured.update(params)
        return _make_cursor(
            {"profile_version": params["version"], "updated_at": datetime(2026, 6, 11)}
        )

    fake_conn.execute = AsyncMock(side_effect=_execute)

    # A client-supplied profile_version must be ignored — server recomputes.
    resp = await client.put(
        "/api/settings/profile", json={**VALID_PROFILE, "profile_version": "client-set"}
    )
    assert resp.status_code == 200
    version = resp.json()["profile_version"]
    assert _VERSION_RE.match(version), version
    assert version != "client-set"
    assert captured["version"] == version


async def test_put_profile_invalid_returns_422(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock()  # must never be reached
    # Missing core_skills + too-short summary.
    resp = await client.put("/api/settings/profile", json={"summary": "too short"})
    assert resp.status_code == 422
    fake_conn.execute.assert_not_called()


async def test_put_profile_unknown_key_returns_422(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock()
    resp = await client.put(
        "/api/settings/profile", json={**VALID_PROFILE, "bogus_field": 1}
    )
    assert resp.status_code == 422
    fake_conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# PUT /api/settings/search
# ---------------------------------------------------------------------------


async def test_put_search_derives_policies(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    captured: dict[str, Any] = {}

    async def _execute(sql: str, params: dict[str, Any]) -> AsyncMock:
        captured.update(params)
        # Echo the derived policies back through RETURNING.
        return _make_cursor(
            {
                "policies": params["policies"].obj,
                "updated_at": datetime(2026, 6, 11),
            }
        )

    fake_conn.execute = AsyncMock(side_effect=_execute)

    resp = await client.put("/api/settings/search", json=VALID_SEARCH)
    assert resp.status_code == 200
    policies = resp.json()["policies"]
    # Permissive search config → all remote classes acceptable, no exclusions.
    assert "unclear" in policies["remote"]["acceptable_classifications"]
    assert policies["prefilter"]["excluded_title_terms"] == []
