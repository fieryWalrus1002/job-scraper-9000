"""
Company → board discovery.

Probes each ATS API endpoint directly and records 200 responses.
Results are written to company_boards.json.
"""
import logging

import requests

from .company_boards import DEFAULT_PATH, load, merge, save

log = logging.getLogger(__name__)

# Probe endpoints — same URLs the scrapers use, just checking status codes
_PROBE_URLS = {
    "lever":      "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{slug}",
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
    db_path=DEFAULT_PATH,
) -> dict[str, list[str]]:
    """Probe companies and persist results to company_boards.json."""
    discovered = discover_probe(companies)
    db = load(db_path)
    updated = merge(db, discovered)
    save(updated, db_path)
    log.info("Updated %s — %d companies total", db_path, len(updated))
    return discovered
