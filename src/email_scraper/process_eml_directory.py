"""Process downloaded Gmail .eml files into JobPosting objects.

This module is the orchestration layer:
  1. Read downloaded .eml files from disk.
  2. Extract the raw text/plain MIME payload from each email.
  3. Hand that payload to the ZipRecruiter parser.

Note: parse_zr_plaintext currently also enriches each parsed job by calling the
ZipRecruiter page scraper for the full description and posted date.
"""

import argparse
import email
import logging
import shutil
from email.message import Message
from pathlib import Path

import yaml

from email_scraper.zr_parser import parse_zr_plaintext
from job_scraper.models import JobPosting

log = logging.getLogger(__name__)

CONFIG_PATH = Path("config/email_scraper/config.yml")
DEFAULT_INPUT_DIR = "data/emails/scraped"
DEFAULT_ARCHIVE_DIR_FALLBACK = "data/emails/archived"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r") as f:
        return yaml.safe_load(f) or {}


_CONFIG = _load_config()
DEFAULT_DIRECTORY = _CONFIG.get("output_dir", DEFAULT_INPUT_DIR)
DEFAULT_ARCHIVE_DIR = _CONFIG.get("archive_dir", DEFAULT_ARCHIVE_DIR_FALLBACK)
DEFAULT_MAX_FILES = _CONFIG.get("max_emails")


def _extract_text_plain_payload(msg: Message) -> str | bytes | None:
    """Return the raw text/plain MIME payload from an email message.

    We intentionally use get_payload(decode=False) because zr_parser owns
    quoted-printable decoding. That keeps the EML extraction layer thin and
    avoids decoding the same content in two different places.
    """
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = part.get("Content-Disposition", "").lower()
            if content_disposition.startswith("attachment"):
                continue
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=False)
                return payload if isinstance(payload, (str, bytes)) else None
        return None

    if msg.get_content_type() != "text/plain":
        return None

    payload = msg.get_payload(decode=False)
    return payload if isinstance(payload, (str, bytes)) else None


def _select_eml_files(eml_dir: Path, max_files: int | None) -> list[Path]:
    """Return newest .eml files in the directory, excluding subdirectories."""
    if max_files is not None and max_files <= 0:
        raise ValueError("max_files must be a positive integer")

    eml_files = sorted(
        (path for path in eml_dir.glob("*.eml") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return eml_files[:max_files] if max_files is not None else eml_files


def _archive_eml_file(eml_file: Path, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / eml_file.name
    shutil.move(str(eml_file), str(destination))
    log.info("Archived %s -> %s", eml_file, destination)


def process_eml_directory(
    directory_path: str = DEFAULT_DIRECTORY,
    archive_dir_path: str = DEFAULT_ARCHIVE_DIR,
    max_files: int | None = DEFAULT_MAX_FILES,
    max_jobs: int | None = None,
    skip_jobs: int = 0,
    scrape_details: bool = True,
    archive_processed: bool = False,
) -> list[JobPosting]:
    """Parse newest downloaded .eml files into JobPosting objects.

    Args:
        directory_path: Directory containing downloaded .eml files.
        archive_dir_path: Directory where successfully parsed .eml files are
            moved when archive_processed is true.
        max_files: Only process the newest N .eml files. Defaults to
            config/email_scraper/config.yml:max_emails when present.
        max_jobs: Stop after parsing this many jobs across all selected emails.
            Useful for fast scraper iteration, e.g. --max-jobs 1.
        skip_jobs: Skip this many parsed job blocks before processing. Useful
            with --max-jobs 1 to test a specific email job link.
        scrape_details: Visit each ZR job URL to enrich description/posted_at.
            Disable for parser-only smoke tests.
        archive_processed: Move successfully parsed .eml files to archive_dir_path
            after parsing.

    Returns:
        Parsed/enriched JobPosting objects.
    """
    if max_jobs is not None and max_jobs <= 0:
        raise ValueError("max_jobs must be a positive integer")
    if skip_jobs < 0:
        raise ValueError("skip_jobs must be zero or a positive integer")

    eml_dir = Path(directory_path)
    archive_dir = Path(archive_dir_path)
    if not eml_dir.exists():
        raise FileNotFoundError(f"Directory {directory_path} not found")

    eml_files = _select_eml_files(eml_dir, max_files)
    if not eml_files:
        log.info("No .eml files found in %s", eml_dir)
        return []

    log.info("Processing %s .eml file(s) from %s", len(eml_files), eml_dir)
    all_new_jobs: list[JobPosting] = []

    for eml_file in eml_files:
        log.info("Processing %s", eml_file.name)
        with eml_file.open("rb") as f:
            msg = email.message_from_binary_file(f)

        payload = _extract_text_plain_payload(msg)
        if payload is None:
            log.warning(
                "No text/plain payload found in %s; leaving file in place", eml_file
            )
            continue

        remaining_jobs = None if max_jobs is None else max_jobs - len(all_new_jobs)
        if remaining_jobs is not None and remaining_jobs <= 0:
            break

        parsed_jobs = parse_zr_plaintext(
            payload,
            max_jobs=remaining_jobs,
            skip_jobs=skip_jobs,
            scrape_details=scrape_details,
        )
        if not parsed_jobs:
            log.warning("No jobs parsed from %s; leaving file in place", eml_file)
            continue

        all_new_jobs.extend(parsed_jobs)
        log.info("Extracted %s job(s) from %s", len(parsed_jobs), eml_file.name)

        if archive_processed:
            _archive_eml_file(eml_file, archive_dir)

        if max_jobs is not None and len(all_new_jobs) >= max_jobs:
            log.info("Reached --max-jobs=%s; stopping early", max_jobs)
            break

    if all_new_jobs:
        log.info("Successfully extracted %s job(s).", len(all_new_jobs))
    else:
        log.info("No new jobs extracted.")

    return all_new_jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process downloaded ZR .eml files.")
    parser.add_argument(
        "--directory",
        default=DEFAULT_DIRECTORY,
        help="Directory containing downloaded .eml files.",
    )
    parser.add_argument(
        "--archive-dir",
        default=DEFAULT_ARCHIVE_DIR,
        help="Directory to move processed .eml files into when archiving.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        help="Only process the newest N .eml files. Defaults to config max_emails.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Only parse/scrape the first N jobs across selected emails.",
    )
    parser.add_argument(
        "--skip-jobs",
        type=int,
        default=0,
        help="Skip the first N parsed jobs before processing.",
    )
    parser.add_argument(
        "--job-index",
        type=int,
        default=None,
        help="Shortcut for --skip-jobs N --max-jobs 1; useful for testing one job URL.",
    )
    parser.add_argument(
        "--print-jobs",
        action="store_true",
        help="Print parsed job titles and URLs after processing.",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Parse email jobs only; do not visit ZipRecruiter detail pages.",
    )
    parser.add_argument(
        "--archive-processed",
        action="store_true",
        help="Move successfully parsed .eml files to archive_dir.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    max_jobs = 1 if args.job_index is not None else args.max_jobs
    skip_jobs = args.job_index if args.job_index is not None else args.skip_jobs
    jobs = process_eml_directory(
        directory_path=args.directory,
        archive_dir_path=args.archive_dir,
        max_files=args.max_files,
        max_jobs=max_jobs,
        skip_jobs=skip_jobs,
        scrape_details=not args.no_scrape,
        archive_processed=args.archive_processed,
    )
    if args.print_jobs:
        for idx, job in enumerate(jobs, start=skip_jobs):
            print(f"[{idx}] {job.title} — {job.source_url}")
