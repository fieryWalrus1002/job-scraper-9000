"""
linkedin_jobs.py — minimal LinkedIn job scraper using the guest endpoint.
No login, no Selenium. For personal/research use; respect robots.txt and ToS.
"""
import re
import time
import random
import hashlib
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

GUEST_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# --- PII scrubbing ---------------------------------------------------------
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")

def scrub(text: str) -> tuple[str, dict]:
    counts = {"email": 0, "phone": 0}
    if not text:
        return text, counts
    text, n = EMAIL_RE.subn("[EMAIL_REDACTED]", text)
    counts["email"] = n
    text, n = PHONE_RE.subn("[PHONE_REDACTED]", text)
    counts["phone"] = n
    return text, counts

# --- Data model ------------------------------------------------------------
@dataclass
class JobPosting:
    source: str
    source_job_id: str
    source_url: str
    title: str
    company: str
    location: str
    posted_at: str | None
    description: str | None
    scraped_at: str
    scrub_counts: dict = field(default_factory=dict)
    dedup_hash: str = ""

    def compute_hash(self) -> None:
        # Normalize for cross-source dedup later
        key = "|".join([
            (self.company or "").lower().strip(),
            (self.title or "").lower().strip(),
            (self.location or "").lower().strip(),
        ])
        self.dedup_hash = hashlib.sha256(key.encode()).hexdigest()

# --- Scraper ---------------------------------------------------------------
class LinkedInJobScraper:
    def __init__(self, min_delay: float = 2.0, max_delay: float = 5.0):
        self.session = requests.Session()
        self.min_delay = min_delay
        self.max_delay = max_delay

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _build_search_url(self, *, keywords: str, location: str = "United States",
                          geo_id: str = "103644278", job_type: str = "F",
                          experience: str = "2,3,4,5", workplace: str = "2",
                          time_posted: str | None = "r86400",
                          sort_by: str = "DD", start: int = 0) -> str:
        params = {
            "keywords": keywords,
            "location": location,
            "geoId": geo_id,
            "f_JT": job_type,
            "f_E": experience,
            "f_WT": workplace,
            "sortBy": sort_by,
            "start": start,
        }
        if time_posted:
            params["f_TPR"] = time_posted
        return f"{GUEST_SEARCH_URL}?{urlencode(params)}"

    def fetch_search_page(self, **query) -> list[dict]:
        """Return list of job stubs from one page (25 results)."""
        url = self._build_search_url(**query)
        log.info(f"GET {url}")
        resp = self.session.get(url, headers=self._headers(), timeout=15)
        if resp.status_code == 429:
            log.warning("Rate limited. Backing off.")
            time.sleep(60)
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", class_="base-card")
        results = []
        for card in cards:
            try:
                results.append(self._parse_card(card))
            except Exception as e:
                log.warning(f"Failed to parse card: {e}")
        return results

    def _parse_card(self, card) -> dict:
        link_tag = card.find("a", class_="base-card__full-link")
        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        location_tag = card.find("span", class_="job-search-card__location")
        time_tag = card.find("time")

        url = link_tag["href"].split("?")[0] if link_tag else ""
        # Job ID is the trailing number in the URL
        job_id_match = re.search(r"-(\d+)$", url)
        job_id = job_id_match.group(1) if job_id_match else ""

        return {
            "source_url": url,
            "source_job_id": job_id,
            "title": title_tag.get_text(strip=True) if title_tag else "",
            "company": company_tag.get_text(strip=True) if company_tag else "",
            "location": location_tag.get_text(strip=True) if location_tag else "",
            "posted_at": time_tag.get("datetime") if time_tag else None,
        }

    def fetch_description(self, job_id: str) -> str:
        """Fetch full description for a single job."""
        url = f"{GUEST_DETAIL_URL}/{job_id}"
        resp = self.session.get(url, headers=self._headers(), timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        desc = soup.find("div", class_="show-more-less-html__markup")
        return desc.get_text("\n", strip=True) if desc else ""

    def scrape(self, *, keywords: str, max_results: int = 100, fetch_descriptions: bool = True,
               **query) -> list[JobPosting]:
        all_jobs: list[JobPosting] = []
        seen_ids: set[str] = set()
        start = 0

        while len(all_jobs) < max_results:
            stubs = self.fetch_search_page(keywords=keywords, start=start, **query)
            if not stubs:
                break
            new_count = 0
            for stub in stubs:
                if stub["source_job_id"] in seen_ids or not stub["source_job_id"]:
                    continue
                seen_ids.add(stub["source_job_id"])
                new_count += 1

                description = ""
                scrub_counts = {"email": 0, "phone": 0}
                if fetch_descriptions:
                    raw_desc = self.fetch_description(stub["source_job_id"])
                    description, scrub_counts = scrub(raw_desc)
                    self._sleep()

                job = JobPosting(
                    source="linkedin",
                    source_job_id=stub["source_job_id"],
                    source_url=stub["source_url"],
                    title=stub["title"],
                    company=stub["company"],
                    location=stub["location"],
                    posted_at=stub["posted_at"],
                    description=description,
                    scraped_at=datetime.now(timezone.utc).isoformat(),
                    scrub_counts=scrub_counts,
                )
                job.compute_hash()
                all_jobs.append(job)
                if len(all_jobs) >= max_results:
                    break

            log.info(f"Page start={start}: {new_count} new jobs (total: {len(all_jobs)})")
            if new_count == 0:
                break
            start += 25
            self._sleep()

        return all_jobs

# --- Example usage ---------------------------------------------------------
if __name__ == "__main__":
    scraper = LinkedInJobScraper()
    jobs = scraper.scrape(
        keywords="LLM Ops",
        max_results=50,
        time_posted="r86400",   # past 24h
        workplace="2",          # remote
        job_type="F",           # full-time
        experience="2,3,4,5",   # entry through director
    )

    log.info(f"Scraped {len(jobs)} jobs")
    total_scrubbed = sum(j.scrub_counts.get("email", 0) + j.scrub_counts.get("phone", 0) for j in jobs)
    log.info(f"Scrubbed {total_scrubbed} PII items across all postings")

    # Dump to JSONL for inspection
    import json
    with open("linkedin_jobs.jsonl", "w") as f:
        for job in jobs:
            f.write(json.dumps(asdict(job)) + "\n")