"""Tests for pipeline.cse_search — Google CSE fallback.

All HTTP is mocked. No real CSE calls, no docker needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pipeline.cse_search import _parse_slug, cse_search
from pipeline.resolver import ResolveResult, resolve


# ---------------------------------------------------------------------------
# _parse_slug
# ---------------------------------------------------------------------------


def test_parse_slug_lever():
    url = "https://jobs.lever.co/cfsenergy/some-job-uuid"
    assert _parse_slug(url, "lever") == "cfsenergy"


def test_parse_slug_ashby():
    url = "https://jobs.ashbyhq.com/avalanchefusion/some-path"
    assert _parse_slug(url, "ashby") == "avalanchefusion"


def test_parse_slug_greenhouse_direct():
    url = "https://boards.greenhouse.io/stripe"
    assert _parse_slug(url, "greenhouse") == "stripe"


def test_parse_slug_greenhouse_embed_for():
    url = "https://boards.greenhouse.io/embed/job_board?for=stripe&edition=joined"
    assert _parse_slug(url, "greenhouse") == "stripe"


def test_parse_slug_greenhouse_embed_skipped():
    """'embed' segment is skipped; falls through to ?for= parsing."""
    url = "https://boards.greenhouse.io/embed/job_board"
    # No ?for= param → None
    assert _parse_slug(url, "greenhouse") is None


def test_parse_slug_unknown_domain():
    url = "https://example.com/foo/bar"
    assert _parse_slug(url, "lever") is None


# ---------------------------------------------------------------------------
# cse_search — unconfigured
# ---------------------------------------------------------------------------


def test_cse_returns_none_when_unconfigured():
    with patch.dict("pipeline.cse_search.os.environ", {}, clear=True):
        result = cse_search("acme")
    assert result is None


# ---------------------------------------------------------------------------
# cse_search — lever resolution
# ---------------------------------------------------------------------------


def test_cse_queries_and_parses_lever_url():
    cse_response = MagicMock()
    cse_response.status_code = 200
    cse_response.json.return_value = {
        "items": [{"link": "https://jobs.lever.co/cfsenergy/abc-uuid"}]
    }

    with patch.dict(
        "os.environ", {"GOOGLE_CSE_API_KEY": "fake", "GOOGLE_CSE_ID": "fake"}
    ):
        with patch("pipeline.cse_search.requests.get", return_value=cse_response):
            with patch("pipeline.cse_search.probe_company", return_value=["lever"]):
                result = cse_search("commonwealth fusion systems")

    assert result is not None
    assert result.status == "resolved"
    assert result.board == "lever"
    assert result.slug == "cfsenergy"


# ---------------------------------------------------------------------------
# cse_search — ashby resolution
# ---------------------------------------------------------------------------


def test_cse_queries_and_parses_ashby_url():
    cse_response = MagicMock()
    cse_response.status_code = 200
    cse_response.json.return_value = {
        "items": [{"link": "https://jobs.ashbyhq.com/avalanchefusion/abc"}]
    }

    # Make lever return no results so it falls through to ashby
    def _get_side_effect(url, **kwargs):
        resp = MagicMock()
        if "lever" in url:
            resp.status_code = 200
            resp.json.return_value = {"items": []}
            return resp
        # ashby
        resp.status_code = 200
        resp.json.return_value = {
            "items": [{"link": "https://jobs.ashbyhq.com/avalanchefusion/abc"}]
        }
        return resp

    with patch.dict(
        "os.environ", {"GOOGLE_CSE_API_KEY": "fake", "GOOGLE_CSE_ID": "fake"}
    ):
        with patch("pipeline.cse_search.requests.get", side_effect=_get_side_effect):
            with patch("pipeline.cse_search.probe_company", return_value=["ashby"]):
                result = cse_search("avalanche energy")

    assert result is not None
    assert result.status == "resolved"
    assert result.board == "ashby"
    assert result.slug == "avalanchefusion"


# ---------------------------------------------------------------------------
# cse_search — verify before trust
# ---------------------------------------------------------------------------


def test_cse_verifies_before_trusting():
    cse_response = MagicMock()
    cse_response.status_code = 200
    cse_response.json.return_value = {
        "items": [{"link": "https://jobs.lever.co/fakeslug/abc"}]
    }

    with patch.dict(
        "os.environ", {"GOOGLE_CSE_API_KEY": "fake", "GOOGLE_CSE_ID": "fake"}
    ):
        with patch("pipeline.cse_search.requests.get", return_value=cse_response):
            with patch("pipeline.cse_search.probe_company", return_value=[]):
                result = cse_search("some company")

    # probe returned [] → slug not verified → None
    assert result is None


# ---------------------------------------------------------------------------
# cse_search — no results from CSE
# ---------------------------------------------------------------------------


def test_cse_handles_no_results():
    cse_response = MagicMock()
    cse_response.status_code = 200
    cse_response.json.return_value = {"items": []}

    with patch.dict(
        "os.environ", {"GOOGLE_CSE_API_KEY": "fake", "GOOGLE_CSE_ID": "fake"}
    ):
        with patch("pipeline.cse_search.requests.get", return_value=cse_response):
            result = cse_search("ghost corp")

    assert result is None


# ---------------------------------------------------------------------------
# cse_search — request exception
# ---------------------------------------------------------------------------


def test_cse_handles_request_exception():
    import requests as requests_mod

    with patch.dict(
        "os.environ", {"GOOGLE_CSE_API_KEY": "fake", "GOOGLE_CSE_ID": "fake"}
    ):
        with patch(
            "pipeline.cse_search.requests.get",
            side_effect=requests_mod.RequestException("connection refused"),
        ):
            result = cse_search("some company")

    assert result is None


# ---------------------------------------------------------------------------
# resolve — uses search_fn on heuristic miss
# ---------------------------------------------------------------------------


def test_resolver_uses_search_fn_on_heuristic_miss():
    expected = ResolveResult(board="lever", slug="cfsenergy", status="resolved")

    def fake_search(name: str) -> ResolveResult | None:
        return expected

    with patch("pipeline.resolver.probe_company", return_value=[]):
        result = resolve("commonwealth fusion systems", search_fn=fake_search)

    assert result == expected


def test_resolver_without_search_fn_returns_unresolved():
    """Backward compat: resolve() without search_fn still returns unresolved."""
    with patch("pipeline.resolver.probe_company", return_value=[]):
        result = resolve("commonwealth fusion systems")

    assert result.status == "unresolved"
    assert result.slug is None
    assert result.board is None
