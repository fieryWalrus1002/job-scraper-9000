"""Shared fixtures for ``tests/pipeline/`` — a fresh, migrated Postgres
per test."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest

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
