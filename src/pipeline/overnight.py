"""``job-scraper-9000 overnight`` — Phase 13 orchestrator (spec §8).

Slices 4–6 wire plan + scrape + consolidation + classification + the
per-user skills_fit/ingest tail. Slice 7 layers per-user failure isolation
and a polished end-of-run summary on top. The ``--scrape-only`` flag in the
CLI stops after the scrape phase; the default invocation runs the full
pipeline through ingest.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import psycopg

from jobs_cli._common import _parse_run_date
from pipeline.consolidation import (
    ClassifyFn,
    batch_classify_fn,
    classify_consolidated,
    consolidate_run,
    default_classify_fn,
)
from pipeline.planner import plan_run
from pipeline.queue import pending_count, requeue_running
from pipeline.scoring import (
    BATCH_SCORE_FNS,
    BatchScoreFns,
    ScoreFn,
    default_score_fn,
    score_run,
)
from pipeline.summary import build_overnight_summary
from pipeline.worker import ScrapeFn, default_scrape_fn, run_worker

log = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = Path("data/pipeline_runs")
DEFAULT_LOGS_DIR = Path("logs")
_LOG_FILE_HANDLE: TextIO | None = None


def make_run_id(
    run_date: str, started_at: datetime, *, run_type: str = "overnight"
) -> str:
    """Unique, sortable run id: ``<run_date>T<HHMM>-<run_type>`` (e.g.
    ``2026-06-12T1635-overnight``). Folding the wall-clock time into the id
    means a second run on the same date no longer clobbers the first's
    artifacts under ``data/pipeline_runs/<run_id>/``."""
    return f"{run_date}T{started_at:%H%M}-{run_type}"


def run_overnight(
    *,
    run_date: str,
    run_id: str | None = None,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    scrape_only: bool = False,
    database_url: str | None = None,
    scrape_fn: ScrapeFn = default_scrape_fn,
    classify_fn: ClassifyFn = default_classify_fn,
    score_fn: ScoreFn = default_score_fn,
    batch_score_fns: BatchScoreFns | None = None,
) -> dict[str, Any]:
    """Plan + scrape + consolidate + classify + score (produce-only).

    Returns a summary the CLI prints. ``scrape_only=True`` stops after the
    scrape phase. The default invocation runs the full pipeline through
    per-user scoring, emitting per-user scored JSONL files; ingest into
    ``raw.job_scores`` is a separate downstream concern (Phase 15 D1). Every
    return path attaches ``summary["run_summary"]`` — the per-user,
    stderr-ready end-of-run rollup with the all-failed verdict (spec §7).

    ``scrape_fn`` / ``classify_fn`` / ``score_fn`` are injectable for tests;
    production callers take the defaults. ``run_id`` is normally minted by the
    CLI (so the log file and run dir share one timestamp); it defaults to a
    freshly-minted id for direct callers.
    """
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    if run_id is None:
        run_id = make_run_id(run_date, datetime.now())
    summary: dict[str, Any] = {"run_id": run_id}

    with psycopg.connect(url, autocommit=True) as conn:
        summary["plan"] = plan_run(conn, run_id=run_id, runs_dir=runs_dir)
        summary["scrape"] = run_worker(conn, runs_dir=runs_dir, scrape_fn=scrape_fn)

        if scrape_only:
            summary["consolidation"] = None
            summary["classification"] = None
            summary["scoring"] = None
            return _finalize(url, summary)

        summary["consolidation"] = consolidate_run(
            conn, run_id=run_id, runs_dir=runs_dir
        )

    if summary["consolidation"]["postings_consolidated"] == 0:
        # Legitimate for a quiet night (or all scrapes failing — the run
        # summary's per-user verdict distinguishes the two). run_remote_filter
        # treats an empty input as an error, so don't hand it one; nothing
        # to score or ingest either.
        log.warning(
            "No postings consolidated — skipping classification + scoring phases"
        )
        summary["classification"] = None
        summary["scoring"] = None
        return _finalize(url, summary)

    summary["classification"] = classify_consolidated(
        runs_dir=runs_dir, run_id=run_id, classify_fn=classify_fn
    )

    # skills_fit fans back out per user, writing per-user scored JSONL files
    # (produce-only — no job_scores write; Phase 15 D1). A fresh connection:
    # the classification phase ran entirely on disk, and scoring needs the DB
    # only to read each user's requested postings + remote policy.
    with psycopg.connect(url, autocommit=True) as conn:
        summary["scoring"] = score_run(
            conn,
            run_id=run_id,
            run_date=run_date,
            runs_dir=runs_dir,
            score_fn=score_fn,
            batch_score_fns=batch_score_fns,
        )

    return _finalize(url, summary)


def _finalize(url: str, summary: dict[str, Any]) -> dict[str, Any]:
    """Attach the end-of-run summary and log completion. Every return path
    of :func:`run_overnight` funnels through here so the run_summary (and its
    exit verdict) is always present."""
    summary["run_summary"] = build_overnight_summary(
        url,
        run_id=summary["run_id"],
        scrape=summary["scrape"],
        scoring=summary.get("scoring"),
    )
    log.info("Pipeline complete: %s", summary["run_summary"]["text"])
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _OperatorInterrupt(KeyboardInterrupt):
    def __init__(self, signame: str, exit_code: int) -> None:
        super().__init__(f"Interrupted by operator ({signame})")
        self.signame = signame
        self.exit_code = exit_code


class _Tee:
    """Mirror writes to multiple text streams.

    The overnight CLI runs unattended under ``at`` today and likely under a
    cloud scheduler later. Tying the log file to stdout/stderr captures normal
    logging, explicit prints, and uncaught tracebacks without depending on a
    shell wrapper for redirection.
    """

    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    @property
    def encoding(self) -> str | None:
        return self._streams[0].encoding

    def isatty(self) -> bool:
        return self._streams[0].isatty()

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _default_log_file(run_date: str, started_at: datetime) -> Path:
    return DEFAULT_LOGS_DIR / f"overnight_{run_date}_{started_at:%H%M%S}.log"


def _configure_overnight_logging(*, run_date: str, log_file: Path | None) -> None:
    global _LOG_FILE_HANDLE

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE_HANDLE = log_file.open("a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, _LOG_FILE_HANDLE)  # type: ignore[assignment]
        sys.stderr = _Tee(sys.stderr, _LOG_FILE_HANDLE)  # type: ignore[assignment]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
        force=True,
    )
    logging.captureWarnings(True)

    log.info("=== Overnight pipeline started for run_date=%s ===", run_date)
    if log_file is not None:
        log.info("Writing overnight log to %s", log_file)


def _install_interrupt_handlers() -> None:
    def _handler(signum: int, _frame: object) -> None:
        signame = signal.Signals(signum).name
        # Preserve conventional shell exit codes: 128 + signal number.
        raise _OperatorInterrupt(signame, 128 + signum)

    for name in ("SIGINT", "SIGTERM", "SIGTSTP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, _handler)


def _requeue_interrupted_run(*, run_id: str, reason: str) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL not set; cannot requeue interrupted jobs")
        return

    error = f"Run {run_id} interrupted by operator: {reason}; job requeued"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            requeued = requeue_running(conn, run_id=run_id, error=error)
            pending = pending_count(conn, run_id=run_id)
    except Exception:
        log.exception("Failed to requeue interrupted jobs for run_id=%s", run_id)
        return

    log.warning(
        "Run %s interrupted by operator; requeued %d running job(s); "
        "%d pending job(s) remain retryable",
        run_id,
        requeued,
        pending,
    )


def _cmd_overnight(args: argparse.Namespace) -> None:
    # One timestamp for the whole invocation: the log file and the run_id (and
    # thus the run dir) share it, so a run is traceable from log name to artifacts.
    started_at = datetime.now()
    run_id = make_run_id(args.run_date, started_at)

    log_file = None
    if not args.no_log_file:
        log_file = Path(args.log_file or _default_log_file(args.run_date, started_at))
    _configure_overnight_logging(run_date=args.run_date, log_file=log_file)
    _install_interrupt_handlers()

    # --batch swaps both LLM phases onto their OpenAI Batch API twins via the
    # same hooks the tests inject through; the default fns stay untouched.
    llm_fns: dict[str, Any] = {}
    if args.batch:
        log.info("--batch: classification + scoring will use the OpenAI Batch API")
        llm_fns = {"classify_fn": batch_classify_fn, "batch_score_fns": BATCH_SCORE_FNS}

    try:
        summary = run_overnight(
            run_date=args.run_date,
            run_id=run_id,
            runs_dir=Path(args.runs_dir),
            scrape_only=args.scrape_only,
            **llm_fns,
        )
    except _OperatorInterrupt as exc:
        log.warning("Overnight pipeline interrupted by operator (%s)", exc.signame)
        _requeue_interrupted_run(run_id=run_id, reason=exc.signame)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        log.warning("Overnight pipeline interrupted by operator (KeyboardInterrupt)")
        _requeue_interrupted_run(run_id=run_id, reason="KeyboardInterrupt")
        sys.exit(130)
    except BaseException:
        log.exception("Overnight pipeline failed before completion")
        raise

    run_summary = summary["run_summary"]
    # The morning admin reads this block; keep it on stderr, separate from the
    # structured logging stream.
    print(run_summary["text"], file=sys.stderr)
    # Exit non-zero iff *every* user failed (spec §7). Any partial success
    # exits zero — the admin reads the summary and re-runs the idempotent
    # queue for the failed rows.
    if run_summary["all_failed"]:
        log.error("Overnight pipeline finished with all users failed")
        sys.exit(2)
    if run_summary["users_failed"]:
        log.warning("Overnight pipeline finished with per-user failures")
    else:
        log.info("Overnight pipeline finished successfully")


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
        help="Date for this run (run_id becomes 'YYYY-MM-DDT<HHMM>-overnight')",
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
    p.add_argument(
        "--batch",
        action="store_true",
        help=(
            "Run classification + scoring through the OpenAI Batch API "
            "(~50%% cheaper; blocks polling until each batch completes; "
            "requires provider=openai)"
        ),
    )
    log_group = p.add_mutually_exclusive_group()
    log_group.add_argument(
        "--log-file",
        help="Path for the overnight log (default: logs/overnight_<run-date>_<HHMMSS>.log)",
    )
    log_group.add_argument(
        "--no-log-file",
        action="store_true",
        help="Do not write a local log file; log to stderr only",
    )
    p.set_defaults(func=_cmd_overnight)


def register(sub: argparse._SubParsersAction) -> None:
    _add_overnight(sub)
