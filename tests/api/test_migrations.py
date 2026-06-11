"""Migration integration tests: verify upgrade/downgrade on real Postgres data.

Each test seeds rows with statuses that a migration transforms, runs the
migration against a live DB, then asserts correctness. This catches bugs where
constraint operations and data backfills are ordered incorrectly.

Run: uv run pytest tests/api/test_migrations.py -v -m docker
Requires Docker. Skipped automatically if Docker is unavailable.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.docker

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


# ---------------------------------------------------------------------------
# 0005: rename withdrawn/saved, add passed
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_0005_upgrade_transforms_statuses_and_enforces_constraint(fresh_pg):
    """Upgrade 0005 must backfill renamed values and install the new constraint.

    This is the test that would have caught the migration bug: candidate_withdrew
    is not in the 0004 constraint, so the UPDATE must happen after the DROP.
    """
    _run_alembic("0004", fresh_pg)

    with psycopg.connect(fresh_pg) as conn:
        conn.execute("""
            INSERT INTO app.user_applications (dedup_hash, status) VALUES
                ('hash-withdrawn', 'withdrawn'),
                ('hash-saved',     'saved'),
                ('hash-applied',   'applied'),
                ('hash-maybe',     'maybe')
        """)

    _run_alembic("0005", fresh_pg)

    with psycopg.connect(fresh_pg) as conn:
        rows = dict(
            conn.execute(
                "SELECT dedup_hash, status FROM app.user_applications"
            ).fetchall()
        )

    assert rows["hash-withdrawn"] == "candidate_withdrew"
    assert rows["hash-saved"] == "maybe"
    assert rows["hash-applied"] == "applied"
    assert rows["hash-maybe"] == "maybe"

    # Old values must be rejected by the new constraint
    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO app.user_applications (dedup_hash, status) "
                "VALUES ('hash-constraint-check', 'withdrawn')"
            )

    # New values added by 0005 must be accepted
    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO app.user_applications (dedup_hash, status) "
            "VALUES ('hash-passed', 'passed')"
        )


@skip_if_no_docker
def test_0005_downgrade_remaps_new_statuses(fresh_pg):
    """Downgrade from 0005 back to 0004 must remap candidate_withdrew/passed to withdrawn."""
    _run_alembic("0005", fresh_pg)

    with psycopg.connect(fresh_pg) as conn:
        conn.execute("""
            INSERT INTO app.user_applications (dedup_hash, status) VALUES
                ('hash-candidate-withdrew', 'candidate_withdrew'),
                ('hash-passed',            'passed'),
                ('hash-applied',           'applied')
        """)

    _run_alembic("0004", fresh_pg, command="downgrade")

    with psycopg.connect(fresh_pg) as conn:
        rows = dict(
            conn.execute(
                "SELECT dedup_hash, status FROM app.user_applications"
            ).fetchall()
        )

    assert rows["hash-candidate-withdrew"] == "withdrawn"
    assert rows["hash-passed"] == "withdrawn"
    assert rows["hash-applied"] == "applied"

    # After downgrade, 'passed' must be rejected and 'withdrawn' accepted again
    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO app.user_applications (dedup_hash, status) "
                "VALUES ('hash-constraint-check', 'passed')"
            )


# ---------------------------------------------------------------------------
# 0006: create app.users + bootstrap admin seed
# ---------------------------------------------------------------------------

_BOOTSTRAP = {"BOOTSTRAP_ADMIN_EMAIL": "Bootstrap-Admin@Example.com"}


@skip_if_no_docker
def test_0006_creates_users_and_seeds_bootstrap_admin(fresh_pg):
    """BOOTSTRAP_ADMIN_EMAIL takes precedence over any local auth.yml, so the
    seed is deterministic across machines with and without that file."""
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        rows = conn.execute(
            "SELECT email, role, external_id, identity_provider FROM app.users"
        ).fetchall()

    assert rows == [("bootstrap-admin@example.com", "admin", None, None)]


@skip_if_no_docker
def test_0006_users_constraints(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg, autocommit=True) as conn:
        # duplicate email rejected
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO app.users (email) VALUES ('bootstrap-admin@example.com')"
            )
        # invalid role rejected
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO app.users (email, role) VALUES ('x@example.com', 'root')"
            )
        # duplicate (identity_provider, external_id) rejected once linked
        conn.execute(
            "INSERT INTO app.users (email, identity_provider, external_id) "
            "VALUES ('a@example.com', 'aad', 'oid-1')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO app.users (email, identity_provider, external_id) "
                "VALUES ('b@example.com', 'aad', 'oid-1')"
            )
        # multiple unlinked rows (NULL external_id) are fine
        conn.execute("INSERT INTO app.users (email) VALUES ('c@example.com')")
        conn.execute("INSERT INTO app.users (email) VALUES ('d@example.com')")


@skip_if_no_docker
def test_0006_downgrade_drops_users(fresh_pg):
    _run_alembic("0006", fresh_pg, extra_env=_BOOTSTRAP)
    _run_alembic("0005", fresh_pg, command="downgrade", extra_env=_BOOTSTRAP)

    with psycopg.connect(fresh_pg) as conn:
        exists = conn.execute("SELECT to_regclass('app.users') IS NOT NULL").fetchone()[
            0
        ]
    assert exists is False
