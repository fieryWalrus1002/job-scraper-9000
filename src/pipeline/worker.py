"""Queue-driven scrape worker (Phase 13 spec §8 step 2).

Loop forever (or until cancelled):

1. ``claim_next`` — atomic lease (source-serialization in SQL).
2. Invoke the per-source scrape via ``scrape_fn``.
3. Apply the user's policies.prefilter inline — currently just
   ``excluded_title_terms`` (cheap title substring drop). Spec §11.4.
4. Write surviving postings to ``runs/<slug>/<run_id>/scrape/<source>.jsonl``.
5. ``mark_succeeded`` with the count, or on any exception ``mark_failed``
   with the full traceback (per-user failure isolation, §7).

Single-process, single-threaded by design. Concurrency between sources
already comes from the source-serialization claim: pending rows for
different sources can be claimed by separate calls without the worker
having to schedule them. (Slice 7 may move to an async loop with multiple
in-flight non-conflicting jobs; this slice keeps it dumb.)

``scrape_fn`` is injectable to keep tests deterministic. Production wires
in :func:`default_scrape_fn` which writes the per-source payload to a
temporary YAML, invokes ``job_scraper.config.load_config`` on it, and runs
the resulting scrapers.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import traceback
from pathlib import Path
from typing import Any, Callable, Iterable

import psycopg
import yaml

from pipeline.queue import claim_next, mark_failed, mark_succeeded
from user_config import UserPolicies

log = logging.getLogger(__name__)

ScrapeFn = Callable[[str, dict[str, Any]], Iterable[Any]]
"""``(source, query_payload) -> iterable of scraped postings`` (either
dataclass instances or already-dict). The worker calls ``asdict`` on any
dataclass, then JSON-serializes; non-dataclass dict inputs pass through."""


# ---------------------------------------------------------------------------
# Default (production) scrape_fn
# ---------------------------------------------------------------------------


def default_scrape_fn(source: str, query_payload: dict[str, Any]) -> list[Any]:
    """Real scrape: write payload to a temp YAML, load_config, run scrapers.

    ``query_payload`` is the per-source slice the planner stored
    (``{source: <section>, "global": {...}}``). The temp YAML lives only for
    the duration of the call.
    """
    from job_scraper.config import load_config

    tmp_yaml = Path(f".pipeline-scrape-input-{source}.yml")
    tmp_yaml.write_text(yaml.safe_dump(query_payload, sort_keys=False))
    try:
        scrapers = load_config(tmp_yaml)
    finally:
        try:
            tmp_yaml.unlink()
        except FileNotFoundError:
            pass

    jobs: list[Any] = []
    for s in scrapers:
        # Per-scraper exceptions bubble up — the worker catches them at the
        # job boundary and marks the whole (user, source) job failed. That's
        # blunter than the single-user CLI (which records permanent skips
        # per-scraper), but Phase 13's per-user retry surface is "re-run the
        # queue", not partial-source resumption (spec §7).
        jobs.extend(s.scrape())
    return jobs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(email: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "_", email.strip().lower()).replace(".", "_")


def run_user_dir(runs_dir: Path, run_id: str, email: str) -> Path:
    """Per-user artifact dir for a run, partitioned **run-first**:
    ``<runs_dir>/<run_id>/<slug>``. Run-first co-locates every user (and the
    shared ``_consolidated/`` stage) under one run dir, so a whole run is one
    subtree to upload, ingest, or drop. Canonical home for the layout so the
    planner, worker, consolidation, and scoring agree on one definition."""
    return runs_dir / run_id / _slug(email)


def _to_dict(job: Any) -> dict[str, Any]:
    """Normalize a scraped posting to a plain dict for serialization."""
    if dataclasses.is_dataclass(job) and not isinstance(job, type):
        return dataclasses.asdict(job)
    if isinstance(job, dict):
        return job
    raise TypeError(
        f"scrape_fn produced an unsupported posting type: {type(job).__name__}; "
        "expected dataclass instance or dict"
    )


def _apply_title_filter(
    jobs: list[dict[str, Any]], excluded_terms: list[str]
) -> list[dict[str, Any]]:
    """Drop postings whose title contains any of ``excluded_terms`` (case-
    insensitive substring match). Empty list of terms = no-op."""
    if not excluded_terms:
        return jobs
    lowered = [t.strip().lower() for t in excluded_terms if t.strip()]
    if not lowered:
        return jobs

    def _keep(job: dict[str, Any]) -> bool:
        title = (job.get("title") or "").lower()
        return not any(term in title for term in lowered)

    return [j for j in jobs if _keep(j)]


def _load_policies(run_dir: Path) -> UserPolicies:
    """Read ``policies.yml`` for the run, validated through UserPolicies.

    Missing file means the planner skipped writing policies (defensive — the
    planner always writes it, even if empty), which we treat as permissive.
    """
    policies_path = run_dir / "policies.yml"
    if not policies_path.exists():
        return UserPolicies()
    payload = yaml.safe_load(policies_path.read_text()) or {}
    return UserPolicies.model_validate(payload)


def _resolve_user_email(conn: psycopg.Connection, user_id: Any) -> str:
    row = conn.execute(
        "SELECT email FROM app.users WHERE id = %s", (str(user_id),)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"app.users row missing for id={user_id}")
    return row[0]


def _persist(jobs: list[dict[str, Any]], dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job) + "\n")
    return len(jobs)


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


def process_job(
    conn: psycopg.Connection,
    job: dict[str, Any],
    *,
    runs_dir: Path,
    scrape_fn: ScrapeFn,
) -> int:
    """Run one claimed job end-to-end. Returns the post-policy posting count.

    Exceptions inside this function bubble up — :func:`run_worker` catches
    them at the boundary and stamps ``mark_failed``."""
    email = _resolve_user_email(conn, job["user_id"])
    run_dir = run_user_dir(runs_dir, job["run_id"], email)
    policies = _load_policies(run_dir)

    raw_jobs = list(scrape_fn(job["source"], job["query_payload"]))
    job_dicts = [_to_dict(j) for j in raw_jobs]
    filtered = _apply_title_filter(job_dicts, policies.prefilter.excluded_title_terms)

    dest = run_dir / "scrape" / f"{job['source']}.jsonl"
    count = _persist(filtered, dest)
    log.info(
        "%s/%s — scraped %d, kept %d after title filter → %s",
        email,
        job["source"],
        len(job_dicts),
        count,
        dest,
    )
    return count


def run_worker(
    conn: psycopg.Connection,
    *,
    runs_dir: Path,
    scrape_fn: ScrapeFn = default_scrape_fn,
) -> dict[str, int]:
    """Claim-and-process loop. Returns ``{"succeeded": N, "failed": M}``.

    Loops until :func:`claim_next` returns ``None``. With single-process
    workers and source-serialization, that signals either "no pending rows"
    or "all pending rows blocked by a running sibling" — in single-process
    mode the second can't happen because the only running rows we'd be
    blocked by are ones we already finished. So None == done.

    Per CLAUDE.md ("fail fast, but log well"): the per-job try/except
    captures ``traceback.format_exc()`` into ``pipe.scrape_jobs.error`` and
    moves on. The exception is also logged so it surfaces in stderr right
    away, not just at end-of-run.
    """
    counters = {"succeeded": 0, "failed": 0}
    while True:
        job = claim_next(conn)
        if job is None:
            break
        try:
            count = process_job(conn, job, runs_dir=runs_dir, scrape_fn=scrape_fn)
            mark_succeeded(conn, job_id=job["id"], posting_count=count)
            counters["succeeded"] += 1
        except Exception:
            tb = traceback.format_exc()
            log.error(
                "Job %s (%s/%s) failed:\n%s",
                job["id"],
                job["user_id"],
                job["source"],
                tb,
            )
            mark_failed(conn, job_id=job["id"], error=tb)
            counters["failed"] += 1

    log.info(
        "Worker done: succeeded=%d failed=%d",
        counters["succeeded"],
        counters["failed"],
    )
    return counters
