import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from utils.salary import extract_salary

from ..description_formatting import clean_description
from ..models import JobPosting
from ..query import SELSearchQuery
from ..search_provenance import build_search_params
from .base import BaseScraper

log = logging.getLogger(__name__)

_JOBS_API = "https://selinc.wd1.myworkdayjobs.com/wday/cxs/selinc/SEL/jobs"
_DETAIL_API = "https://selinc.wd1.myworkdayjobs.com/wday/cxs/selinc/SEL/job"
_DOMAIN = "https://selinc.wd1.myworkdayjobs.com/SEL"
_PAGE_SIZE = 20

_LOCATION_DISPLAY: dict[str, str] = {
    "pullman_wa": "Washington - Pullman",
}

_MULTI_LOCATION_RE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)
_DAYS_AGO_RE = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def _workday_detail_search_params(detail: dict) -> dict:
    """Return remote-filter-relevant Workday detail metadata.

    Workday exposes header fields like ``location=Remote`` and
    ``timeType=Full time`` outside ``jobDescription``. Preserve them so the
    remote filter does not have to infer from the description alone.
    """
    context: dict[str, Any] = {}

    locations = _workday_detail_locations(detail)
    if locations:
        context["source_detail_location"] = "; ".join(locations)
        if any(str(loc).strip().lower() == "remote" for loc in locations):
            context["workplace"] = "remote"

    time_type = str(detail.get("timeType") or "").strip().lower()
    if time_type.replace("-", " ") == "full time":
        context["job_type"] = "fulltime"

    if job_req_id := detail.get("jobReqId"):
        context["workday_job_req_id"] = job_req_id

    return build_search_params(**context)


def _workday_detail_locations(detail: dict) -> list[str]:
    locations = []
    if location := detail.get("location") or detail.get("locationsText"):
        if not _MULTI_LOCATION_RE.match(str(location)):
            locations.append(str(location))
    locations.extend(str(loc) for loc in detail.get("additionalLocations") or [])
    return [loc for loc in dict.fromkeys(loc.strip() for loc in locations) if loc]


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
        """Fetch Workday detail JSON and return the ``jobPostingInfo`` object.

        Detail fields include source-of-truth header metadata such as remote
        location and time type, so failures must surface at the scrape-job
        boundary instead of silently degrading downstream classification.
        """
        api_url = f"{_DETAIL_API}{job_path.replace('/job', '')}"
        resp = self.session.get(api_url, timeout=10)
        resp.raise_for_status()
        info = resp.json().get("jobPostingInfo")
        if not isinstance(info, dict):
            raise ValueError(
                f"Workday detail response missing jobPostingInfo: {api_url}"
            )
        return info

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

                # Workday header metadata (location/time type/job req) is part of
                # the posting contract, not just the long description. Always fetch
                # detail JSON when a path exists; ``fetch_descriptions`` only gates
                # whether we retain the description body.
                detail: dict = self._fetch_detail(path) if path else {}

                description_html = (
                    detail.get("jobDescription", "")
                    if self.query.fetch_descriptions
                    else ""
                )
                description, scrub_counts = clean_description(description_html)

                bullet_fields = item.get("bulletFields") or []
                source_job_id = (
                    bullet_fields[0] if bullet_fields else path.rsplit("_", 1)[-1]
                )

                item_detail = {
                    "location": item.get("locationsText"),
                    "timeType": item.get("timeType"),
                    "jobReqId": source_job_id,
                }
                detail_search_params = _workday_detail_search_params(
                    {**item_detail, **detail}
                )
                detail_location = detail_search_params.get("source_detail_location")
                raw_location = item.get("locationsText", "")
                location = (
                    str(detail_location)
                    if detail_location
                    else fallback_location
                    if _MULTI_LOCATION_RE.match(raw_location) and fallback_location
                    else raw_location
                )

                title = item.get("title", "").strip()

                salary = extract_salary(description)
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
                    search_params=detail_search_params,
                    salary_min_usd=salary.salary_min_usd if salary else None,
                    salary_max_usd=salary.salary_max_usd if salary else None,
                    salary_period=salary.salary_period if salary else None,
                )
                job.compute_hash()

                # Post-fetch Validation Gate: Only append if it hits your target software domains
                # This prevents the scraper from ingesting all those SEL jobs that I have no interest in,
                # and cost me mad rubels in OpenAI calls.
                if self.query.allowed_title_keywords:
                    title_lower = title.lower()
                    is_relevant = any(
                        kw.lower() in title_lower
                        for kw in self.query.allowed_title_keywords
                    )
                    if not is_relevant:
                        log.debug("SEL: Dropping non-software role: %s", title)
                        continue

                all_jobs.append(job)

            offset += len(postings)
            if total is not None and offset >= total:
                break

        log.info("Ingested %d jobs from SEL.", len(all_jobs))
        return all_jobs
