import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from utils.salary import SalaryResult, annualise, extract_salary

from ..models import JobPosting
from ..pii import scrub
from .base import BaseScraper

log = logging.getLogger(__name__)

# Sites python-jobspy supports natively
JOBSPY_SITES = ("linkedin", "indeed", "glassdoor", "zip_recruiter", "google")


@dataclass
class JobSpyQuery:
    search_term: str
    location: str = "USA"
    site_name: list[str] = field(
        default_factory=lambda: ["linkedin", "indeed", "zip_recruiter"]
    )
    job_type: str | None = "fulltime"  # fulltime, parttime, internship, contract
    is_remote: bool = True
    hours_old: int = 24
    results_wanted: int = 100
    enforce_annual_salary: bool = False
    linkedin_fetch_description: bool = True
    country_indeed: str = "USA"


class JobSpyScraper(BaseScraper["JobSpyQuery"]):
    def __init__(self, query: JobSpyQuery):
        self.query = query

    @property
    def source_name(self) -> str:
        return "jobspy:" + "+".join(self.query.site_name)

    def describe(self) -> dict:
        return {
            "source": self.source_name,
            "search_term": self.query.search_term,
            "sites": self.query.site_name,
            "location": self.query.location,
            "hours_old": self.query.hours_old,
            "is_remote": self.query.is_remote,
        }

    def scrape(self) -> list[JobPosting]:
        from jobspy import scrape_jobs  # deferred: large import (pandas, numpy)

        log.info(
            "JobSpy scraping %s for %r", self.query.site_name, self.query.search_term
        )
        df = scrape_jobs(
            site_name=self.query.site_name,
            search_term=self.query.search_term,
            location=self.query.location,
            job_type=self.query.job_type,
            is_remote=self.query.is_remote,
            hours_old=self.query.hours_old,
            results_wanted=self.query.results_wanted,
            enforce_annual_salary=self.query.enforce_annual_salary,
            linkedin_fetch_description=self.query.linkedin_fetch_description,
            country_indeed=self.query.country_indeed,
            verbose=0,
        )

        jobs: list[JobPosting] = []
        for _, row in df.iterrows():
            raw_desc = str(row.get("description") or "")
            description, scrub_counts = scrub(raw_desc)

            salary = _salary_from_row(row) or extract_salary(description)

            url = str(row.get("job_url") or "")
            job = JobPosting(
                source=str(row.get("site") or self.source_name),
                source_job_id=_id_from_url(url),
                source_url=url,
                title=str(row.get("title") or ""),
                company=str(row.get("company") or ""),
                location=str(row.get("location") or ""),
                # JobPosting.__post_init__ normalizes this (pandas Timestamp/NaT,
                # float NaN, datetime-ish strings) into the date-only contract.
                posted_at=row.get("date_posted"),
                description=description,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                scrub_counts=scrub_counts,
                search_params={
                    "search_term": self.query.search_term,
                    "sites": self.query.site_name,
                    "location": self.query.location,
                    "is_remote": self.query.is_remote,
                    "job_type": self.query.job_type,
                },
                salary_min_usd=salary.salary_min_usd if salary else None,
                salary_max_usd=salary.salary_max_usd if salary else None,
                salary_period=salary.salary_period if salary else None,
            )
            job.compute_hash()
            jobs.append(job)

        log.info("JobSpy returned %d jobs", len(jobs))
        return jobs


def _id_from_url(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16] if url else ""


_JOBSPY_PERIOD_MAP = {
    "yearly": "yearly",
    "monthly": "monthly",
    "weekly": "weekly",
    "daily": "daily",
    "hourly": "hourly",
}


def _salary_from_row(row) -> SalaryResult | None:
    """Extract structured salary from a jobspy DataFrame row."""
    min_amt = row.get("min_amount")
    max_amt = row.get("max_amount")
    interval = str(row.get("interval") or "").lower()

    if not isinstance(min_amt, (int, float)) or math.isnan(float(min_amt)):
        return None

    period = _JOBSPY_PERIOD_MAP.get(interval, "yearly")
    return SalaryResult(
        salary_min_usd=annualise(float(min_amt), period),
        salary_max_usd=(
            annualise(float(max_amt), period)
            if isinstance(max_amt, (int, float)) and not math.isnan(float(max_amt))
            else None
        ),
        salary_period=period,
    )
