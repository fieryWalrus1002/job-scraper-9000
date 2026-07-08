"""Name → ATS slug resolution: heuristic candidates + probe.

This module is stateless — no DB reads or writes. The cache layer (#453)
wraps it.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

from job_scraper.discover import probe_company

log = logging.getLogger(__name__)

RESOLVER_VERSION = "v1"

_FILLER_WORDS = frozenset(
    {
        "systems",
        "technologies",
        "technology",
        "inc",
        "corp",
        "corporation",
        "llc",
        "co",
        "company",
        "group",
        "labs",
        "laboratories",
        "aviation",
        "space",
        "energy",
    }
)


@dataclass
class ResolveResult:
    board: str | None
    slug: str | None
    status: str  # 'resolved' | 'unresolved' | 'needs_review'


def normalize(name: str) -> str:
    """Canonical form for dedup/cache lookup: lowercase, strip leading/trailing space."""
    return name.strip().lower()


def _squash(s: str) -> str:
    """Lowercase + strip all non-alphanumeric."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _significant_words(name: str) -> list[str]:
    """Split on whitespace/punctuation, drop filler words."""
    words = re.split(r"[\s/,&.]+", name.lower())
    return [w for w in words if w and w not in _FILLER_WORDS]


def heuristic_candidates(name: str) -> list[str]:
    """Generate slug candidates from a human company name, spec §4.2 rule set.

    Order matters: cheap common-case rules first, so first-200-wins stops early.
    Returns deduplicated list preserving order.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(c: str) -> None:
        if c and c not in seen:
            candidates.append(c)
            seen.add(c)

    # Rule 1: squash full name
    _add(_squash(name))

    # Rule 2: drop trailing filler word(s), then squash
    words = re.split(r"[\s/,&.]+", name.lower())
    trimmed = words[:]
    while trimmed and trimmed[-1] in _FILLER_WORDS:
        trimmed.pop()
    if trimmed:
        _add(_squash(" ".join(trimmed)))

    # Rule 3: first significant word
    sig = _significant_words(name)
    if sig:
        _add(_squash(sig[0]))

    # Rule 4: acronym — first letter of each significant word
    if sig:
        _add("".join(w[0] for w in sig))

    return candidates


def resolve(name: str) -> ResolveResult:
    """Try heuristic candidates against ATS probes. Return first 200 hit.

    Returns ResolveResult with status='unresolved' if nothing hits.
    The search-fallback path (#454) is called by the cache layer on miss.
    """
    candidates = heuristic_candidates(name)
    log.debug("resolve(%r): candidates=%s", name, candidates)

    for candidate in candidates:
        boards = probe_company(candidate)
        if len(boards) == 1:
            log.info("resolve(%r): %r → %s/%s", name, candidate, boards[0], candidate)
            return ResolveResult(board=boards[0], slug=candidate, status="resolved")
        if len(boards) > 1:
            # Multiple boards for one candidate slug = ambiguous; flag it.
            log.warning(
                "resolve(%r): candidate %r returned multiple boards %s — needs_review",
                name,
                candidate,
                boards,
            )
            return ResolveResult(board=None, slug=candidate, status="needs_review")

    log.info("resolve(%r): no candidate hit any ATS board", name)
    return ResolveResult(board=None, slug=None, status="unresolved")
