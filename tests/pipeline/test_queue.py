"""Integration tests for ``pipeline.queue.claim_next``.

Source-serialization (Phase 13 spec §6: ≤1 in-flight per source globally) is
enforced inside the SQL claim, not in Python. These tests run against a real
Postgres so ``FOR UPDATE SKIP LOCKED`` and the ``source NOT IN (...)`` filter
both exercise their real semantics.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest

from pipeline.queue import claim_next

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


@pytest.fixture
def migrated_pg():
    """Spin up Postgres, run all migrations to head, yield the conn string."""
    if not _docker_available():
        pytest.skip("Docker not available")

    name = f"test-queue-{uuid.uuid4().hex[:8]}"
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


def _new_user(conn: psycopg.Connection, email: str) -> str:
    row = conn.execute(
        "INSERT INTO app.users (email) VALUES (%s) RETURNING id::text", (email,)
    ).fetchone()
    assert row is not None
    return row[0]


def _enqueue(
    conn: psycopg.Connection, *, run_id: str, user_id: str, source: str
) -> None:
    conn.execute(
        """
        INSERT INTO pipe.scrape_jobs (run_id, user_id, source, query_payload)
        VALUES (%s, %s::uuid, %s, '{}'::jsonb)
        """,
        (run_id, user_id, source),
    )


@skip_if_no_docker
def test_claim_next_returns_none_when_queue_empty(migrated_pg):
    with psycopg.connect(migrated_pg) as conn:
        assert claim_next(conn) is None


@skip_if_no_docker
def test_claim_next_marks_row_running_and_increments_attempts(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "claim@example.com")
        _enqueue(conn, run_id="r", user_id=uid, source="linkedin")

        row = claim_next(conn)
        assert row is not None
        assert row["source"] == "linkedin"
        assert row["attempts"] == 1
        assert row["started_at"] is not None

        # The row is now 'running' in the DB.
        status_row = conn.execute(
            "SELECT status FROM pipe.scrape_jobs WHERE id = %s", (row["id"],)
        ).fetchone()
        assert status_row is not None
        assert status_row[0] == "running"


@skip_if_no_docker
def test_claim_next_serializes_per_source_globally(migrated_pg):
    """The core invariant: two pending rows with the same source serialize
    even when they belong to different users."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        user_a = _new_user(conn, "a@example.com")
        user_b = _new_user(conn, "b@example.com")
        user_c = _new_user(conn, "c@example.com")

        # Enqueue order: linkedin/a, linkedin/b, indeed/c.
        # ORDER BY created_at means linkedin/a claims first.
        _enqueue(conn, run_id="r", user_id=user_a, source="linkedin")
        _enqueue(conn, run_id="r", user_id=user_b, source="linkedin")
        _enqueue(conn, run_id="r", user_id=user_c, source="indeed")

        first = claim_next(conn)
        assert first is not None
        assert first["source"] == "linkedin"
        assert str(first["user_id"]) == user_a

        # linkedin is now 'running'; the next claim must skip linkedin/b and
        # pick indeed/c — different source, free to run.
        second = claim_next(conn)
        assert second is not None
        assert second["source"] == "indeed"
        assert str(second["user_id"]) == user_c

        # Both sources are now in flight; linkedin/b is still gated.
        assert claim_next(conn) is None

        # Finish linkedin/a; linkedin/b should now be claimable.
        conn.execute(
            "UPDATE pipe.scrape_jobs SET status = 'succeeded', finished_at = now() "
            "WHERE id = %s",
            (first["id"],),
        )

        third = claim_next(conn)
        assert third is not None
        assert third["source"] == "linkedin"
        assert str(third["user_id"]) == user_b


@skip_if_no_docker
def test_claim_next_ignores_succeeded_and_failed_rows(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "finished@example.com")
        conn.execute(
            "INSERT INTO pipe.scrape_jobs "
            "(run_id, user_id, source, query_payload, status) "
            "VALUES ('r', %s::uuid, 'linkedin', '{}'::jsonb, 'succeeded')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO pipe.scrape_jobs "
            "(run_id, user_id, source, query_payload, status) "
            "VALUES ('r', %s::uuid, 'indeed', '{}'::jsonb, 'failed')",
            (uid,),
        )
        assert claim_next(conn) is None
