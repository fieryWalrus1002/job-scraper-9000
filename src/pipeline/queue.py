"""Queue helpers for ``pipe.scrape_jobs`` (Phase 13 spec §5).

Five operations on the queue:

- :func:`enqueue` — idempotent ``INSERT`` of one ``(run_id, user_id, source)``
  job. UNIQUE on that triple lets re-running the planner do nothing.
- :func:`claim_next` — atomic lease, with source-serialization enforced in
  the SQL (≤1 in-flight per ``source`` globally, spec §6).
- :func:`mark_succeeded` — terminal: stamp ``finished_at``, record
  ``posting_count``.
- :func:`mark_failed` — terminal: stamp ``finished_at`` + ``error`` (full
  traceback). Per-user failure isolation (§7) leans on this.
- :func:`requeue_running` — interruption cleanup: move this run's in-flight
  rows back to ``pending`` so a manual rerun can resume.
- :func:`pending_count` — read-only diagnostic for the orchestrator
  end-of-phase summary.

All helpers take a sync :class:`psycopg.Connection`. The worker is a single
process by design (residential-IP constraint, spec §10), but
``FOR UPDATE SKIP LOCKED`` in :func:`claim_next` keeps the helpers honest if
that ever changes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json


def enqueue(
    conn: Connection,
    *,
    run_id: str,
    user_id: UUID | str,
    source: str,
    query_payload: dict[str, Any],
) -> UUID | None:
    """Insert one ``(run_id, user_id, source)`` row, status='pending'.

    Idempotent: re-inserting the same triple is a no-op (UNIQUE constraint
    catches it via ``ON CONFLICT DO NOTHING``). Returns the new row's UUID,
    or ``None`` if the row already existed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipe.scrape_jobs (run_id, user_id, source, query_payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (run_id, user_id, source) DO NOTHING
            RETURNING id
            """,
            (run_id, str(user_id), source, Json(query_payload)),
        )
        row = cur.fetchone()
    return row[0] if row else None


def claim_next(conn: Connection) -> dict[str, Any] | None:
    """Atomically claim the next claimable pending job.

    Marks the row ``running``, stamps ``started_at``, increments ``attempts``,
    and returns it. ``source`` serialization is enforced in the inner SELECT —
    if every pending row's source already has a ``running`` sibling, returns
    ``None`` even though pending rows exist.

    Returns ``None`` when there is nothing claimable right now. The caller's
    loop is responsible for deciding whether that means "done" (no pending
    rows at all) or "waiting on a sibling to finish".
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE pipe.scrape_jobs
            SET status = 'running',
                started_at = now(),
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM pipe.scrape_jobs
                WHERE status = 'pending'
                  AND source NOT IN (
                      SELECT source FROM pipe.scrape_jobs WHERE status = 'running'
                  )
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, run_id, user_id, source, query_payload,
                      attempts, started_at, created_at
            """
        )
        return cur.fetchone()


def mark_succeeded(conn: Connection, *, job_id: UUID | str, posting_count: int) -> None:
    """Move a ``running`` job to ``succeeded``; stamp ``finished_at`` and
    ``posting_count``. Caller's responsibility to only call on rows it
    claimed."""
    conn.execute(
        """
        UPDATE pipe.scrape_jobs
        SET status = 'succeeded',
            finished_at = now(),
            posting_count = %s,
            error = NULL
        WHERE id = %s
        """,
        (posting_count, str(job_id)),
    )


def mark_failed(conn: Connection, *, job_id: UUID | str, error: str) -> None:
    """Move a ``running`` job to ``failed``; stamp ``finished_at`` and capture
    the full ``error`` (per CLAUDE.md, prefer the full traceback so the
    end-of-run summary has something to diagnose with)."""
    conn.execute(
        """
        UPDATE pipe.scrape_jobs
        SET status = 'failed',
            finished_at = now(),
            error = %s
        WHERE id = %s
        """,
        (error, str(job_id)),
    )


def requeue_running(conn: Connection, *, run_id: str, error: str) -> int:
    """Move this run's ``running`` rows back to ``pending`` after interruption.

    Operator aborts during local debugging should not leave permanent source
    blockers behind, and they should be retryable with the same ``run_id``.
    ``attempts`` is intentionally preserved: the row was claimed and tried,
    even though it did not reach a terminal state.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipe.scrape_jobs
            SET status = 'pending',
                started_at = NULL,
                finished_at = NULL,
                posting_count = NULL,
                error = %s
            WHERE run_id = %s
              AND status = 'running'
            """,
            (error, run_id),
        )
        return cur.rowcount


def pending_count(conn: Connection, *, run_id: str) -> int:
    """How many ``pending`` rows remain in this run. Used by the orchestrator
    to assert all work was claimed before advancing to consolidation."""
    row = conn.execute(
        "SELECT COUNT(*) FROM pipe.scrape_jobs "
        "WHERE run_id = %s AND status = 'pending'",
        (run_id,),
    ).fetchone()
    return int(row[0]) if row else 0
