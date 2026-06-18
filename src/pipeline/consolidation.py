"""Fan-in + classification phase (Phase 13 spec §8 steps 3–4, slice 5).

Two steps that run after the scrape worker drains the queue:

1. :func:`consolidate_run` — read every *succeeded* ``pipe.scrape_jobs``
   row's JSONL, collapse to one posting per dedup key (longest-description
   winner, same rule as :func:`utils.dedup.dedup_jobs`), record which users
   produced each posting, and upsert ``pipe.consolidated_postings``. The
   canonical union is also written to one JSONL on disk — that file is the
   classification input and what ``posting_ref`` points at.
2. :func:`classify_consolidated` — run remote_filter over the union. Live
   calls only (OpenAI Batch is slice 8). Cache hits across users are free:
   the :class:`AnalysisCache` key is profile-independent.

Failed scrape jobs are skipped — the run proceeds for users whose scrapes
succeeded (spec §7). A *succeeded* row whose JSONL is missing is a broken
contract and raises.

``classify_fn`` is injectable to keep tests deterministic, mirroring the
worker's ``scrape_fn``. Production wires in :func:`default_classify_fn`,
which wraps :func:`agents.remote_filter.runner.run_remote_filter`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import psycopg

from pipeline.worker import run_user_dir
from utils.dedup import dedup_jobs

log = logging.getLogger(__name__)

# The shared (all-users) stage of a run, a sibling of the per-user slug dirs
# under <run_id>/. Underscore-prefixed and reserved: it is not a valid email
# slug the planner/worker would ever emit for a user.
CONSOLIDATED_DIRNAME = "_consolidated"

UNION_NAME = "postings.jsonl"
PASS_NAME = "classified_pass.jsonl"
TRASH_NAME = "classified_trash.jsonl"

ClassifyFn = Callable[..., dict[str, Any]]
"""``(input_path=, pass_path=, trash_path=, parent_run_id=) -> summary dict``."""


def consolidated_dir(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id / CONSOLIDATED_DIRNAME


def _posting_key(job: dict[str, Any]) -> str | None:
    """Same key rule as ``dedup_jobs``: ``dedup_hash``, fallback
    ``source_job_id``. The key becomes ``consolidated_postings.dedup_hash``."""
    return job.get("dedup_hash") or job.get("source_job_id") or None


def _attach_search_contexts(
    canonical: list[dict[str, Any]], postings: list[dict[str, Any]]
) -> None:
    """Attach search provenance from all duplicate postings to canonical rows.

    ``dedup_jobs`` keeps a single winner, but remote_filter needs search context
    from every duplicate that collapsed into that winner. For example, a longer
    duplicate without search params should not erase the fact that another copy
    came from a remote-only LinkedIn search.
    """
    contexts_by_key: dict[str, list[dict[str, Any]]] = {}
    seen_by_key: dict[str, set[str]] = {}

    def add_context(key: str, context: dict[str, Any]) -> None:
        cleaned = {k: v for k, v in context.items() if v not in (None, "", [], {})}
        if not cleaned or set(cleaned) == {"source"}:
            return
        marker = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
        seen = seen_by_key.setdefault(key, set())
        if marker in seen:
            return
        seen.add(marker)
        contexts_by_key.setdefault(key, []).append(cleaned)

    # Include canonical rows explicitly so pre-existing provenance on the dedup
    # winner is retained even if callers pass a transformed postings list.
    for job in [*canonical, *postings]:
        key = _posting_key(job)
        if key is None:
            continue
        if search_params := job.get("search_params"):
            add_context(key, {"source": job.get("source"), **search_params})
        for context in job.get("search_contexts") or []:
            add_context(key, context)

    for job in canonical:
        key = _posting_key(job)
        if key is not None and contexts_by_key.get(key):
            job["search_contexts"] = contexts_by_key[key]


def consolidate_run(
    conn: psycopg.Connection,
    *,
    run_id: str,
    runs_dir: Path,
) -> dict[str, Any]:
    """Fan-in: succeeded scrape JSONLs → ``pipe.consolidated_postings``.

    Idempotent: ``requested_by`` is re-derived in full from the succeeded
    rows on every call, so the upsert overwrites rather than merges — a
    re-run after a previously-failed user's retry succeeds picks that user
    up, and a plain re-run is a no-op.

    Postings carrying neither ``dedup_hash`` nor ``source_job_id`` cannot be
    keyed into the table's PK; they are dropped with a warning and counted
    in the summary (``keyless_skipped``).
    """
    rows = conn.execute(
        """
        SELECT u.email, j.user_id::text, j.source
        FROM pipe.scrape_jobs j
        JOIN app.users u ON u.id = j.user_id
        WHERE j.run_id = %s AND j.status = 'succeeded'
        ORDER BY u.email, j.source
        """,
        (run_id,),
    ).fetchall()

    postings: list[dict[str, Any]] = []
    requested_by: dict[str, list[str]] = {}  # dedup key -> ordered unique user_ids
    postings_read = 0
    keyless_skipped = 0

    for email, user_id, source in rows:
        path = run_user_dir(runs_dir, run_id, email) / "scrape" / f"{source}.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"pipe.scrape_jobs row for {email}/{source} (run_id={run_id}) is "
                f"'succeeded' but its scrape JSONL is missing: {path}"
            )
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                job = json.loads(line)
                postings_read += 1
                key = _posting_key(job)
                if key is None:
                    keyless_skipped += 1
                    log.warning(
                        "Posting with neither dedup_hash nor source_job_id in %s "
                        "— cannot consolidate, skipping (title=%r)",
                        path,
                        job.get("title"),
                    )
                    continue
                postings.append(job)
                users = requested_by.setdefault(key, [])
                if user_id not in users:
                    users.append(user_id)

    canonical, duplicates_collapsed = dedup_jobs(postings)
    _attach_search_contexts(canonical, postings)

    out_dir = consolidated_dir(runs_dir, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    union_path = out_dir / UNION_NAME
    with union_path.open("w", encoding="utf-8") as f:
        for job in canonical:
            f.write(json.dumps(job) + "\n")

    for job in canonical:
        key = _posting_key(job)
        assert key is not None  # keyless postings were dropped before dedup
        conn.execute(
            """
            INSERT INTO pipe.consolidated_postings
                (run_id, dedup_hash, requested_by, posting_ref)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (run_id, dedup_hash) DO UPDATE
            SET requested_by = EXCLUDED.requested_by,
                posting_ref = EXCLUDED.posting_ref
            """,
            (run_id, key, [UUID(u) for u in requested_by[key]], str(union_path)),
        )

    summary = {
        "scrape_files_read": len(rows),
        "postings_read": postings_read,
        "postings_consolidated": len(canonical),
        "duplicates_collapsed": duplicates_collapsed,
        "keyless_skipped": keyless_skipped,
        "union_path": str(union_path),
    }
    log.info(
        "Consolidated run_id=%s: %d file(s), %d posting(s) read → %d unique "
        "(%d duplicate(s) collapsed, %d keyless skipped) → %s",
        run_id,
        len(rows),
        postings_read,
        len(canonical),
        duplicates_collapsed,
        keyless_skipped,
        union_path,
    )
    return summary


def default_classify_fn(
    *,
    input_path: Path,
    pass_path: Path,
    trash_path: Path,
    parent_run_id: str,
) -> dict[str, Any]:
    """Production classification: remote_filter over the union, live calls.

    Reuses the existing runner wholesale: shared AnalysisCache, RunTracker
    telemetry, config from ``config/agent/remote_agent.yml``. The runner also
    applies the *global* pass/trash policy split — Phase 13 treats that as
    advisory at this stage, because both output files carry the full
    ``_remote_analysis`` per posting and slice 6 applies each user's own
    ``policies.remote.acceptable_classifications`` over the union of the two.
    """
    from agents.remote_filter.runner import run_remote_filter

    return run_remote_filter(
        input_path=input_path,
        pass_path=pass_path,
        trash_path=trash_path,
        parent_run_id=parent_run_id,
    )


def classify_consolidated(
    *,
    runs_dir: Path,
    run_id: str,
    classify_fn: ClassifyFn = default_classify_fn,
) -> dict[str, Any]:
    """Classification phase: remote_filter against the consolidated union."""
    out_dir = consolidated_dir(runs_dir, run_id)
    summary = classify_fn(
        input_path=out_dir / UNION_NAME,
        pass_path=out_dir / PASS_NAME,
        trash_path=out_dir / TRASH_NAME,
        parent_run_id=run_id,
    )
    log.info("Classification phase done for run_id=%s: %s", run_id, summary)
    return summary
