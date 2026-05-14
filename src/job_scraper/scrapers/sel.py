import logging
import re
from datetime import datetime, timedelta, timezone

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

_LOCATION_DISPLAY: dict[str, str] = {
    "pullman_wa": "Washington - Pullman",
}

_MULTI_LOCATION_RE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)
_DAYS_AGO_RE = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def _parse_posted_at(relative: str | None, ref_iso: str) -> str | None:
    """Convert a Workday relative date string to an ISO date string.

    Uses ref_iso (the scraped_at timestamp) as "today" so the result stays
    accurate even when the record is read days later.
    """
    if not relative:
        return None
    s = relative.strip()
    try:
        ref = datetime.fromisoformat(ref_iso).date()
    except (ValueError, TypeError):
        return s
    sl = s.lower()
    if sl == "posted today":
        return ref.isoformat()
    if sl == "posted yesterday":
        return (ref - timedelta(days=1)).isoformat()
    m = _DAYS_AGO_RE.match(s)
    if m:
        return (ref - timedelta(days=int(m.group(1)))).isoformat()
    return s


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

        fallback_location = _LOCATION_DISPLAY.get(self.query.location_key, "")
        scraped_at = datetime.now(timezone.utc).isoformat()

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
                description_raw = (
                    BeautifulSoup(description_html, "html.parser").get_text("\n", strip=True)
                    if description_html
                    else ""
                )
                description, scrub_counts = scrub(description_raw)

                bullet_fields = item.get("bulletFields") or []
                source_job_id = bullet_fields[0] if bullet_fields else path.rsplit("_", 1)[-1]

                raw_location = item.get("locationsText", "")
                location = (
                    fallback_location
                    if _MULTI_LOCATION_RE.match(raw_location) and fallback_location
                    else raw_location
                )

                title = item.get("title", "").strip()

                job = JobPosting(
                    source=self.source_name,
                    source_job_id=source_job_id,
                    source_url=f"{_DOMAIN}{path}",
                    title=title,
                    company="SEL",
                    location=location,
                    posted_at=_parse_posted_at(detail.get("postedOn"), scraped_at),
                    description=description,
                    scraped_at=scraped_at,
                    scrub_counts=scrub_counts,
                )
                job.compute_hash()
                all_jobs.append(job)

            offset += len(postings)
            if total is not None and offset >= total:
                break

        log.info("Ingested %d jobs from SEL.", len(all_jobs))
        return all_jobs
