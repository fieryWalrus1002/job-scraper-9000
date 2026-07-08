"""
Tests for discover.py — probe method and DB persistence.
All HTTP is mocked.
"""

import logging
from unittest.mock import MagicMock, patch

import requests

from job_scraper.discover import probe_company, discover_probe, run


# ---------------------------------------------------------------------------
# probe_company
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


def test_probe_finds_lever(tmp_path):
    with patch(
        "job_scraper.discover.requests.get", side_effect=_mock_get({"lever.co": 200})
    ):
        boards = probe_company("stripe")
    assert "lever" in boards


def test_probe_finds_ashby(tmp_path):
    with patch(
        "job_scraper.discover.requests.get", side_effect=_mock_get({"ashbyhq.com": 200})
    ):
        boards = probe_company("mistral")
    assert "ashby" in boards


def test_probe_finds_greenhouse(tmp_path):
    with patch(
        "job_scraper.discover.requests.get",
        side_effect=_mock_get({"greenhouse.io": 200}),
    ):
        boards = probe_company("anthropic")
    assert "greenhouse" in boards


def test_probe_finds_multiple_boards():
    with patch(
        "job_scraper.discover.requests.get",
        side_effect=_mock_get({"lever.co": 200, "greenhouse.io": 200}),
    ):
        boards = probe_company("stripe")
    assert set(boards) == {"lever", "greenhouse"}


def test_probe_returns_empty_when_not_found():
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({})):
        boards = probe_company("nobody")
    assert boards == []


def test_probe_swallows_request_exceptions():
    def _raise(url, timeout=10):
        raise requests.RequestException("timeout")

    with patch("job_scraper.discover.requests.get", side_effect=_raise):
        boards = probe_company("stripe")
    assert boards == []


# ---------------------------------------------------------------------------
# discover_probe
# ---------------------------------------------------------------------------


def test_discover_probe_returns_mapping():
    with patch("job_scraper.discover.probe_company", side_effect=lambda c: ["ashby"]):
        result = discover_probe(["mistral", "cohere"])
    assert result == {"mistral": ["ashby"], "cohere": ["ashby"]}


# ---------------------------------------------------------------------------
# run — DB persistence via AliasCache
# ---------------------------------------------------------------------------


def test_run_with_conn_writes_to_alias_cache():
    """When conn is provided and probe finds boards, AliasCache.write is called."""
    from pipeline.resolver import ResolveResult

    mock_conn = MagicMock()
    with (
        patch(
            "job_scraper.discover.discover_probe",
            return_value={"stripe": ["lever"]},
        ),
        patch("pipeline.alias_cache.AliasCache.write") as mock_write,
    ):
        result = run(["stripe"], conn=mock_conn)

    assert result == {"stripe": ["lever"]}
    mock_write.assert_called_once_with(
        mock_conn,
        "stripe",
        ResolveResult(board="lever", slug="stripe", status="resolved"),
    )


def test_run_without_conn_logs_warning(caplog):
    """When conn=None, a warning is logged and results are still returned."""
    with (
        patch(
            "job_scraper.discover.discover_probe",
            return_value={"stripe": ["lever"]},
        ),
        caplog.at_level(logging.WARNING, logger="job_scraper.discover"),
    ):
        result = run(["stripe"], conn=None)

    assert result == {"stripe": ["lever"]}
    assert any("not persisted" in r.message for r in caplog.records)


def test_run_with_conn_skips_write_for_empty_probe():
    """Companies with no boards found do not trigger AliasCache.write."""
    mock_conn = MagicMock()
    with (
        patch(
            "job_scraper.discover.discover_probe",
            return_value={"nobody": []},
        ),
        patch("pipeline.alias_cache.AliasCache.write") as mock_write,
    ):
        result = run(["nobody"], conn=mock_conn)

    assert result == {"nobody": []}
    mock_write.assert_not_called()
