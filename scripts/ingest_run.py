#!/usr/bin/env python3
"""Ingest a completed run's per-user scored files into a **local** DB (Phase 15 §5, D1).

The pipeline is produce-only (slice 1): it writes per-user
``data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl`` and never touches
``raw.job_scores``. In the cloud, ingest is the blob → ACA Job path (slice 3).
This is the **local-dev equivalent**: a standalone recipe that walks the same
per-run outputs via :func:`pipeline.scoring.iter_run_user_outputs` and feeds
each file through the existing ``ingest`` CLI into the DB named by
``DATABASE_URL`` (a local dev DB).

Records self-route by their stamped ``user_email`` (slice 2), so no
``--user-email`` is passed — each file ingests to its own user.

This is deliberately separate from the pipeline (D1): the pipeline and ingest
are decoupled, and a developer reaches for this only when they want scores
materialized locally.

Usage (DATABASE_URL from .env — point it at your local DB, not Azure):
    uv run scripts/ingest_run.py --run-id 2026-06-12T1635-overnight
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from pipeline.scoring import iter_run_user_outputs  # noqa: E402

log = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "pipeline_runs"
# Legacy positional still required by the ingest CLI; unused without
# --apply-schema (which this recipe never passes — the local DB is already
# migrated). Goes away with #173 (slice 5).
DEFAULT_SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"

IngestFn = Callable[..., None]
"""``(scored_path=, schema_path=, dry_run=) -> None``."""


def _cli_ingest(*, scored_path: Path, schema_path: Path, dry_run: bool) -> None:
    """Ingest one file through the existing ``ingest`` CLI subcommand.

    ``check=True`` so a failed file raises rather than being silently skipped;
    DATABASE_URL is inherited from the environment (the CLI reads it).
    """
    cmd = [
        "job-scraper-9000",
        "ingest",
        "--input",
        str(scored_path),
        "--schema-path",
        str(schema_path),
    ]
    if dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, check=True)


def ingest_run(
    *,
    run_id: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    dry_run: bool = False,
    ingest_fn: IngestFn = _cli_ingest,
) -> list[Path]:
    """Ingest each of a run's per-user scored files into the local DB.

    Returns the scored paths ingested, in the walk's deterministic order.
    ``ingest_fn`` is injectable so tests run without a DB or a subprocess.
    Raises if the run produced no per-user outputs — an empty ingest is
    almost always an operator error (wrong ``run_id``), not a quiet no-op.
    """
    ingested: list[Path] = []
    for out in iter_run_user_outputs(runs_dir, run_id):
        log.info("Ingesting %s ← %s", out.user_email, out.scored_path)
        ingest_fn(scored_path=out.scored_path, schema_path=schema_path, dry_run=dry_run)
        ingested.append(out.scored_path)

    if not ingested:
        raise SystemExit(
            f"No per-user scored files found for run_id={run_id!r} under "
            f"{runs_dir} — wrong --run-id, or the pipeline produced nothing?"
        )
    log.info("Ingested %d user file(s) for run_id=%r", len(ingested), run_id)
    return ingested


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, dest="run_id")
    parser.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR, type=Path)
    parser.add_argument("--schema-path", default=DEFAULT_SCHEMA_PATH, type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + resolve users but do not write to the DB",
    )
    args = parser.parse_args()

    ingest_run(
        run_id=args.run_id,
        runs_dir=args.runs_dir,
        schema_path=args.schema_path,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
