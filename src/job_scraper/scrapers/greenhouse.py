import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from ..models import JobPosting
from ..pii import scrub
from .base import BaseScraper

log = logging.getLogger(__name__)

# Greenhouse has a public JSON API — no Selenium needed for most boards.
# For boards that block the API or use a custom ATS, fall back to BS4+Selenium.
_BOARDS_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


@dataclass
class GreenhouseQuery:
    board_token: str  # e.g. "anthropic" → boards.greenhouse.io/anthropic
    fetch_descriptions: bool = True


class GreenhouseScraper(BaseScraper["GreenhouseQuery"]):
    def __init__(self, query: GreenhouseQuery):
        self.query = query
        self.session = requests.Session()

    @property
    def source_name(self) -> str:
        return f"greenhouse:{self.query.board_token}"

    def describe(self) -> dict:
        return {
            "source": self.source_name,
            "board_token": self.query.board_token,
        }

    def scrape(self) -> list[JobPosting]:
        url = _BOARDS_API.format(token=self.query.board_token)
        params = {"content": "true"} if self.query.fetch_descriptions else {}
        log.info("GET %s", url)
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        jobs: list[JobPosting] = []
        for item in data.get("jobs", []):
            raw_desc = item.get("content") or ""
            description, scrub_counts = scrub(raw_desc)

            location = ""
            loc = item.get("location")
            if isinstance(loc, dict):
                location = loc.get("name", "")
            elif isinstance(loc, str):
                location = loc

            job = JobPosting(
                source=self.source_name,
                source_job_id=str(item.get("id", "")),
                source_url=item.get("absolute_url", ""),
                title=item.get("title", ""),
                company=self.query.board_token,
                location=location,
                posted_at=item.get("updated_at"),
                description=description,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                scrub_counts=scrub_counts,
                search_params={"board_token": self.query.board_token},
            )
            job.compute_hash()
            jobs.append(job)

        log.info("Greenhouse %s: %d jobs", self.query.board_token, len(jobs))
        return jobs
