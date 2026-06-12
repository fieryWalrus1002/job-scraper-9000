"""``job-scraper-9000 overnight`` — Phase 13 orchestrator (spec §8).

Slice 4 wires the scrape phase only. Subsequent slices (5, 6, 7) extend
:func:`run_overnight` with consolidation, classification, skills_fit, ingest,
and the end-of-run summary. The ``--scrape-only`` flag in the CLI keeps
the partial behavior callable while those land.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import psycopg

from jobs_cli._common import _parse_run_date
from pipeline.planner import plan_run
from pipeline.worker import run_worker

log = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = Path("runs")


def run_overnight(
    *,
    run_date: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    scrape_only: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Plan + scrape phase. Returns a small summary the CLI prints.

    ``scrape_only=True`` is the only mode this slice ships. Future slices
    flip on consolidation/classification/skills_fit/ingest gated on the
    same flag's default flipping to False.
    """
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    run_id = f"overnight-{run_date}"

    with psycopg.connect(url, autocommit=True) as conn:
        plan_summary = plan_run(conn, run_id=run_id, runs_dir=runs_dir)
        worker_summary = run_worker(conn, runs_dir=runs_dir)

    if not scrape_only:
        # Slice 5/6/7 will land here. Failing loudly until then keeps the
        # default invocation honest about what's wired.
        raise NotImplementedError(
            "Slice 4 ships --scrape-only only; consolidation + classification "
            "+ skills_fit + ingest land in slices 5–7. Pass --scrape-only."
        )

    return {"run_id": run_id, "plan": plan_summary, "scrape": worker_summary}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_overnight(args: argparse.Namespace) -> None:
    summary = run_overnight(
        run_date=args.run_date,
        runs_dir=Path(args.runs_dir),
        scrape_only=args.scrape_only,
    )
    log.info("Overnight summary: %s", summary)
    # Non-zero exit iff every (user, source) row failed — keeps the at-job
    # exit code honest. Spec §7 talks about partial-success → 0; we apply that
    # here at the scrape phase too.
    scrape = summary["scrape"]
    if scrape["succeeded"] == 0 and scrape["failed"] > 0:
        sys.exit(2)


def _add_overnight(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "overnight",
        help="Phase 13 orchestrator: plan + run the queue-driven pipeline",
    )
    p.add_argument(
        "--run-date",
        required=True,
        dest="run_date",
        metavar="YYYY-MM-DD",
        type=_parse_run_date,
        help="Date label for this run (becomes run_id 'overnight-YYYY-MM-DD')",
    )
    p.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Base dir for per-user run artifacts (default: {DEFAULT_RUNS_DIR})",
    )
    p.add_argument(
        "--scrape-only",
        action="store_true",
        help="Run plan + scrape only (slice-4 scope while later phases land)",
    )
    p.set_defaults(func=_cmd_overnight)


def register(sub: argparse._SubParsersAction) -> None:
    _add_overnight(sub)
