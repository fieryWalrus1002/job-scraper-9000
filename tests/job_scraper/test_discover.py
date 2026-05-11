"""
Tests for discover.py — probe method and DB persistence.
All HTTP is mocked.
"""
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
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({"lever.co": 200})):
        boards = probe_company("stripe")
    assert "lever" in boards


def test_probe_finds_ashby(tmp_path):
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({"ashbyhq.com": 200})):
        boards = probe_company("mistral")
    assert "ashby" in boards


def test_probe_finds_greenhouse(tmp_path):
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({"greenhouse.io": 200})):
        boards = probe_company("anthropic")
    assert "greenhouse" in boards


def test_probe_finds_multiple_boards():
    with patch("job_scraper.discover.requests.get", side_effect=_mock_get({
        "lever.co": 200, "greenhouse.io": 200
    })):
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
# run — integration (DB persistence)
# ---------------------------------------------------------------------------

def test_run_persists_to_db(tmp_path):
    db_path = tmp_path / "boards.json"
    with patch("job_scraper.discover.discover_probe", return_value={"stripe": ["lever"]}):
        run(["stripe"], db_path=db_path)
    from job_scraper.company_boards import load
    assert load(db_path)["stripe"] == ["lever"]


def test_run_merges_with_existing_db(tmp_path):
    db_path = tmp_path / "boards.json"
    from job_scraper.company_boards import save
    save({"anthropic": ["greenhouse"]}, db_path)
    with patch("job_scraper.discover.discover_probe", return_value={"stripe": ["lever"]}):
        run(["stripe"], db_path=db_path)
    from job_scraper.company_boards import load
    db = load(db_path)
    assert "anthropic" in db
    assert "stripe" in db
