"""Shared fixtures for API tests.

The mock pool replaces the real psycopg AsyncConnectionPool so tests run
without a live Postgres instance.  Each fixture controls what execute()
returns so individual tests can assert on specific query results.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from api import auth
from api.main import app, get_pool

# ---------------------------------------------------------------------------
# Representative fake records
# ---------------------------------------------------------------------------

FAKE_JOB_ROW: dict[str, Any] = {
    "dedup_hash": "deadbeef" * 8,
    "source": "linkedin",
    "source_url": "https://example.com/jobs/1",
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "location": "Remote, USA",
    "posted_at": "2026-05-01",
    "remote_classification": "fully_remote",
    "salary_min_usd": 150000,
    "salary_max_usd": 200000,
    "salary_period": "yearly",
    "fit_score": 4,
    "confidence": "high",
    "score_rationale": "Strong match on Python and data pipelines.",
    "failure_reason": None,
    "scored_at": datetime(2026, 6, 1, 12, 0, 0),
}

FAKE_DETAIL_ROW: dict[str, Any] = {
    **FAKE_JOB_ROW,
    "source": "linkedin",
    "source_job_id": "job-12345",
    "description": "We are looking for a senior software engineer...",
    "scraped_at": datetime(2026, 5, 31, 8, 0, 0),
    "ai_fit_detail": {
        "top_matches": ["Python", "data pipelines"],
        "gaps": ["Kubernetes"],
        "hard_concerns": [],
        "core_job_duties": ["design systems", "write code"],
    },
    "pipeline_metadata": {"prefilter": "remote_filter_candidate"},
    "run_id": "run-abc",
    "model": "claude-sonnet-4-6",
    "provider": "anthropic",
    "profile_version": "v2",
    "metadata": {"commit": "abc123"},
    "ingested_at": datetime(2026, 6, 1, 13, 0, 0),
}


# ---------------------------------------------------------------------------
# Async mock pool builder
# ---------------------------------------------------------------------------


class _FakePool:
    """Drop-in for AsyncConnectionPool that returns a controlled async conn."""

    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self):  # type: ignore[override]
        yield self._conn


def _make_cursor(*rows: Any) -> AsyncMock:
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value=rows[0] if rows else None)
    cur.fetchall = AsyncMock(return_value=list(rows))
    return cur


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_conn() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def fake_pool(fake_conn: AsyncMock) -> _FakePool:
    return _FakePool(fake_conn)


@pytest.fixture
async def client(fake_pool: _FakePool, monkeypatch) -> AsyncClient:  # type: ignore[misc]
    monkeypatch.setenv(auth.BYPASS_VAR, "1")
    app.dependency_overrides[get_pool] = lambda: fake_pool
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def setup_list_response(
    fake_conn: AsyncMock,
    rows: list[dict[str, Any]],
    total: int | None = None,
) -> None:
    """Wire fake_conn.execute to return count then rows for list_jobs."""
    count_cursor = _make_cursor({"n": total if total is not None else len(rows)})
    list_cursor = AsyncMock()
    list_cursor.fetchall = AsyncMock(return_value=rows)
    fake_conn.execute = AsyncMock(side_effect=[count_cursor, list_cursor])


def setup_detail_response(
    fake_conn: AsyncMock,
    row: dict[str, Any] | None,
) -> None:
    """Wire fake_conn.execute to return a single row for get_job."""
    cur = _make_cursor(row)
    fake_conn.execute = AsyncMock(return_value=cur)
