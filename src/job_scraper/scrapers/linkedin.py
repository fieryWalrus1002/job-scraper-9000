import re
import time
import random
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from ..models import JobPosting
from ..pii import scrub
from ..query import LinkedInSearchQuery
from .base import BaseScraper

log = logging.getLogger(__name__)

GUEST_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
GUEST_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class LinkedInJobScraper(BaseScraper["LinkedInSearchQuery"]):
    def __init__(
        self, query: LinkedInSearchQuery, min_delay: float = 2.0, max_delay: float = 5.0
    ):
        self.query = query
        self.session = requests.Session()
        self.min_delay = min_delay
        self.max_delay = max_delay

    @property
    def source_name(self) -> str:
        return "linkedin"

    def describe(self) -> dict:
        return {
            "source": self.source_name,
            "keywords": self.query.keywords,
            "time_posted": self.query.time_posted,
            "workplace": self.query.workplace,
            "salary_floor": self.query.salary_floor,
            "max_results": self.query.max_results,
        }

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def fetch_search_page(self, start: int = 0) -> list[dict]:
        url = self.query.to_url(GUEST_SEARCH_URL, start=start)
        log.info("GET %s", url)
        resp = self.session.get(url, headers=self._headers(), timeout=15)
        if resp.status_code == 429:
            log.warning("Rate limited — backing off 60s")
            time.sleep(60)
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for card in soup.find_all("div", class_="base-card"):
            try:
                results.append(_parse_card(card))
            except Exception as exc:
                log.warning("Failed to parse card: %s", exc)
        return results

    def fetch_description(self, job_id: str) -> str:
        url = f"{GUEST_DETAIL_URL}/{job_id}"
        resp = self.session.get(url, headers=self._headers(), timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        desc = soup.find("div", class_="show-more-less-html__markup")
        return desc.get_text("\n", strip=True) if desc else ""

    def scrape(self) -> list[JobPosting]:
        all_jobs: list[JobPosting] = []
        seen_ids: set[str] = set()
        start = 0

        while len(all_jobs) < self.query.max_results:
            stubs = self.fetch_search_page(start=start)
            if not stubs:
                break

            new_count = 0
            for stub in stubs:
                if not stub["source_job_id"] or stub["source_job_id"] in seen_ids:
                    continue
                seen_ids.add(stub["source_job_id"])
                new_count += 1

                description = ""
                scrub_counts: dict = {"email": 0, "phone": 0}
                if self.query.fetch_descriptions:
                    raw = self.fetch_description(stub["source_job_id"])
                    description, scrub_counts = scrub(raw)
                    self._sleep()

                job = JobPosting(
                    source=self.source_name,
                    source_job_id=stub["source_job_id"],
                    source_url=stub["source_url"],
                    title=stub["title"],
                    company=stub["company"],
                    location=stub["location"],
                    posted_at=stub["posted_at"],
                    description=description,
                    scraped_at=datetime.now(timezone.utc).isoformat(),
                    scrub_counts=scrub_counts,
                    search_params=_search_params(self.query),
                )
                job.compute_hash()
                all_jobs.append(job)
                if len(all_jobs) >= self.query.max_results:
                    break

            log.info(
                "Page start=%d: %d new jobs (total: %d)",
                start,
                new_count,
                len(all_jobs),
            )
            if new_count == 0:
                break
            start += 25
            self._sleep()

        return all_jobs


_WORKPLACE_LABEL = {"1": "onsite", "2": "remote", "3": "hybrid"}
_JOBTYPE_LABEL = {"F": "fulltime", "P": "parttime", "C": "contract"}


def _search_params(query: LinkedInSearchQuery) -> dict:
    return {
        "keywords": query.keywords,
        "workplace": _WORKPLACE_LABEL.get(query.workplace, query.workplace),
        "job_type": _JOBTYPE_LABEL.get(query.job_type, query.job_type),
        "experience": query.experience,
        "salary_floor": query.salary_floor,
    }


def _parse_card(card) -> dict:
    link_tag = card.find("a", class_="base-card__full-link")
    title_tag = card.find("h3", class_="base-search-card__title")
    company_tag = card.find("h4", class_="base-search-card__subtitle")
    location_tag = card.find("span", class_="job-search-card__location")
    time_tag = card.find("time")

    url = link_tag["href"].split("?")[0] if link_tag else ""
    match = re.search(r"-(\d+)$", url)

    return {
        "source_url": url,
        "source_job_id": match.group(1) if match else "",
        "title": title_tag.get_text(strip=True) if title_tag else "",
        "company": company_tag.get_text(strip=True) if company_tag else "",
        "location": location_tag.get_text(strip=True) if location_tag else "",
        "posted_at": time_tag.get("datetime") if time_tag else None,
    }
