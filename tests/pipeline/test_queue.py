"""Integration tests for ``src/pipeline/queue.py``.

Source-serialization (Phase 13 spec §6: ≤1 in-flight per source globally) is
enforced inside the SQL claim, not in Python. These tests run against a real
Postgres so ``FOR UPDATE SKIP LOCKED`` and the ``source NOT IN (...)`` filter
both exercise their real semantics.
"""

from __future__ import annotations

import psycopg
import pytest

from pipeline.queue import (
    claim_next,
    enqueue,
    mark_failed,
    mark_succeeded,
    pending_count,
    requeue_running,
)

from .conftest import skip_if_no_docker

pytestmark = pytest.mark.docker


def _new_user(conn: psycopg.Connection, email: str) -> str:
    row = conn.execute(
        "INSERT INTO app.users (email) VALUES (%s) RETURNING id::text", (email,)
    ).fetchone()
    assert row is not None
    return row[0]


def _raw_enqueue(
    conn: psycopg.Connection, *, run_id: str, user_id: str, source: str
) -> None:
    """Raw INSERT used in tests that need to bypass the helper itself."""
    conn.execute(
        """
        INSERT INTO pipe.scrape_jobs (run_id, user_id, source, query_payload)
        VALUES (%s, %s::uuid, %s, '{}'::jsonb)
        """,
        (run_id, user_id, source),
    )


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_enqueue_inserts_pending_row(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "enqueue@example.com")
        new_id = enqueue(
            conn,
            run_id="r",
            user_id=uid,
            source="linkedin",
            query_payload={"linkedin": {"searches": [{"keywords": "k"}]}},
        )
        assert new_id is not None

        row = conn.execute(
            "SELECT status, query_payload FROM pipe.scrape_jobs WHERE id = %s",
            (str(new_id),),
        ).fetchone()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] == {"linkedin": {"searches": [{"keywords": "k"}]}}


@skip_if_no_docker
def test_enqueue_idempotent_on_unique_triple(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "idem@example.com")
        first = enqueue(
            conn, run_id="r", user_id=uid, source="linkedin", query_payload={}
        )
        assert first is not None
        # Same (run_id, user_id, source) — UNIQUE → ON CONFLICT DO NOTHING.
        second = enqueue(
            conn,
            run_id="r",
            user_id=uid,
            source="linkedin",
            query_payload={"different": "payload"},
        )
        assert second is None
        # Exactly one row exists.
        count_row = conn.execute(
            "SELECT COUNT(*) FROM pipe.scrape_jobs WHERE run_id = 'r'"
        ).fetchone()
        assert count_row is not None and count_row[0] == 1


# ---------------------------------------------------------------------------
# claim_next
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_claim_next_returns_none_when_queue_empty(migrated_pg):
    with psycopg.connect(migrated_pg) as conn:
        assert claim_next(conn) is None


@skip_if_no_docker
def test_claim_next_marks_row_running_and_increments_attempts(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "claim@example.com")
        _raw_enqueue(conn, run_id="r", user_id=uid, source="linkedin")

        row = claim_next(conn)
        assert row is not None
        assert row["source"] == "linkedin"
        assert row["attempts"] == 1
        assert row["started_at"] is not None

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

        _raw_enqueue(conn, run_id="r", user_id=user_a, source="linkedin")
        _raw_enqueue(conn, run_id="r", user_id=user_b, source="linkedin")
        _raw_enqueue(conn, run_id="r", user_id=user_c, source="indeed")

        first = claim_next(conn)
        assert first is not None and first["source"] == "linkedin"
        assert str(first["user_id"]) == user_a

        second = claim_next(conn)
        assert second is not None and second["source"] == "indeed"
        assert str(second["user_id"]) == user_c

        assert claim_next(conn) is None

        mark_succeeded(conn, job_id=first["id"], posting_count=0)

        third = claim_next(conn)
        assert third is not None and third["source"] == "linkedin"
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


# ---------------------------------------------------------------------------
# mark_succeeded / mark_failed / pending_count
# ---------------------------------------------------------------------------


@skip_if_no_docker
def test_mark_succeeded_stamps_finished_and_count(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "succ@example.com")
        new_id = enqueue(
            conn, run_id="r", user_id=uid, source="linkedin", query_payload={}
        )
        claimed = claim_next(conn)
        assert claimed is not None
        mark_succeeded(conn, job_id=claimed["id"], posting_count=42)

        row = conn.execute(
            "SELECT status, posting_count, finished_at, error "
            "FROM pipe.scrape_jobs WHERE id = %s",
            (str(new_id),),
        ).fetchone()
        assert row is not None
        status, count, finished, err = row
        assert status == "succeeded"
        assert count == 42
        assert finished is not None
        assert err is None


@skip_if_no_docker
def test_mark_failed_captures_error_text(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "fail@example.com")
        new_id = enqueue(
            conn, run_id="r", user_id=uid, source="linkedin", query_payload={}
        )
        claimed = claim_next(conn)
        assert claimed is not None
        mark_failed(
            conn,
            job_id=claimed["id"],
            error="Traceback (most recent call last):\n  ...\nValueError: boom",
        )

        row = conn.execute(
            "SELECT status, error, finished_at FROM pipe.scrape_jobs WHERE id = %s",
            (str(new_id),),
        ).fetchone()
        assert row is not None
        status, err, finished = row
        assert status == "failed"
        assert err is not None and "ValueError: boom" in err
        assert finished is not None


@skip_if_no_docker
def test_requeue_running_resets_in_flight_rows_for_retry(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "requeue@example.com")
        enqueue(conn, run_id="r", user_id=uid, source="linkedin", query_payload={})
        enqueue(conn, run_id="r", user_id=uid, source="jobspy", query_payload={})
        claimed = claim_next(conn)
        assert claimed is not None

        requeued = requeue_running(
            conn,
            run_id="r",
            error="Run overnight-r interrupted by operator: SIGINT; job requeued",
        )

        assert requeued == 1
        row = conn.execute(
            "SELECT status, attempts, error, started_at, finished_at, posting_count "
            "FROM pipe.scrape_jobs WHERE id = %s",
            (claimed["id"],),
        ).fetchone()
        assert row is not None
        status, attempts, err, started, finished, posting_count = row
        assert status == "pending"
        assert attempts == 1
        assert err is not None and "SIGINT" in err
        assert started is None
        assert finished is None
        assert posting_count is None
        assert pending_count(conn, run_id="r") == 2

        retried = claim_next(conn)
        assert retried is not None and retried["id"] == claimed["id"]
        mark_succeeded(conn, job_id=retried["id"], posting_count=7)
        succeeded = conn.execute(
            "SELECT status, error, posting_count FROM pipe.scrape_jobs WHERE id = %s",
            (claimed["id"],),
        ).fetchone()
        assert succeeded == ("succeeded", None, 7)


@skip_if_no_docker
def test_pending_count_excludes_terminal_rows(migrated_pg):
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        uid = _new_user(conn, "count@example.com")
        enqueue(conn, run_id="r", user_id=uid, source="linkedin", query_payload={})
        enqueue(conn, run_id="r", user_id=uid, source="jobspy", query_payload={})
        assert pending_count(conn, run_id="r") == 2

        claimed = claim_next(conn)
        assert claimed is not None
        mark_succeeded(conn, job_id=claimed["id"], posting_count=0)

        # One claimed → succeeded, one still pending.
        assert pending_count(conn, run_id="r") == 1
