import json
import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from ..models import JobPosting
from ..pii import scrub
from ..query import SELSearchQuery
from .base import BaseScraper

log = logging.getLogger(__name__)


class SELJobScraper(BaseScraper["SELSearchQuery"]):
    def __init__(self, query: SELSearchQuery):
        self.query = query
        self.session = requests.Session()
        self.domain = "https://selinc.wd1.myworkdayjobs.com"
        self.base_url = f"{self.domain}/en-US/SEL"
        self.detail_api = f"{self.domain}/wday/cxs/selinc/SEL/job"

    @property
    def source_name(self) -> str:
        return "sel"

    def _extract_json(self, html: str) -> dict:
        """Extracts the initial state JSON from the Workday landing page."""
        match = re.search(r'data-initial-state="({.*?})"', html)
        if match:
            try:
                return json.loads(match.group(1).replace("&quot;", '"'))
            except json.JSONDecodeError as e:
                log.error("Workday JSON decode failed: %s", e)
        return {}

    def fetch_description(self, job_path: str) -> str:
        """Hits the hidden JSON API for the full job spec."""
        api_url = f"{self.detail_api}{job_path.replace('/job', '')}"
        try:
            resp = self.session.get(api_url, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("jobDescription", "")
        except Exception as e:
            log.warning("Failed enrichment for %s: %s", job_path, e)
        return ""

    def scrape(self) -> list[JobPosting]:
        url = self.query.to_url(self.base_url)
        log.info("Starting discovery at %s", url)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()

        state = self._extract_json(resp.text)
        postings = state.get("jobPostings", [])

        all_jobs = []
        for item in postings:
            path = item.get("externalPath")

            description_raw = ""
            if self.query.fetch_descriptions and path:
                description_raw = self.fetch_description(path)
                description_raw = BeautifulSoup(
                    description_raw, "html.parser"
                ).get_text("\n", strip=True)

            description, scrub_counts = scrub(description_raw)

            job = JobPosting(
                source=self.source_name,
                source_job_id=item.get("bulletinId") or item.get("jobPostingId"),
                source_url=f"{self.domain}{path}",
                title=item.get("title", ""),
                company="SEL",
                location=item.get("location", ""),
                posted_at=item.get("postedOn"),
                description=description,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                scrub_counts=scrub_counts,
            )
            job.compute_hash()
            all_jobs.append(job)

        log.info("Ingested %d jobs from SEL.", len(all_jobs))
        return all_jobs
