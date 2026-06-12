"""Atomic lease for ``pipe.scrape_jobs`` (Phase 13 spec §5.1, §6).

The worker (slice 4) calls :func:`claim_next` in a loop. Source-serialization
is enforced *inside the SQL*, not in Python: the claim's inner SELECT excludes
any source that already has a ``running`` sibling. That keeps the rule —
"≤1 in-flight per source globally" — in one place where the database can
honor it under concurrency, instead of asking the worker to coordinate.

``FOR UPDATE SKIP LOCKED`` makes the claim safe if the worker ever runs in
more than one process; today it's single-process by design (residential-IP
constraint, see spec §10).
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


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
