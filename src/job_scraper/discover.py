"""
Company → board discovery.

Probes each ATS API endpoint directly and records 200 responses.
Results are persisted to raw.company_aliases via AliasCache.
"""

import logging
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    import psycopg

log = logging.getLogger(__name__)

# Probe endpoints — same URLs the scrapers use, just checking status codes
_PROBE_URLS = {
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
}


def probe_company(company: str, timeout: int = 10) -> list[str]:
    """Return board types whose API returns 200 for this company slug."""
    found = []
    for board, url_tpl in _PROBE_URLS.items():
        url = url_tpl.format(slug=company)
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                found.append(board)
                log.info("  %s → %s ✓", company, board)
            else:
                log.debug("  %s → %s ✗ (%d)", company, board, resp.status_code)
        except requests.RequestException as exc:
            log.debug("  %s → %s error: %s", company, board, exc)
    return found


def discover_probe(companies: list[str]) -> dict[str, list[str]]:
    """Probe every company against every ATS. Returns {slug: [boards]}."""
    results: dict[str, list[str]] = {}
    for company in companies:
        log.info("Probing %s...", company)
        boards = probe_company(company)
        results[company] = boards
        if not boards:
            log.info("  %s — not found on any board", company)
    return results


def run(
    companies: list[str],
    *,
    conn: "psycopg.Connection | None" = None,
) -> dict[str, list[str]]:
    """Probe companies and (optionally) persist results to raw.company_aliases."""
    discovered = discover_probe(companies)
    if conn is not None:
        from pipeline.alias_cache import AliasCache
        from pipeline.resolver import ResolveResult

        for slug, boards in discovered.items():
            if boards:
                result = ResolveResult(board=boards[0], slug=slug, status="resolved")
                AliasCache.write(conn, slug, result)
    else:
        log.warning("discover.run() called without conn — results not persisted to DB")
    return discovered
