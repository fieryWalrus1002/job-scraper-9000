"""Tests for pipeline.resolver — heuristic candidates + probe.

All HTTP is mocked. No network calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.resolver import (
    RESOLVER_VERSION,
    ResolveResult,
    heuristic_candidates,
    normalize,
    resolve,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_get(status_map: dict):
    """Return a mock requests.get that returns status codes by URL prefix."""

    def _get(url, timeout=10):
        resp = MagicMock()
        for prefix, code in status_map.items():
            if prefix in url:
                resp.status_code = code
                return resp
        resp.status_code = 404
        return resp

    return _get


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize():
    assert normalize("  Foo Bar  ") == "foo bar"
    assert normalize("ABC") == "abc"
    assert normalize("x") == "x"


# ---------------------------------------------------------------------------
# heuristic_candidates
# ---------------------------------------------------------------------------


def test_heuristic_candidates_commonwealth_fusion_systems():
    candidates = heuristic_candidates("commonwealth fusion systems")
    # Rule 1: squash full name
    assert candidates[0] == "commonwealthfusionsystems"
    # Rule 2: drop trailing filler ("systems"), squash
    assert candidates[1] == "commonwealthfusion"
    # Rule 3: first significant word ("systems" is filler)
    assert candidates[2] == "commonwealth"
    # Rule 4: acronym of significant words only ("systems" dropped → cf)
    assert candidates[3] == "cf"
    # Deduped, no duplicates
    assert len(candidates) == len(set(candidates))


def test_heuristic_candidates_single_word():
    candidates = heuristic_candidates("momentus")
    # Rule 1: squash, Rule 2: same (no filler), Rule 3: first sig word = same (deduped),
    # Rule 4: acronym of single word = "m"
    assert candidates == ["momentus", "m"]


def test_heuristic_candidates_two_words():
    candidates = heuristic_candidates("blue origin")
    assert candidates[0] == "blueorigin"
    assert candidates[1] == "blue"
    assert candidates[2] == "bo"


def test_heuristic_candidates_filler_only():
    # All filler words → empty significant words, only squash survives
    candidates = heuristic_candidates("inc corp llc")
    assert candidates == ["inccorpllc"]


# ---------------------------------------------------------------------------
# resolve — golden fixture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected_board,expected_slug",
    [
        (
            "relativity space",
            "greenhouse",
            "relativityspace",
        ),  # Rule 1 squash hits first
        ("rocket lab", None, "rocketlab"),  # any board
        ("momentus", None, "momentus"),  # any board
        ("spacex", "greenhouse", "spacex"),
        ("blue origin", "lever", "blueorigin"),
    ],
)
def test_resolve_golden_fixture_resolved(name, expected_board, expected_slug):
    """Test the 5 golden pairs reachable by heuristics."""
    # Determine which board domain to mock based on expected board
    if expected_board == "greenhouse":
        board_domain = "greenhouse.io"
        expected_board_actual = "greenhouse"
    elif expected_board == "lever":
        board_domain = "lever.co"
        expected_board_actual = "lever"
    elif expected_board == "ashby":
        board_domain = "ashbyhq.com"
        expected_board_actual = "ashby"
    else:
        # "any board" — pick lever as the mock target
        board_domain = "lever.co"
        expected_board_actual = "lever"

    with patch(
        "job_scraper.discover.requests.get", side_effect=_mock_get({board_domain: 200})
    ):
        result = resolve(name)

    assert result.status == "resolved"
    assert result.slug == expected_slug
    assert result.board == expected_board_actual


@pytest.mark.parametrize(
    "name,expected_board,expected_slug",
    [
        ("commonwealth fusion systems", "lever", "cfsenergy"),
        ("avalanche energy", "ashby", "avalanchefusion"),
    ],
)
def test_resolve_golden_fixture_unresolved(name, expected_board, expected_slug):
    """cfsenergy/avalanchefusion require search fallback (slice #454);
    heuristic correctly misses them."""
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({})):
        result = resolve(name)

    assert result.status == "unresolved"
    assert result.slug is None
    assert result.board is None


# ---------------------------------------------------------------------------
# resolve — negative / edge cases
# ---------------------------------------------------------------------------


def test_resolve_negative():
    """'boeing' has no ATS board → unresolved."""
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({})):
        result = resolve("boeing")
    assert result.status == "unresolved"
    assert result.slug is None
    assert result.board is None


def test_resolve_needs_review():
    """Candidate returns 2 boards → needs_review."""
    with patch(
        "job_scraper.discover.requests.get",
        side_effect=_mock_get({"lever.co": 200, "greenhouse.io": 200}),
    ):
        result = resolve("stripe")
    assert result.status == "needs_review"
    assert result.slug is not None
    assert result.board is None


def test_resolve_stops_at_first_hit():
    """resolve() returns on the first candidate that hits, doesn't try further."""
    probed_slugs: list[str] = []

    def _probe_side_effect(company: str, timeout: int = 10) -> list[str]:
        probed_slugs.append(company)
        # First candidate (blueorigin) → 404 everywhere
        if company == "blueorigin":
            return []
        # Second candidate (blue) → hits lever
        return ["lever"]

    with patch("pipeline.resolver.probe_company", side_effect=_probe_side_effect):
        result = resolve("blue origin")

    assert result.status == "resolved"
    assert result.slug == "blue"
    assert result.board == "lever"
    # Probed blueorigin (miss), then blue (hit), stopped there
    assert probed_slugs == ["blueorigin", "blue"]


# ---------------------------------------------------------------------------
# ResolveResult dataclass
# ---------------------------------------------------------------------------


def test_resolve_result_dataclass():
    r = ResolveResult(board="lever", slug="stripe", status="resolved")
    assert r.board == "lever"
    assert r.slug == "stripe"
    assert r.status == "resolved"


def test_resolver_version():
    assert RESOLVER_VERSION == "v1"
