#!/usr/bin/env python3
"""
Upload a batch request file to OpenAI, poll until complete, and download results.

Reads from and writes to the run directory (default: data/batch/YYYY-MM-DD/).

Workflow:
    prepare_batch.py → submit_batch.py → merge_batch_results.py

Usage:
    python scripts/submit_batch.py                               # upload + wait
    python scripts/submit_batch.py --batch-id batch_abc123      # resume polling
    python scripts/submit_batch.py --no-wait                     # upload only, print ID
    python scripts/submit_batch.py --run-dir data/batch/2026-05-11  # cross-day resume
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from utils import batch_api

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_RUN_DIR = f"data/batch/{date.today().isoformat()}"
POLL_INTERVAL = 60  # seconds


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--run-dir",
        default=DEFAULT_RUN_DIR,
        help=f"Batch run directory (default: {DEFAULT_RUN_DIR})",
    )
    p.add_argument(
        "--batch-id", help="Skip upload and resume polling an existing batch ID"
    )
    p.add_argument(
        "--no-wait",
        action="store_true",
        help="Upload only — print batch ID and exit without polling",
    )
    p.add_argument(
        "--poll-interval",
        type=int,
        default=POLL_INTERVAL,
        help=f"Seconds between status checks (default: {POLL_INTERVAL})",
    )
    return p.parse_args()


def upload_batch(client: OpenAI, batch_path: Path, batch_id_path: Path) -> str:
    batch_id, _ = batch_api.upload_and_create_batch(client, batch_path)
    batch_id_path.write_text(batch_id)
    log.info("Batch ID saved to %s", batch_id_path)
    return batch_id


def download_results(client: OpenAI, batch, results_path: Path) -> None:
    try:
        content = batch_api.download_results(client, batch)
    except RuntimeError as exc:
        log.error("%s — no results to download", exc)
        if batch.error_file_id:
            errors = client.files.content(batch.error_file_id).text
            log.error("Errors:\n%s", errors[:2000])
        sys.exit(1)

    log.info("Downloading results (file_id=%s) ...", batch.output_file_id)
    results_path.write_text(content)
    log.info("Results written to %s", results_path)

    counts = batch.request_counts
    log.info(
        "Final counts: %d completed | %d failed | %d total",
        counts.completed,
        counts.failed,
        counts.total,
    )
    if counts.failed:
        log.warning(
            "%d requests failed — merge_batch_results.py will skip those records",
            counts.failed,
        )


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.error("OPENAI_API_KEY not set")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    batch_path = run_dir / "gpt_teacher_batch.jsonl"
    results_path = run_dir / "gpt_teacher_results.jsonl"
    batch_id_path = run_dir / "last_batch_id.txt"

    if args.batch_id:
        batch_id = args.batch_id
        log.info("Resuming existing batch: %s", batch_id)
    else:
        if not batch_path.exists():
            log.error(
                "Batch file not found: %s  (run prepare_batch.py first)", batch_path
            )
            sys.exit(1)
        batch_id = upload_batch(client, batch_path, batch_id_path)

    if args.no_wait:
        print(f"\nBatch ID: {batch_id}")
        print(
            f"Resume with: uv run python scripts/submit_batch.py --run-dir {run_dir} --batch-id {batch_id}"
        )
        return

    batch = batch_api.poll_until_done(client, batch_id, args.poll_interval)
    download_results(client, batch, results_path)

    print(
        f"\nNext step: uv run python scripts/merge_batch_results.py --run-dir {run_dir}"
    )


if __name__ == "__main__":
    main()
