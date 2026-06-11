"""Starter-set seeding (specs/multi_user_design.md §5).

A newly invited member sees an empty feed until the admin runs their first
overnight pipeline. To bridge that, each member is seeded once with per-user
score rows pointing at the shared ``example-`` postings (migration 0008), which
makes those postings visible in their feed.

Seeding is "once per member, only if their feed is empty":

- Gated on ``app.users.starter_seeded_at`` — once set, the check never runs
  again, so there is no permanent per-request cost. The column rides the
  existing per-request user lookup, so detecting "already handled" adds no query.
- Only members are seeded; the admin already has a real feed.
- Skipped (but still marked) for a member who already has scores — covers the
  case where the admin ran their pipeline before they first logged in.

The example postings stay shared; visibility is per-user via these score rows
(``run_id = 'example-set'``), so they remain bulk-removable per user
(``DELETE FROM raw.job_scores WHERE user_id = X AND run_id = 'example-set'``)
and excludable from real stats.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

STARTER_RUN_ID = "example-set"


async def seed_starter_set(conn, user_id) -> None:
    """Make the shared example postings visible to one user.

    Inserts a per-user score row for every ``example-`` posting. Neutral
    fit_score and ``example`` provenance mark them as non-real so they can be
    filtered out of any stats. Idempotent via the score PK.
    """
    await conn.execute(
        """
        INSERT INTO raw.job_scores
            (user_id, dedup_hash, fit_score, score_rationale,
             run_id, scored_at, model, provider, profile_version)
        SELECT %(user_id)s, dedup_hash, 3,
               'Example job, shown until your first real pipeline run.',
               %(run_id)s, now(), 'example', 'example', 'example'
        FROM raw.job_postings
        WHERE dedup_hash LIKE 'example-%%'
        ON CONFLICT (user_id, dedup_hash) DO NOTHING
        """,
        {"user_id": user_id, "run_id": STARTER_RUN_ID},
    )


async def ensure_starter_set(conn, user: dict[str, Any]) -> None:
    """Seed the starter set once for a member with an empty feed.

    Called from the CurrentUser dependency after the user row is resolved.
    No-ops for non-members and for anyone already marked. Mutates ``user``'s
    ``starter_seeded_at`` so the resolved row stays consistent.
    """
    if user.get("role") != "member" or user.get("starter_seeded_at") is not None:
        return

    cur = await conn.execute(
        "SELECT 1 FROM raw.job_scores WHERE user_id = %(user_id)s LIMIT 1",
        {"user_id": user["id"]},
    )
    has_scores = await cur.fetchone() is not None

    if not has_scores:
        await seed_starter_set(conn, user["id"])
        log.info("Seeded starter set for member %s", user["id"])

    # Mark handled either way so this never re-runs for the user.
    cur = await conn.execute(
        "UPDATE app.users SET starter_seeded_at = now() WHERE id = %(user_id)s "
        "RETURNING starter_seeded_at",
        {"user_id": user["id"]},
    )
    row = await cur.fetchone()
    if row is not None:
        user["starter_seeded_at"] = row["starter_seeded_at"]
