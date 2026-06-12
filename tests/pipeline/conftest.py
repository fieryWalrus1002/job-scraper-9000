"""Shared fixtures for ``tests/pipeline/`` — a fresh, migrated Postgres
per test, plus user-seeding helpers."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Json

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


@pytest.fixture
def migrated_pg():
    """Spin up Postgres, run all migrations to head, yield the conn string."""
    if not _docker_available():
        pytest.skip("Docker not available")

    name = f"test-pipeline-{uuid.uuid4().hex[:8]}"
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

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env={
            **os.environ,
            "DATABASE_URL": conn_str,
            "BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
        },
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"alembic upgrade failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )

    yield conn_str

    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)


skip_if_no_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


def pytest_collection_modifyitems(items):
    """Auto-tag every test that needs a live Postgres (``migrated_pg``) with the
    ``docker`` marker, so the default ``-m "not docker"`` run skips them for a
    fast local loop. CI runs the docker-marked suite in a separate step."""
    for item in items:
        if "migrated_pg" in getattr(item, "fixturenames", ()):
            item.add_marker("docker")


# ---------------------------------------------------------------------------
# Seed helpers — minimal-but-valid SearchConfigInput / CandidateProfileInput.
# ---------------------------------------------------------------------------


def valid_search_payload() -> dict:
    return {
        "user": {
            "display_name": "Test User",
            "email": "test@example.com",
            "home_location": {"city": "Seattle", "region": "WA", "country": "US"},
        },
        "search_profile": {"name": "ML Engineer search"},
        "roles": {"target_titles": {"preferred": ["ML Engineer", "ML Ops"]}},
        "organizations": {"target_companies": ["acme", "initech"]},
    }


def valid_profile_payload() -> dict:
    return {
        "summary": "Experienced ML engineer with infra background. " * 2,
        "level": "Senior individual contributor",
        "core_skills": ["Python", "PyTorch"],
    }


def seed_user(
    conn: psycopg.Connection,
    email: str,
    *,
    with_profile: bool = True,
    with_search: bool = True,
) -> str:
    uid_row = conn.execute(
        "INSERT INTO app.users (email) VALUES (%s) RETURNING id::text", (email,)
    ).fetchone()
    assert uid_row is not None
    uid = uid_row[0]

    if with_search:
        conn.execute(
            """
            INSERT INTO app.user_search_configs (user_id, payload, policies)
            VALUES (%s::uuid, %s, %s)
            """,
            (uid, Json(valid_search_payload()), Json({})),
        )
    if with_profile:
        conn.execute(
            """
            INSERT INTO app.candidate_profiles (user_id, payload, profile_version)
            VALUES (%s::uuid, %s, %s)
            """,
            (uid, Json(valid_profile_payload()), "2026-06-12.testhashabcd"),
        )
    return uid
