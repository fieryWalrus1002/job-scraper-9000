"""Shared fixtures for API tests.

The mock pool replaces the real psycopg AsyncConnectionPool so tests run
without a live Postgres instance.  Each fixture controls what execute()
returns so individual tests can assert on specific query results.
"""

from __future__ import annotations

import os
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import uuid

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from api import auth
from api.main import app
from api.dependencies import current_user, get_pool
from api.schemas import User

# Stable fake identity for route tests: current_user is overridden in the
# client fixture so route tests don't consume fake_conn.execute calls on
# provisioning. Provisioning itself is tested directly in test_users.py.
TEST_USER = User(
    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    email="dev@localhost",
    display_name="Dev Bypass",
    role="admin",
)

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
    conn = AsyncMock()
    # Default: conn.transaction() returns an async-context-manager mock.
    # Tests that need specific transaction behavior can override this.
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=True)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)
    return conn


@pytest.fixture
def fake_pool(fake_conn: AsyncMock) -> _FakePool:
    return _FakePool(fake_conn)


@pytest.fixture
async def client(fake_pool: _FakePool, monkeypatch) -> AsyncClient:  # type: ignore[misc]
    monkeypatch.setenv(auth.BYPASS_VAR, "1")
    app.dependency_overrides[get_pool] = lambda: fake_pool
    app.dependency_overrides[current_user] = lambda: TEST_USER
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


# ---------------------------------------------------------------------------
# Live-Postgres fixtures (docker) — shared by the migration + endpoint DB tests.
# Mock-pool tests above don't touch these; they only matter under `-m docker`.
# ---------------------------------------------------------------------------

_PG_IMAGE = "postgres:16-alpine"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=5
            ).returncode
            == 0
        )
    except Exception:
        return False


skip_if_no_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


def _container_ip(name: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            name,
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_alembic(
    revision: str,
    conn_str: str,
    command: str = "upgrade",
    extra_env: dict[str, str] | None = None,
) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", command, revision],
        env={**os.environ, "DATABASE_URL": conn_str, **(extra_env or {})},
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"alembic {command} {revision!r} failed:\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )


@pytest.fixture
def fresh_pg():
    """Spin up a fresh postgres:16-alpine container; yield its connection string."""
    if not _docker_available():
        pytest.skip("Docker not available")

    name = f"test-migrations-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_USER=test",
            "-e",
            "POSTGRES_PASSWORD=test",
            "-e",
            "POSTGRES_DB=test",
            _PG_IMAGE,
        ],
        check=True,
        capture_output=True,
    )

    conn_str = f"postgresql://test:test@{_container_ip(name)}:5432/test"

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(conn_str, connect_timeout=2):
                break
        except Exception:
            time.sleep(0.5)
    else:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        pytest.fail("Postgres container did not become ready within 20s")

    yield conn_str

    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
