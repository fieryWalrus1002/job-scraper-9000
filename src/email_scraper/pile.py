"""Write enriched email jobs into the pipeline's raw pile.

Every scraper hands the pipeline an append-only JSONL file under ``data/raw/``;
``prefilter`` then reads that directory. This module does the same for email
jobs by reusing the scrapers' own writer (``jobs_cli._common``), so email
postings are indistinguishable from any other source once they land in the pile
— no parallel format, no special-casing downstream.
"""

import logging
from pathlib import Path

from jobs_cli._common import _auto_path, _output
from job_scraper.models import JobPosting

log = logging.getLogger(__name__)

# Mirrors JobPosting.source set by zr_parser; the keywords slot has no real
# search term for alerts, so we use a stable label.
PILE_SOURCE = "ZipRecruiter_Email"
PILE_KEYWORDS = "email-alerts"


def write_pile(jobs: list[JobPosting], run_date: str | None = None) -> Path | None:
    """Write *jobs* to ``data/raw/[run_date/]<ts>_ZipRecruiter_Email_email-alerts.jsonl``.

    Returns the destination path, or None for an empty list (we skip writing an
    empty file rather than leave a misleading zero-job artifact in the pile).
    """
    if not jobs:
        log.info("No jobs to write to the pile; skipping.")
        return None

    dest = _auto_path(PILE_SOURCE, PILE_KEYWORDS, run_date)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # _output serializes via json.dumps(asdict(job)) — JobPosting is a dataclass,
    # so enrichment_status and every other field ride along automatically.
    _output(jobs, dest)
    return dest
