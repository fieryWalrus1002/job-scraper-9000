"""``email-enrich`` — the DB-free, cloud-free enrichment frontend.

Runs on any worker (your workstation, a Proxmox VM, a Pi5): pull + enrich ZR
alert emails and write ``enriched.jsonl``. No database, no LLM, no Azure — feed it
input and rsync the output back to a box that runs ``email-overnight
--enriched-input`` for the paid scoring stages. (It does need a Cloudflare-cleared
Chrome profile to enrich — see the email_scraper README.)
"""

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

from email_scraper.orchestrator import (
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_PROFILE_DIR,
    enrich_email_jobs,
)
from job_scraper.models import JobPosting

log = logging.getLogger(__name__)


def write_enriched(jobs: list[JobPosting], path: Path) -> Path:
    """Write enriched jobs as ``asdict`` JSONL (the seam's transport format)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(asdict(job)) + "\n")
    return path


def _cmd_enrich(args: argparse.Namespace) -> None:
    jobs = enrich_email_jobs(
        pull=not args.no_pull,
        max_emails=args.max_emails,
        max_age_hours=None if args.include_stale else DEFAULT_MAX_AGE_HOURS,
        headless=args.headless,
        profile_dir=args.profile_dir,
        max_files=args.max_files,
        max_jobs=args.max_jobs,
        use_cache=not args.no_cache,
    )
    out = write_enriched(jobs, Path(args.output))
    print(f"enriched {len(jobs)} job(s) → {out}")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "email-enrich",
        help="DB-free: enrich ZR alert emails → enriched.jsonl (for a worker node).",
    )
    p.add_argument(
        "--output",
        "-o",
        default="enriched.jsonl",
        help="Where to write the enriched JSONL (default: enriched.jsonl).",
    )
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
        help="Bypass the Layer-1 processed-email cache.",
    )
    p.set_defaults(func=_cmd_enrich)
