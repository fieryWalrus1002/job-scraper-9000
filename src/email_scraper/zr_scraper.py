"""ZR Scraper Module.

Fetches full job details from ZipRecruiter job posting URLs.
Email alerts only include a short snippet and an obfuscated tracking URL;
this module visits each URL to scrape the full job description and posted date
to match the output shape of our other scrapers.

ZR is a Cloudflare-protected Next.js SPA, so we use Playwright with stealth
to bypass bot detection and render the JavaScript.

Strategy:
  1. Try JSON-LD (schema.org/JobPosting) — clean, structured, resilient to UI changes.
     Works on sites that embed it (Indeed, Glassdoor). ZR doesn't, but it's cheap to check.
  2. Fall back to DOM parsing — finds the description div and relative posted date.
"""

import argparse
import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

log = logging.getLogger(__name__)

# Relative-date patterns: "Posted 3 days ago", "Posted 2 hours ago", "Posted today"
_POSTED_AGO_RE = re.compile(
    r"Posted\s+(\d+)\s+(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago"
)
_POSTED_TODAY_RE = re.compile(r"Posted\s+today")


def _parse_posted_date(text: str) -> Optional[str]:
    """Convert a relative posted date string to an ISO 8601 datetime.

    Handles: "Posted 3 days ago", "Posted 2 hours ago", "Posted today".
    Returns None if the text doesn't match a recognized pattern.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    ago_match = _POSTED_AGO_RE.search(text)
    if ago_match:
        value, unit = int(ago_match.group(1)), ago_match.group(2)
        # Normalize singular → plural for timedelta ("day" → "days")
        if not unit.endswith("s"):
            unit = f"{unit}s"
        delta = timedelta(**{unit: value})
        dt = now - delta
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if _POSTED_TODAY_RE.search(text):
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")

    return None


def _extract_from_json_ld(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    """Look for the SEO JSON-LD block (schema.org/JobPosting).

    Returns (description, posted_at) if found, else (None, None).
    This is the clean, resilient approach — works on sites that embed structured data.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue

        # Sometimes it's a list of schemas, sometimes a single dict
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                description = item.get("description")
                posted_at = item.get("datePosted")
                # Strip HTML from JSON-LD description if present
                if description:
                    desc_soup = BeautifulSoup(description, "html.parser")
                    description = desc_soup.get_text("\n", strip=True)
                    # Collapse excessive blank lines
                    while "\n\n\n" in description:
                        description = description.replace("\n\n\n", "\n\n")
                    description = description.strip() or None
                return description, posted_at

    return None, None


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    """Extract the job description from a parsed ZR page via DOM.

    Looks for the job-details-scroll-container, then finds the div with
    'whitespace-pre-line' class which contains the formatted description.
    """
    container = soup.find(attrs={"data-testid": "job-details-scroll-container"})
    if not container:
        return None

    desc_el = container.find("div", class_="whitespace-pre-line")
    if not desc_el:
        return None

    text = desc_el.get_text("\n", strip=True)
    if not text:
        return None

    # Collapse excessive blank lines
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text.strip() or None


def _extract_posted_date(soup: BeautifulSoup) -> Optional[str]:
    """Extract the posted date from a parsed ZR page via DOM.

    Looks for a <p> element containing 'Posted' text inside the job details
    container. Parses relative dates like "Posted 3 days ago" into ISO 8601.
    """
    container = soup.find(attrs={"data-testid": "job-details-scroll-container"})
    if not container:
        return None

    for p in container.find_all("p"):
        text = p.get_text(strip=True)
        if "Posted" in text:
            return _parse_posted_date(text)

    return None


def _parse_html(html: str) -> tuple[Optional[str], Optional[str]]:
    """Parse rendered HTML and extract description + posted date.

    Tries JSON-LD first (structured, resilient), falls back to DOM parsing.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    if title == "Just a moment..." or "challenges.cloudflare.com" in html:
        log.warning(
            "ZipRecruiter returned a Cloudflare challenge page; no job details available"
        )
        return None, None
    if "Error 500--Internal Server Error" in html:
        log.warning("Destination site returned HTTP 500 page; no job details available")
        return None, None

    # 1. Try JSON-LD first — clean, structured, resilient to UI changes
    description, posted_at = _extract_from_json_ld(soup)
    if description:
        return description, posted_at

    # 2. Fallback: DOM parsing
    description = _extract_description(soup)
    posted_at = _extract_posted_date(soup)

    return description, posted_at


def _fetch_with_playwright(url: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch a ZR job page using Playwright and extract description + posted date."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        context.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'
        )

        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            log.info(
                "Loaded URL status=%s final_url=%s title=%r",
                response.status if response else None,
                page.url,
                page.title(),
            )

            # ZR pages often keep analytics / tracking requests open forever, so
            # `networkidle` is the wrong success signal here. Wait only for the
            # specific content we know how to parse, then capture the page HTML.
            try:
                page.wait_for_selector(
                    '[data-testid="job-details-scroll-container"], script[type="application/ld+json"]',
                    timeout=10_000,
                )
            except PlaywrightTimeout:
                log.debug(
                    "Timed out waiting for known ZR selectors on %s; parsing loaded HTML",
                    url,
                )

            rendered_html = page.content()
        except Exception as exc:
            log.warning(
                "Playwright failed before HTML could be captured on %s: %s", url, exc
            )
            return None, None
        finally:
            browser.close()

    return _parse_html(rendered_html)


def fetch_job_details_from_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch a ZR job page and extract the full description and posted date.

    Uses Playwright to bypass Cloudflare bot protection and render the
    React SPA. Tries JSON-LD (schema.org/JobPosting) first, falls back
    to DOM parsing.

    Args:
        url: The ZipRecruiter job posting URL (e.g. from an email alert).

    Returns:
        A tuple of (description, posted_at). Either value may be None if
        the field could not be extracted. On HTTP or network errors, returns
        (None, None).
    """
    try:
        return _fetch_with_playwright(url)
    except Exception as exc:
        log.warning("Failed to fetch ZR job page %s: %s", url, exc)
        return None, None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape one ZipRecruiter job URL.")
    parser.add_argument("url", help="ZipRecruiter job URL to scrape.")
    parser.add_argument(
        "--description-chars",
        type=int,
        default=1000,
        help="Number of description characters to print.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    description, posted_at = fetch_job_details_from_url(args.url)

    print(f"posted_at: {posted_at}")
    print(f"description_found: {bool(description)}")
    if description:
        print("description_preview:")
        print(description[: args.description_chars])
