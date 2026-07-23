import argparse
import json
import logging
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from job_scraper.pii import pii_redaction_total

log = logging.getLogger(__name__)

DATA_DIR = Path("data/raw")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_run_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid --run-date {value!r}: expected YYYY-MM-DD (e.g. 2026-05-19)"
        )
    return value


def _parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected integer >= 1")
    return parsed


def _auto_path(source: str, keywords: str, run_date: str | None = None) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    if run_date:
        return DATA_DIR / run_date / f"{ts}_{source}_{_slug(keywords)}.jsonl"
    return DATA_DIR / f"{ts}_{source}_{_slug(keywords)}.jsonl"


def _resolve_dest(args, source: str, keywords: str) -> Path | None:
    if args.output:
        return Path(args.output)
    if getattr(args, "save", False):
        path = _auto_path(source, keywords)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def _output(jobs, dest: Path | None) -> None:
    lines = [json.dumps(asdict(j)) for j in jobs]
    if dest:
        with open(dest, "w") as f:
            f.write("\n".join(lines) + "\n")
        log.info("Wrote %d jobs → %s", len(jobs), dest)
    else:
        sys.stdout.write("\n".join(lines) + "\n")


def _summary(jobs) -> None:
    scrubbed = sum(pii_redaction_total(j.scrub_counts) for j in jobs)
    log.info("Total: %d jobs | PII items redacted: %d", len(jobs), scrubbed)


def _add_save_output(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Write JSONL to a specific file (default: stdout)",
    )
    group.add_argument(
        "--save",
        action="store_true",
        help=f"Write JSONL to {DATA_DIR}/YYYY-MM-DD_<source>_<keywords>.jsonl",
    )
