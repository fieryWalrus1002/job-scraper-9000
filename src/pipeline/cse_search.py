"""Google Programmable Search fallback for slug resolution.

Only called when all heuristic candidates miss. Results are verified before
being trusted (verify-before-trust is mandatory per spec §4.2).
"""

from __future__ import annotations

import logging
import os
import re

import requests

from job_scraper.discover import probe_company
from pipeline.resolver import ResolveResult

log = logging.getLogger(__name__)

_CSE_URL = "https://www.googleapis.com/customsearch/v1"

_ATS_DOMAINS = {
    "lever": "jobs.lever.co",
    "ashby": "jobs.ashbyhq.com",
    "greenhouse": "boards.greenhouse.io",
}


def _parse_slug(url: str, board: str) -> str | None:
    """Extract company slug from a CSE result URL.

    lever:      https://jobs.lever.co/<slug>/<job-id>   → first path segment
    ashby:      https://jobs.ashbyhq.com/<slug>/...      → first path segment
    greenhouse: https://boards.greenhouse.io/embed/job_board?for=<slug>&...
                or https://boards.greenhouse.io/<slug>   → first path segment OR ?for=
    """
    domain = _ATS_DOMAINS[board]
    # Try first path segment after the domain
    m = re.search(rf"https?://{re.escape(domain)}/([^/?#]+)", url)
    if m:
        seg = m.group(1)
        if seg not in ("embed",):
            return seg
    # Greenhouse embed URL: ?for=<slug>
    if board == "greenhouse":
        m2 = re.search(r"[?&]for=([^&]+)", url)
        if m2:
            return m2.group(1)
    return None


def cse_search(name: str, timeout: int = 10) -> ResolveResult | None:
    """Query Google CSE for each ATS domain; verify first candidate found.

    Returns a verified ResolveResult or None if CSE is unconfigured,
    returns no results, or the top result fails probe verification.
    """
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cx:
        log.debug("CSE credentials not set — skipping search fallback")
        return None

    for board, domain in _ATS_DOMAINS.items():
        query = f'site:{domain} "{name}"'
        try:
            resp = requests.get(
                _CSE_URL,
                params={"key": api_key, "cx": cx, "q": query, "num": 1},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            log.warning("CSE request failed for %r: %s", name, exc)
            continue

        if resp.status_code != 200:
            log.debug("CSE returned %d for %r on %s", resp.status_code, name, board)
            continue

        items = resp.json().get("items", [])
        if not items:
            log.debug("CSE no results for %r on %s", name, board)
            continue

        top_url = items[0].get("link", "")
        slug = _parse_slug(top_url, board)
        if not slug:
            log.debug("CSE could not parse slug from %r", top_url)
            continue

        # Verify before trusting
        verified_boards = probe_company(slug)
        if board in verified_boards:
            log.info("CSE resolved %r → %s/%s (verified)", name, board, slug)
            return ResolveResult(board=board, slug=slug, status="resolved")

        log.debug("CSE candidate %r failed probe for %s", slug, board)

    return None
