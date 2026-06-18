"""Local-only orchestrator: pull → enrich → pipeline pile.

One command that turns ZipRecruiter alert emails into a `data/raw/` JSONL the
rest of the pipeline already knows how to read:

  1. Pull the newest labeled emails from Gmail (unless --no-pull).
  2. Parse + enrich them, defaulting to the real Chrome profile so live ZR /km/
     links actually get past Cloudflare (see zr_scraper). Headful by default.
  3. Keep only the *enriched* jobs (those with a real description) and write them
     to data/raw/[run_date/] exactly like every other scraper.

Freshness is load-bearing: ZR's /km/ enrichment tokens expire 96h after the
email is sent, so by default we skip emails older than that — there's nothing
left to scrape on them.

This module is personal, local-only tooling (it reads a personal inbox) and is
never part of the cloud pipeline.

Run:
    uv run python src/email_scraper/orchestrator.py
    uv run python src/email_scraper/orchestrator.py --no-pull --run-date 2026-06-18
"""

import argparse
import logging
import os
import subprocess
from collections import Counter
from datetime import datetime

from email_scraper.gmail_eml_grabber import LABEL_QUERY, MAX_EMAILS, OUTPUT_DIR
from email_scraper.pile import write_pile
from email_scraper.process_eml_directory import (
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_DIRECTORY,
    process_eml_directory,
)
from email_scraper.seen_store import default_processed_store
from email_scraper.zr_scraper import ENRICHED, _HEADLESS_ENV, _PROFILE_DIR_ENV
from job_scraper.models import JobPosting

log = logging.getLogger(__name__)

# ZR /km/ enrichment links expire 96h after send; past that an email yields no
# enrichable jobs, so it's not worth a browser launch.
DEFAULT_MAX_AGE_HOURS = 96.0
DEFAULT_PROFILE_DIR = "~/.config/google-chrome"


def _chrome_is_running() -> bool:
    """True if a Chrome process holds the profile (its lock would crash launch)."""
    try:
        return subprocess.run(["pgrep", "-x", "chrome"]).returncode == 0
    except FileNotFoundError:
        # No pgrep (non-Linux/dev box): can't check, so don't block the run.
        return False


def enrich_email_jobs(
    *,
    pull: bool = True,
    max_emails: int | None = MAX_EMAILS,
    directory_path: str = DEFAULT_DIRECTORY,
    archive_dir_path: str = DEFAULT_ARCHIVE_DIR,
    max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
    archive_processed: bool = False,
    headless: bool = False,
    profile_dir: str = DEFAULT_PROFILE_DIR,
    max_files: int | None = None,
    max_jobs: int | None = None,
    use_cache: bool = True,
) -> list[JobPosting]:
    """Pull + enrich emails and return only the **enriched** jobs.

    The shared core of both handoffs: the ``data/raw`` pile (:func:`run`) and the
    Azure pipeline (:mod:`pipeline.email_overnight`). Does everything except
    decide where the jobs go.
    """
    # 1. Pull newest labeled emails.
    if pull:
        log.info("Pulling newest emails (max=%s) into %s", max_emails, OUTPUT_DIR)
        from email_scraper.gmail_eml_grabber import download_labeled_emails_as_eml

        download_labeled_emails_as_eml(LABEL_QUERY, OUTPUT_DIR, max_emails)

    # 2. Enrichment mode. The whole point of this local tool is to beat Cloudflare
    # with a real session, so default to the profile (headful). Fail fast if
    # Chrome holds the profile lock — a confusing mid-run crash otherwise.
    if not headless:
        expanded = os.path.expanduser(profile_dir)
        if _chrome_is_running():
            raise RuntimeError(
                "Chrome is running and would lock the profile. Close Chrome, or "
                "run with --headless (no descriptions for ZR /km/), or point "
                "--profile-dir at a copy."
            )
        os.environ[_PROFILE_DIR_ENV] = expanded
        os.environ[_HEADLESS_ENV] = "0"
        log.info("Enriching via Chrome profile %s (headful)", expanded)
    else:
        os.environ.pop(_PROFILE_DIR_ENV, None)
        log.info("Enriching headless (no profile) — ZR /km/ will hit Cloudflare")

    # 3. Parse + enrich, skipping aged-out emails and ones already processed.
    jobs = process_eml_directory(
        directory_path=directory_path,
        archive_dir_path=archive_dir_path,
        scrape_details=True,
        archive_processed=archive_processed,
        max_age_hours=max_age_hours,
        max_files=max_files,
        max_jobs=max_jobs,
        seen_store=default_processed_store() if use_cache else None,
    )

    # 4. Summarize outcomes, then keep only jobs that actually got a description.
    histogram = Counter(j.enrichment_status for j in jobs)
    log.info(
        "Enrichment outcomes: %s",
        ", ".join(
            f"{k}={v}" for k, v in sorted(histogram.items(), key=lambda x: str(x[0]))
        ),
    )
    enriched = [j for j in jobs if j.enrichment_status == ENRICHED]
    log.info("Enriched %d/%d jobs.", len(enriched), len(jobs))
    return enriched


def run(
    *,
    pull: bool = True,
    max_emails: int | None = MAX_EMAILS,
    directory_path: str = DEFAULT_DIRECTORY,
    archive_dir_path: str = DEFAULT_ARCHIVE_DIR,
    run_date: str | None = None,
    max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
    archive_processed: bool = False,
    headless: bool = False,
    profile_dir: str = DEFAULT_PROFILE_DIR,
    max_files: int | None = None,
    max_jobs: int | None = None,
    use_cache: bool = True,
) -> list[JobPosting]:
    """Pull, enrich, and write the enriched email jobs into the ``data/raw`` pile.

    Returns the enriched jobs that were written (empty list if none). For the
    Azure pipeline handoff instead, see :mod:`pipeline.email_overnight`.
    """
    enriched = enrich_email_jobs(
        pull=pull,
        max_emails=max_emails,
        directory_path=directory_path,
        archive_dir_path=archive_dir_path,
        max_age_hours=max_age_hours,
        archive_processed=archive_processed,
        headless=headless,
        profile_dir=profile_dir,
        max_files=max_files,
        max_jobs=max_jobs,
        use_cache=use_cache,
    )
    dest = write_pile(enriched, run_date)
    if dest:
        log.info("Pile ready for the pipeline: %s", dest)
    return enriched


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pull ZR alert emails, enrich them, and write the pipeline pile."
    )
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Skip the Gmail download; reprocess already-downloaded .eml files.",
    )
    parser.add_argument(
        "--max-emails",
        type=int,
        default=MAX_EMAILS,
        help="Download at most N newest emails. Defaults to config max_emails.",
    )
    parser.add_argument(
        "--run-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Write the pile under data/raw/<run-date>/ (default: today).",
    )
    parser.add_argument(
        "--include-stale",
        action="store_true",
        help="Process all emails regardless of age (default skips >96h old).",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Move successfully parsed .eml files to the archive dir.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless without the Chrome profile (ZR /km/ will hit Cloudflare).",
    )
    parser.add_argument(
        "--profile-dir",
        default=DEFAULT_PROFILE_DIR,
        help="Chrome user-data-dir for the Cloudflare piggyback (Chrome must be closed).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Only process the newest N .eml files (default: all, age-gated).",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Stop after enriching N parsed jobs across emails (handy for quick runs).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the Layer-1 processed-email cache (reprocess everything).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(
        pull=not args.no_pull,
        max_emails=args.max_emails,
        run_date=args.run_date,
        max_age_hours=None if args.include_stale else DEFAULT_MAX_AGE_HOURS,
        archive_processed=args.archive,
        headless=args.headless,
        profile_dir=args.profile_dir,
        max_files=args.max_files,
        max_jobs=args.max_jobs,
        use_cache=not args.no_cache,
    )
