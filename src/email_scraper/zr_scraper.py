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
import base64
import binascii
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

log = logging.getLogger(__name__)

# Enrichment outcomes recorded on each JobPosting. Constrained set (not free
# text) because downstream branches on it — keep it small and meaningful.
ENRICHED = "enriched"  # reached a ZR page and got a description and/or posted_at
EXTERNAL_ATS = "external_ats"  # /ekm/ link hands off to an employer ATS; not scraped
EXPIRED = "expired"  # the email tracking token's `expires` is already in the past
UNENRICHED = "unenriched"  # ZR page reached but yielded nothing (Cloudflare/500/empty)

EnrichmentStatus = Literal["enriched", "external_ats", "expired", "unenriched"]

# Cloudflare piggyback. This whole module is local-only personal tooling (it
# touches a personal inbox and never goes to the cloud), so reusing a real Chrome
# profile is a first-class option, not a hack to apologize for. Headless requests
# face the "Just a moment..." challenge cold every run; a real browser sails
# through on the cf_clearance cookie it already earned by browsing ZR. Pointing
# Playwright at a real Chrome user-data-dir reuses that cookie + fingerprint and
# piggybacks on a session you've already cleared.
#
# It's opt-in via env (not the default) only so the headless path still works
# with no profile configured and the tests stay hermetic — not because there's
# anything wrong with making it your normal way to run this.
#
#   ZR_SCRAPER_PROFILE_DIR  — path to a Chrome user-data-dir (Chrome must be
#                             closed, or point at a copy/dedicated profile).
#   ZR_SCRAPER_HEADLESS     — set truthy to force headless even with a profile;
#                             default is headful when a profile is set, since
#                             headless is the easiest tell for Cloudflare.
_PROFILE_DIR_ENV = "ZR_SCRAPER_PROFILE_DIR"
_HEADLESS_ENV = "ZR_SCRAPER_HEADLESS"


def _profile_settings() -> tuple[Optional[str], bool]:
    """Resolve (profile_dir, headless) from the environment.

    Default (no profile configured) is the throwaway-context headless path.
    """
    profile_dir = os.environ.get(_PROFILE_DIR_ENV) or None
    if not profile_dir:
        return None, True
    headless = os.environ.get(_HEADLESS_ENV, "").strip().lower() in ("1", "true", "yes")
    return profile_dir, headless


# Relative-date patterns: "Posted 3 days ago", "Posted 2 hours ago", "Posted today"
_POSTED_AGO_RE = re.compile(
    r"Posted\s+(\d+)\s+(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago"
)
_POSTED_TODAY_RE = re.compile(r"Posted\s+today")


def _date_only(value: Optional[str]) -> Optional[str]:
    """Normalize an ISO date/datetime string to a ``YYYY-MM-DD`` date.

    The pipeline's `posted_at` is a *date* (`ScoredJobPosting.posted_at: date`),
    matching every other scraper — a datetime with a time component fails strict
    validation. Truncating to the date portion keeps us on contract.
    """
    if not value:
        return None
    return value[:10]


def _parse_posted_date(text: str) -> Optional[str]:
    """Convert a relative posted date string to a ``YYYY-MM-DD`` date.

    Handles: "Posted 3 days ago", "Posted 2 hours ago", "Posted today".
    Returns None if the text doesn't match a recognized pattern. Date-only by
    contract (see :func:`_date_only`).
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
        return (now - delta).strftime("%Y-%m-%d")

    if _POSTED_TODAY_RE.search(text):
        return now.strftime("%Y-%m-%d")

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
                # datePosted may be a date or a full datetime; the contract is a date.
                posted_at = _date_only(item.get("datePosted"))
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


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]


def _fetch_with_playwright(
    url: str,
    profile_dir: Optional[str] = None,
    headless: bool = True,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch a ZR job page using Playwright; return (description, posted_at, final_url).

    ``final_url`` is the post-redirect URL (the `/jobs/v2/` page), which carries
    the stable `listing_key` even when the page itself is Cloudflare-blocked.

    When ``profile_dir`` is set, launches a persistent context backed by that
    real Chrome profile (reusing its cookies/fingerprint) instead of a throwaway
    headless context — the local-only Cloudflare piggyback. See ``_profile_settings``.
    """
    with sync_playwright() as p:
        if profile_dir:
            # Persistent context owns its own browser; there's no separate
            # browser handle to close, and add_init_script lives on the context.
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=headless,
                args=_LAUNCH_ARGS,
                viewport={"width": 1920, "height": 1080},
                user_agent=_USER_AGENT,
                locale="en-US",
            )
            browser = None
        else:
            browser = p.chromium.launch(headless=headless, args=_LAUNCH_ARGS)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=_USER_AGENT,
                locale="en-US",
            )
        context.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'
        )

        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # /km/ email links land on a "Redirecting..." shim that JS-navigates
            # to the real /jobs/v2/ page. Wait for that hop first; otherwise we
            # parse the shim and either miss the content or mislabel the failure.
            try:
                page.wait_for_url(lambda u: "/km/" not in u, timeout=10_000)
            except PlaywrightTimeout:
                log.debug("No redirect off the /km/ shim within timeout on %s", url)

            # Captured/logged after the redirect so final_url reflects where we
            # actually landed (the /jobs/v2/ page), not the shim.
            final_url = page.url
            log.info(
                "Loaded URL status=%s final_url=%s title=%r",
                response.status if response else None,
                final_url,
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
            return None, None, None
        finally:
            context.close()
            if browser is not None:
                browser.close()

    description, posted_at = _parse_html(rendered_html)
    return description, posted_at, final_url


def _fetch_guarded(
    url: str,
    profile_dir: Optional[str] = None,
    headless: bool = True,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """``_fetch_with_playwright`` with the launch-level error guard. 3-tuple."""
    try:
        return _fetch_with_playwright(url, profile_dir=profile_dir, headless=headless)
    except Exception as exc:
        log.warning("Failed to fetch ZR job page %s: %s", url, exc)
        return None, None, None


def fetch_job_details_from_url(
    url: str,
    profile_dir: Optional[str] = None,
    headless: bool = True,
) -> tuple[Optional[str], Optional[str]]:
    """Fetch a ZR job page and extract the full description and posted date.

    Uses Playwright to render the React SPA. Tries JSON-LD
    (schema.org/JobPosting) first, falls back to DOM parsing.

    Args:
        url: The ZipRecruiter job posting URL (e.g. from an email alert).
        profile_dir: Optional Chrome user-data-dir for the persistent-context
            Cloudflare piggyback (local-only). None = throwaway headless context.
        headless: Whether to run headless. Ignored-in-spirit for the profile
            path, where headful is usually required to pass Cloudflare.

    Returns:
        A tuple of (description, posted_at). Either value may be None if
        the field could not be extracted. On HTTP or network errors, returns
        (None, None). (For the stable listing id too, use ``enrich_job_url``.)
    """
    description, posted_at, _ = _fetch_guarded(
        url, profile_dir=profile_dir, headless=headless
    )
    return description, posted_at


def _extract_listing_key(final_url: Optional[str]) -> Optional[str]:
    """Decode the stable ZipRecruiter listing id from a resolved ``/jobs/v2/`` URL.

    The email tracking token rotates every send, but a `/km/` link redirects to
    ``/jobs/v2/<base64>`` whose payload is ``{"listing_key": ...}`` — stable per
    listing. Using it as ``source_job_id`` makes ``dedup_hash`` stable across
    sends. Returns None for non-`/jobs/v2/` URLs or anything that won't decode.
    """
    if not final_url or "/jobs/v2/" not in final_url:
        return None
    segment = urlparse(final_url).path.rstrip("/").split("/")[-1]
    padded = segment + "=" * (-len(segment) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            data = json.loads(decoder(padded))
        except (ValueError, binascii.Error):
            continue
        if isinstance(data, dict) and data.get("listing_key"):
            return data["listing_key"]
        # Decoded cleanly but no listing_key — the whole dedup story rides on
        # this, so surface a shape change loudly rather than silently losing it.
        log.warning(
            "Decoded /jobs/v2 payload but found no listing_key (ZR shape change?): %s",
            final_url,
        )
        return None
    return None


def classify_zr_url(url: str) -> tuple[Literal["external", "ziprecruiter"], bool]:
    """Classify an email tracking URL *before* spending any network/browser cost.

    ZR email alerts use two link shapes:
      - ``/ekm/...`` — an "external" hand-off that redirects out to the employer's
        own ATS (Oracle, Workday, ...). We don't scrape those; per-ATS parsers are
        a maintenance treadmill, so these stay email-only by policy.
      - ``/km/...`` (and any other ZR path) — a ZR-hosted detail page, the only
        kind worth rendering.

    The ``/km/`` links also carry an ``expires`` query param (a unix timestamp);
    once that passes, the link is dead and there's nothing to fetch.

    Returns ``(kind, expired)``.
    """
    parsed = urlparse(url)

    expired = False
    expires = parse_qs(parsed.query).get("expires", [None])[0]
    if expires:
        try:
            expired = int(expires) < int(datetime.now(timezone.utc).timestamp())
        except ValueError:
            # A non-numeric expires we don't understand — treat as live rather
            # than silently skipping a fetch we could have made.
            expired = False

    kind = "external" if "/ekm/" in parsed.path else "ziprecruiter"
    return kind, expired


def enrich_job_url(
    url: str,
) -> tuple[Optional[str], Optional[str], str, Optional[str]]:
    """Resolve a tracking URL to ``(description, posted_at, status, listing_key)``.

    This is the router the email parser calls. It classifies the URL up front so
    we only ever launch Playwright for ZR-hosted pages we can actually parse —
    ``/ekm/`` external hand-offs and expired links short-circuit with no fetch.

    ``status`` records why a description is missing (legible, not a silent None).
    ``listing_key`` is the stable per-listing id decoded from the resolved
    ``/jobs/v2/`` URL (None for non-`/km/` or unresolved pages) — the parser uses
    it as ``source_job_id`` so ``dedup_hash`` survives the rotating tracking token.
    """
    kind, expired = classify_zr_url(url)

    if expired:
        log.info("ZR tracking link expired; skipping enrichment: %s", url)
        return None, None, EXPIRED, None

    if kind == "external":
        log.info("External-ATS (/ekm/) link; email-only by policy: %s", url)
        return None, None, EXTERNAL_ATS, None

    profile_dir, headless = _profile_settings()
    description, posted_at, final_url = _fetch_guarded(
        url, profile_dir=profile_dir, headless=headless
    )
    status = ENRICHED if (description or posted_at) else UNENRICHED
    return description, posted_at, status, _extract_listing_key(final_url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape one ZipRecruiter job URL.")
    parser.add_argument("url", help="ZipRecruiter job URL to scrape.")
    parser.add_argument(
        "--description-chars",
        type=int,
        default=1000,
        help="Number of description characters to print.",
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help=(
            "Chrome user-data-dir to reuse a real session's cookies (Cloudflare "
            f"piggyback). Overrides ${_PROFILE_DIR_ENV}. Chrome must be closed."
        ),
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Force a visible browser (recommended with --profile-dir for Cloudflare).",
    )
    args = parser.parse_args()

    # Bridge CLI flags to the same env the pipeline path reads, so there's one
    # resolution path. --headful wins; otherwise a profile defaults to headful.
    if args.profile_dir:
        os.environ[_PROFILE_DIR_ENV] = args.profile_dir
    if args.headful:
        os.environ[_HEADLESS_ENV] = "0"

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    description, posted_at, status, listing_key = enrich_job_url(args.url)

    print(f"enrichment_status: {status}")
    print(f"listing_key: {listing_key}")
    print(f"posted_at: {posted_at}")
    print(f"description_found: {bool(description)}")
    if description:
        print("description_preview:")
        print(description[: args.description_chars])
