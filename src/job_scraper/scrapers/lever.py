import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from utils.salary import extract_salary

from ..description_formatting import html_to_markdown
from ..models import JobPosting
from ..pii import scrub
from ..search_provenance import build_search_params
from .base import BaseScraper

log = logging.getLogger(__name__)

_POSTINGS_API = "https://api.lever.co/v0/postings/{company}?mode=json"


@dataclass
class LeverQuery:
    company: str  # slug from jobs.lever.co/<company>
    fetch_descriptions: bool = True


class LeverScraper(BaseScraper["LeverQuery"]):
    def __init__(self, query: LeverQuery):
        self.query = query
        self.session = requests.Session()

    @property
    def source_name(self) -> str:
        return f"lever:{self.query.company}"

    def describe(self) -> dict:
        return {
            "source": self.source_name,
            "company": self.query.company,
        }

    def scrape(self) -> list[JobPosting]:
        url = _POSTINGS_API.format(company=self.query.company)
        log.info("GET %s", url)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        jobs: list[JobPosting] = []
        for item in data:
            raw_desc = ""
            if self.query.fetch_descriptions:
                raw_desc = item.get("descriptionPlain") or html_to_markdown(
                    item.get("description") or ""
                )
            description, scrub_counts = scrub(raw_desc)

            location = (item.get("categories") or {}).get("location", "")

            created_ms = item.get("createdAt")
            posted_at = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
                if created_ms
                else None
            )

            salary = extract_salary(description)
            job = JobPosting(
                source=self.source_name,
                source_job_id=str(item.get("id", "")),
                source_url=item.get("hostedUrl", ""),
                title=item.get("text", ""),
                company=self.query.company,
                location=location,
                posted_at=posted_at,
                description=description,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                scrub_counts=scrub_counts,
                search_params=build_search_params(company=self.query.company),
                salary_min_usd=salary.salary_min_usd if salary else None,
                salary_max_usd=salary.salary_max_usd if salary else None,
                salary_period=salary.salary_period if salary else None,
            )
            job.compute_hash()
            jobs.append(job)

        log.info("Lever %s: %d jobs", self.query.company, len(jobs))
        return jobs
