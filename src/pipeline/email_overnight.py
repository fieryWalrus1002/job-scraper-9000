"""``job-scraper-9000 email-overnight`` — email jobs → the same blob/ingest path.

A *separate* pipeline that lands ZipRecruiter email jobs in the exact place
``run-overnight`` does: per-user
``data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl``, ready for
``just upload-blob <run-id>`` → KEDA → ingest → app.

It reuses the overnight stages verbatim (``consolidate_run`` →
``classify_consolidated`` → ``score_run``) but swaps the source: instead of the
queue-driven multi-user live scrape, it enriches one user's email alerts (local,
Chrome-profile) and feeds them in as a single synthetic ``ziprecruiter_email``
scrape result. It writes the scrape stage + marks the job succeeded **directly**
(no ``claim_next``, which isn't run_id-scoped), so it never disturbs an overnight
run. The run_id carries a dedicated ``-email`` suffix.

This driver is local-only (it runs the Chrome-profile enrichment); it talks to
the same DB ``run-overnight`` uses for the user's profile / policy / run state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from email_scraper.orchestrator import (
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_PROFILE_DIR,
    enrich_email_jobs,
)
from job_scraper.models import JobPosting
from jobs_cli._common import _parse_run_date
from pipeline.consolidation import (
    classify_consolidated,
    consolidate_run,
)
from pipeline.overnight import DEFAULT_RUNS_DIR, make_run_id
from pipeline.planner import _SELECT_USERS, _materialize_user
from pipeline.queue import enqueue, mark_succeeded
from pipeline.scoring import score_run, skills_fit_dir
from pipeline.worker import _persist, _to_dict, run_user_dir

log = logging.getLogger(__name__)

# Synthetic queue source for email jobs. Nothing validates source names, and a
# normal overnight never enqueues this, so the two pipelines stay disjoint.
EMAIL_SOURCE = "ziprecruiter_email"


def _load_user(conn: psycopg.Connection, user_email: str) -> dict[str, Any]:
    """Load one provisioned user, failing fast with the same guards as the planner."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SELECT_USERS)
        rows = cur.fetchall()
    by_email = {row["email"]: row for row in rows}
    row = by_email.get(user_email)
    if row is None:
        raise SystemExit(
            f"No app.users row for {user_email!r}. Known: {sorted(by_email)}"
        )
    if row["profile_payload"] is None or row["search_payload"] is None:
        raise SystemExit(
            f"{user_email} is missing a candidate profile and/or search config; "
            "provision it (same precondition as run-overnight)."
        )
    if row["pipeline_enabled"] is False:
        raise SystemExit(f"{user_email} has pipeline_enabled=false; nothing to run.")
    return row


def _prepare_user(
    conn: psycopg.Connection, *, runs_dir: Path, run_id: str, user_email: str
) -> tuple[str, Path]:
    """Load the user and materialize their run dir (profile/search/policies)."""
    user = _load_user(conn, user_email)
    run_dir = run_user_dir(runs_dir, run_id, user_email)
    _materialize_user(
        run_dir=run_dir,
        profile_payload=user["profile_payload"],
        profile_version=user["profile_version"],
        search_payload=user["search_payload"],
        policies=user["policies"],
    )
    return user["user_id"], run_dir


# Injectable seams so the composition is testable without a DB / LLM / browser.
PrepareUserFn = Callable[..., tuple[str, Path]]
EnrichFn = Callable[..., list]
StageFn = Callable[..., Any]


def run_email_pipeline(
    *,
    run_date: str,
    user_email: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    database_url: str | None = None,
    run_id: str | None = None,
    conn: psycopg.Connection | None = None,
    enriched_input: Path | None = None,
    enrich_fn: EnrichFn = enrich_email_jobs,
    prepare_user_fn: PrepareUserFn = _prepare_user,
    consolidate_fn: StageFn = consolidate_run,
    classify_fn: StageFn = classify_consolidated,
    score_fn: StageFn = score_run,
    **enrich_kwargs: Any,
) -> dict[str, Any]:
    """Enrich one user's email alerts and run them through the overnight stages.

    When ``enriched_input`` is set, load a pre-built ``enriched.jsonl`` (from a
    detached ``email-enrich`` worker) instead of enriching inline — the score
    half of the seam. Returns a summary dict. ``conn`` is injectable (tests pass
    a fake); when None a connection is opened from ``database_url`` / ``$DATABASE_URL``.
    """
    if run_id is None:
        run_id = make_run_id(run_date, datetime.now(), run_type="email")

    common = dict(
        run_date=run_date,
        user_email=user_email,
        runs_dir=runs_dir,
        run_id=run_id,
        enriched_input=enriched_input,
        enrich_fn=enrich_fn,
        prepare_user_fn=prepare_user_fn,
        consolidate_fn=consolidate_fn,
        classify_fn=classify_fn,
        score_fn=score_fn,
        **enrich_kwargs,
    )
    if conn is not None:
        return _run(conn, **common)

    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    with psycopg.connect(url, autocommit=True) as opened:
        return _run(opened, **common)


def _load_enriched(path: Path) -> list[JobPosting]:
    """Load an ``enriched.jsonl`` (from a detached ``email-enrich`` worker)."""
    jobs: list[JobPosting] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            jobs.append(JobPosting(**json.loads(line)))
    return jobs


def _run(
    conn: psycopg.Connection,
    *,
    run_date: str,
    user_email: str,
    runs_dir: Path,
    run_id: str,
    enriched_input: Path | None,
    enrich_fn: EnrichFn,
    prepare_user_fn: PrepareUserFn,
    consolidate_fn: StageFn,
    classify_fn: StageFn,
    score_fn: StageFn,
    **enrich_kwargs: Any,
) -> dict[str, Any]:
    log.info("=== email-overnight run_id=%s user=%s ===", run_id, user_email)

    # Fail fast on an unprovisioned user *before* the slow Chrome enrichment.
    user_id, run_dir = prepare_user_fn(
        conn, runs_dir=runs_dir, run_id=run_id, user_email=user_email
    )

    if enriched_input is not None:
        jobs = _load_enriched(enriched_input)
        log.info("Loaded %d enriched job(s) from %s", len(jobs), enriched_input)
    else:
        jobs = enrich_fn(**enrich_kwargs)
    if not jobs:
        log.warning("No enriched email jobs — nothing to consolidate or score.")
        return {"run_id": run_id, "enriched": 0, "scored_path": None}

    # Write the enriched jobs as this run's scrape stage, in the worker's own
    # format, then record the job as succeeded so consolidation fans it in.
    dest = run_dir / "scrape" / f"{EMAIL_SOURCE}.jsonl"
    _persist([_to_dict(j) for j in jobs], dest)
    log.info("Wrote %d enriched job(s) → %s", len(jobs), dest)

    job_id = enqueue(
        conn, run_id=run_id, user_id=user_id, source=EMAIL_SOURCE, query_payload={}
    )
    if job_id is None:
        raise RuntimeError(
            f"scrape_jobs row for {user_email}/{EMAIL_SOURCE} (run_id={run_id}) "
            "already exists — is this run_id being reused?"
        )
    mark_succeeded(conn, job_id=job_id, posting_count=len(jobs))

    consolidate_fn(conn, run_id=run_id, runs_dir=runs_dir)
    classify_fn(runs_dir=runs_dir, run_id=run_id)
    score_fn(conn, run_id=run_id, run_date=run_date, runs_dir=runs_dir)

    scored_path = skills_fit_dir(runs_dir, user_email, run_id) / "scored.jsonl"
    log.info(
        "email-overnight done: run_id=%s → %s\nNext: just upload-blob %s",
        run_id,
        scored_path,
        run_id,
    )
    return {"run_id": run_id, "enriched": len(jobs), "scored_path": str(scored_path)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_email(args: argparse.Namespace) -> None:
    summary = run_email_pipeline(
        run_date=args.run_date,
        user_email=args.user_email,
        runs_dir=Path(args.runs_dir),
        enriched_input=Path(args.enriched_input) if args.enriched_input else None,
        pull=not args.no_pull,
        max_emails=args.max_emails,
        headless=args.headless,
        profile_dir=args.profile_dir,
        max_age_hours=None if args.include_stale else DEFAULT_MAX_AGE_HOURS,
        max_files=args.max_files,
        max_jobs=args.max_jobs,
        use_cache=not args.no_cache,
    )
    if summary["scored_path"]:
        print(f"run_id: {summary['run_id']}  (enriched {summary['enriched']} job(s))")
        print(f"scored: {summary['scored_path']}")
        print(f"upload: just upload-blob {summary['run_id']}")
    else:
        print(f"run_id: {summary['run_id']} — no enriched jobs; nothing produced.")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "email-overnight",
        help="Enrich email alerts and run them through the overnight stages (→ blob).",
    )
    p.add_argument(
        "--run-date",
        dest="run_date",
        default=datetime.now().strftime("%Y-%m-%d"),
        metavar="YYYY-MM-DD",
        type=_parse_run_date,
        help="Date for this run (run_id becomes 'YYYY-MM-DDT<HHMM>-email').",
    )
    p.add_argument(
        "--enriched-input",
        default=None,
        help="Score a pre-built enriched.jsonl from an email-enrich worker "
        "(skips local enrichment; the score half of the seam).",
    )
    p.add_argument(
        "--user-email",
        required=True,
        help="The provisioned user this email run scores for.",
    )
    p.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Base dir for per-user run artifacts (default: {DEFAULT_RUNS_DIR}).",
    )
    # Enrichment passthrough (mirrors orchestrator.py).
    p.add_argument("--no-pull", action="store_true", help="Skip the Gmail download.")
    p.add_argument(
        "--max-emails", type=int, default=None, help="Download at most N newest emails."
    )
    p.add_argument(
        "--include-stale",
        action="store_true",
        help="Process all emails regardless of age (default skips >96h old).",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run headless without the Chrome profile (ZR /km/ will hit Cloudflare).",
    )
    p.add_argument(
        "--profile-dir",
        default=DEFAULT_PROFILE_DIR,
        help="Chrome user-data-dir for the Cloudflare piggyback (Chrome must be closed).",
    )
    p.add_argument("--max-files", type=int, default=None, help="Only newest N emails.")
    p.add_argument(
        "--max-jobs", type=int, default=None, help="Stop after N enriched jobs."
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the Layer-1 processed-email cache (reprocess/retry a run).",
    )
    p.set_defaults(func=_cmd_email)
