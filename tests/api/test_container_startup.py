"""
Docker-based startup tests for the API container.

These tests verify how the container behaves when DATABASE_URL is missing or
unreachable — the suspected cause of ACA crashes in the Phase 9 deployment.

Run with: uv run pytest tests/api/test_container_startup.py -v -m docker

Requires Docker to be running locally. Skipped automatically if Docker is not
available or the image hasn't been built yet.

Build the image first:
  docker build -f docker/app.Dockerfile --target backend -t job-scraper-api-test:local .
"""

from __future__ import annotations

import subprocess
import time
import uuid

import httpx
import pytest

IMAGE = "job-scraper-api-test:local"
_HOST_PORT_BASE = 18000


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _image_exists(tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", tag], capture_output=True, timeout=5
    )
    return result.returncode == 0


pytestmark = pytest.mark.docker

skip_if_no_docker = pytest.mark.skipif(
    not _docker_available() or not _image_exists(IMAGE),
    reason=f"Docker not available or image {IMAGE!r} not built",
)


class _Container:
    """Context manager that runs a container and cleans it up on exit."""

    def __init__(self, env: dict[str, str], port: int) -> None:
        self.name = f"test-api-{uuid.uuid4().hex[:8]}"
        self.port = port
        self._env = env
        self._proc: subprocess.Popen | None = None

    def __enter__(self) -> "_Container":
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            self.name,
            "-p",
            f"{self.port}:8000",
        ]
        for k, v in self._env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(IMAGE)
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return self

    def __exit__(self, *_) -> None:
        subprocess.run(["docker", "stop", self.name], capture_output=True, timeout=15)
        if self._proc:
            self._proc.wait(timeout=10)

    def wait_for_exit(self, timeout: float = 10.0) -> int | None:
        """Return exit code if process exits within timeout, else None."""
        try:
            return self._proc.wait(timeout=timeout)  # type: ignore[union-attr]
        except subprocess.TimeoutExpired:
            return None

    def poll(self) -> int | None:
        return self._proc.poll() if self._proc else None

    def base_url(self) -> str:
        return f"http://localhost:{self.port}"


def _wait_for_health(base_url: str, timeout: float = 15.0) -> httpx.Response | None:
    """Poll /api/health until a response arrives or timeout. Returns None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=1.0)
            return r
        except httpx.TransportError:
            time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_container_exits_cleanly_without_database_url():
    """Container must exit with code 3 and write a clear CRITICAL message to
    stderr when DATABASE_URL is absent — not a raw traceback."""
    with _Container(env={"AUTH_BYPASS": "1"}, port=_HOST_PORT_BASE) as c:
        exit_code = c.wait_for_exit(timeout=15.0)
        assert exit_code == 3, (
            f"Expected exit code 3 (missing DATABASE_URL) but got {exit_code!r}. "
            "Lifespan must call sys.exit(3) with a clear error message."
        )
        stderr = c._proc.stderr.read().decode(errors="replace")  # type: ignore[union-attr]
        assert "DATABASE_URL" in stderr, (
            f"Exit code was 3 but stderr didn't mention DATABASE_URL:\n{stderr}"
        )


@skip_if_no_docker
def test_container_exits_with_unreachable_database():
    """Container fails fast when DATABASE_URL points at an unreachable host.

    Alembic runs during lifespan startup and requires a live DB connection.
    migrations/env.py sets connect_timeout=5 s so the container exits well
    before the OS TCP retry timer (~63 s) would fire. ACA will then restart it.
    """
    env = {
        "AUTH_BYPASS": "1",
        "DATABASE_URL": "postgresql://user:pass@192.0.2.1:5432/db",
    }
    with _Container(env=env, port=_HOST_PORT_BASE + 1) as c:
        exit_code = c.wait_for_exit(timeout=15.0)
        assert exit_code == 3, (
            f"Expected exit code 3 (startup failure) but got {exit_code!r}."
        )


@skip_if_no_docker
def test_container_health_ok_with_postgres():
    """Container returns 200 on /api/health when a real Postgres is reachable."""
    pg_name = f"test-pg-{uuid.uuid4().hex[:8]}"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                pg_name,
                "-e",
                "POSTGRES_PASSWORD=test",
                "-e",
                "POSTGRES_USER=test",
                "-e",
                "POSTGRES_DB=test",
                "postgres:16-alpine",
            ],
            check=True,
            capture_output=True,
        )
        # Give postgres a moment to accept connections
        time.sleep(3)

        pg_ip_result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                pg_name,
            ],
            capture_output=True,
            text=True,
        )
        pg_ip = pg_ip_result.stdout.strip()
        db_url = f"postgresql://test:test@{pg_ip}:5432/test"

        env = {"AUTH_BYPASS": "1", "DATABASE_URL": db_url}
        with _Container(env=env, port=_HOST_PORT_BASE + 2) as c:
            exit_code = c.wait_for_exit(timeout=8.0)
            assert exit_code is None, (
                f"Container crashed (exit {exit_code}) even with a live DB"
            )
            resp = _wait_for_health(c.base_url())
            assert resp is not None, "/api/health never responded"
            assert resp.status_code == 200, (
                f"Expected 200 with live DB but got {resp.status_code}. "
                f"Body: {resp.text}"
            )
    finally:
        subprocess.run(["docker", "stop", pg_name], capture_output=True, timeout=15)
