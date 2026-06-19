import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from utils.salary import extract_salary

from ..description_formatting import html_to_markdown
from ..models import JobPosting
from ..pii import scrub
from .base import BaseScraper

log = logging.getLogger(__name__)

_POSTINGS_API = "https://api.ashbyhq.com/posting-api/job-board/{company}"


@dataclass
class AshbyQuery:
    company: str  # slug from jobs.ashbyhq.com/<company>
    fetch_descriptions: bool = True


class AshbyScraper(BaseScraper["AshbyQuery"]):
    def __init__(self, query: AshbyQuery):
        self.query = query
        self.session = requests.Session()

    @property
    def source_name(self) -> str:
        return f"ashby:{self.query.company}"

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
        for item in data.get("jobs", []):
            raw_desc = ""
            if self.query.fetch_descriptions:
                raw_desc = item.get("descriptionPlain") or html_to_markdown(
                    item.get("descriptionHtml") or ""
                )
            description, scrub_counts = scrub(raw_desc)

            salary = extract_salary(description)
            job = JobPosting(
                source=self.source_name,
                source_job_id=str(item.get("id", "")),
                source_url=item.get("jobUrl", ""),
                title=item.get("title", ""),
                company=self.query.company,
                location=item.get("location", ""),
                posted_at=item.get("publishedAt"),
                description=description,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                scrub_counts=scrub_counts,
                search_params={"company": self.query.company},
                salary_min_usd=salary.salary_min_usd if salary else None,
                salary_max_usd=salary.salary_max_usd if salary else None,
                salary_period=salary.salary_period if salary else None,
            )
            job.compute_hash()
            jobs.append(job)

        log.info("Ashby %s: %d jobs", self.query.company, len(jobs))
        return jobs
