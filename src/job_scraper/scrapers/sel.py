import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from ..models import JobPosting
from ..pii import scrub
from ..query import SELSearchQuery
from .base import BaseScraper

log = logging.getLogger(__name__)

_JOBS_API = "https://selinc.wd1.myworkdayjobs.com/wday/cxs/selinc/SEL/jobs"
_DETAIL_API = "https://selinc.wd1.myworkdayjobs.com/wday/cxs/selinc/SEL/job"
_DOMAIN = "https://selinc.wd1.myworkdayjobs.com"
_PAGE_SIZE = 20


class SELJobScraper(BaseScraper["SELSearchQuery"]):
    def __init__(self, query: SELSearchQuery):
        self.query = query
        self.session = requests.Session()

    @property
    def source_name(self) -> str:
        return "sel"

    def _fetch_detail(self, job_path: str) -> dict:
        """Hits the Workday detail JSON API. Returns jobPostingInfo dict or empty dict."""
        api_url = f"{_DETAIL_API}{job_path.replace('/job', '')}"
        try:
            resp = self.session.get(api_url, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("jobPostingInfo", {})
        except Exception as e:
            log.warning("Failed detail fetch for %s: %s", job_path, e)
        return {}

    def scrape(self) -> list[JobPosting]:
        applied_facets = self.query.to_applied_facets()
        log.info("SEL: querying %s | facets=%s", _JOBS_API, applied_facets)

        all_jobs: list[JobPosting] = []
        offset = 0
        total: int | None = None

        while True:
            payload = {
                "limit": _PAGE_SIZE,
                "offset": offset,
                "searchText": "",
                "appliedFacets": applied_facets,
            }
            resp = self.session.post(_JOBS_API, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if total is None:
                total = data.get("total", 0)

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for item in postings:
                path = item.get("externalPath", "")

                detail: dict = {}
                if self.query.fetch_descriptions and path:
                    detail = self._fetch_detail(path)

                description_html = detail.get("jobDescription", "")
                description_raw = BeautifulSoup(
                    description_html, "html.parser"
                ).get_text("\n", strip=True) if description_html else ""
                description, scrub_counts = scrub(description_raw)

                bullet_fields = item.get("bulletFields") or []
                source_job_id = bullet_fields[0] if bullet_fields else path.rsplit("_", 1)[-1]

                job = JobPosting(
                    source=self.source_name,
                    source_job_id=source_job_id,
                    source_url=f"{_DOMAIN}{path}",
                    title=item.get("title", ""),
                    company="SEL",
                    location=item.get("locationsText", ""),
                    posted_at=detail.get("postedOn"),
                    description=description,
                    scraped_at=datetime.now(timezone.utc).isoformat(),
                    scrub_counts=scrub_counts,
                )
                job.compute_hash()
                all_jobs.append(job)

            offset += len(postings)
            if total is not None and offset >= total:
                break

        log.info("Ingested %d jobs from SEL.", len(all_jobs))
        return all_jobs
