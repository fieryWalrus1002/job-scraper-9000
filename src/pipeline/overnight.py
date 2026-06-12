"""``job-scraper-9000 overnight`` — Phase 13 orchestrator (spec §8).

Slices 4–5 wire plan + scrape + consolidation + classification. Slices 6–7
extend :func:`run_overnight` with skills_fit, ingest, and the end-of-run
summary. The ``--scrape-only`` flag in the CLI stops after the scrape phase;
the default invocation runs through classification, then fails loudly on the
unimplemented tail.
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
from pipeline.consolidation import (
    ClassifyFn,
    classify_consolidated,
    consolidate_run,
    default_classify_fn,
)
from pipeline.planner import plan_run
from pipeline.worker import ScrapeFn, default_scrape_fn, run_worker

log = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = Path("runs")


def run_overnight(
    *,
    run_date: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    scrape_only: bool = False,
    database_url: str | None = None,
    scrape_fn: ScrapeFn = default_scrape_fn,
    classify_fn: ClassifyFn = default_classify_fn,
) -> dict[str, Any]:
    """Plan + scrape + consolidate + classify. Returns a summary the CLI prints.

    ``scrape_only=True`` stops after the scrape phase. The default invocation
    runs through classification and then raises — skills_fit/ingest are
    slice 6, the end-of-run summary slice 7.

    ``scrape_fn`` / ``classify_fn`` are injectable for tests; production
    callers take the defaults.
    """
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    run_id = f"overnight-{run_date}"
    summary: dict[str, Any] = {"run_id": run_id}

    with psycopg.connect(url, autocommit=True) as conn:
        summary["plan"] = plan_run(conn, run_id=run_id, runs_dir=runs_dir)
        summary["scrape"] = run_worker(conn, runs_dir=runs_dir, scrape_fn=scrape_fn)

        if scrape_only:
            return summary

        summary["consolidation"] = consolidate_run(
            conn, run_id=run_id, runs_dir=runs_dir
        )

    if summary["consolidation"]["postings_consolidated"] == 0:
        # Legitimate for a quiet night (or all scrapes failing — the scrape
        # counters in the summary distinguish the two). run_remote_filter
        # treats an empty input as an error, so don't hand it one.
        log.warning("No postings consolidated — skipping classification phase")
        summary["classification"] = None
    else:
        summary["classification"] = classify_consolidated(
            runs_dir=runs_dir, run_id=run_id, classify_fn=classify_fn
        )

    log.info("Phases through classification complete: %s", summary)
    # Slice 6 (skills_fit + ingest) and slice 7 (end-of-run summary) land
    # here. Failing loudly until then keeps the default invocation honest.
    raise NotImplementedError(
        "Slice 5 ships through classification; skills_fit + ingest land in "
        "slice 6, the end-of-run summary in slice 7. Pass --scrape-only for "
        "the scrape-phase-only run."
    )


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
        help="Stop after plan + scrape (skip consolidation + classification)",
    )
    p.set_defaults(func=_cmd_overnight)


def register(sub: argparse._SubParsersAction) -> None:
    _add_overnight(sub)
