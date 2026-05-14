"""Tests for SELJobScraper."""

import json
from unittest.mock import MagicMock

from job_scraper.query import SELSearchQuery
from job_scraper.scrapers.sel import SELJobScraper


def _make_scraper(**kwargs) -> SELJobScraper:
    return SELJobScraper(SELSearchQuery(**kwargs))


def _mock_session(postings: list[dict]) -> MagicMock:
    """Return a mock session whose first GET returns a Workday state page."""
    state = json.dumps({"jobPostings": postings}).replace('"', "&quot;")
    html = f'<div data-initial-state="{state}"></div>'
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp
    return mock_session


# ---------------------------------------------------------------------------
# source_name and wiring
# ---------------------------------------------------------------------------


def test_source_name():
    assert _make_scraper().source_name == "sel"


def test_scrape_uses_to_url_not_bare_base_url():
    scraper = _make_scraper()
    scraper.session = _mock_session([])
    scraper.scrape()

    actual_url = scraper.session.get.call_args.args[0]
    expected_url = SELSearchQuery().to_url(scraper.base_url)
    assert actual_url == expected_url


def test_scrape_url_contains_location_guid():
    scraper = _make_scraper(location_key="pullman_wa")
    scraper.session = _mock_session([])
    scraper.scrape()

    url = scraper.session.get.call_args.args[0]
    assert "df72ee3ddefc1018ebf01de718624e22" in url  # pullman_wa GUID


# ---------------------------------------------------------------------------
# Parsing job listings
# ---------------------------------------------------------------------------


def test_scrape_returns_empty_on_no_postings():
    scraper = _make_scraper()
    scraper.session = _mock_session([])
    assert scraper.scrape() == []


def test_scrape_returns_one_job_posting(tmp_path):
    posting = {
        "bulletinId": "JR123",
        "externalPath": "/job/Pullman-WA/Engineer_JR123",
        "title": "Software Engineer",
        "location": "Pullman, WA",
        "postedOn": "2026-05-01",
    }
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = _mock_session([posting])

    jobs = scraper.scrape()
    assert len(jobs) == 1
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].company == "SEL"
    assert jobs[0].location == "Pullman, WA"
    assert jobs[0].source == "sel"
    assert jobs[0].source_job_id == "JR123"


def test_scrape_source_url_constructed_from_domain_and_path():
    posting = {
        "bulletinId": "JR999",
        "externalPath": "/job/Pullman-WA/Eng_JR999",
        "title": "Engineer",
        "location": "Pullman, WA",
        "postedOn": None,
    }
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = _mock_session([posting])

    jobs = scraper.scrape()
    assert jobs[0].source_url == "https://selinc.wd1.myworkdayjobs.com/job/Pullman-WA/Eng_JR999"


def test_scrape_computes_dedup_hash():
    posting = {
        "bulletinId": "JR1",
        "externalPath": "/job/Pullman-WA/Eng_JR1",
        "title": "Engineer",
        "location": "Pullman, WA",
        "postedOn": None,
    }
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = _mock_session([posting])

    jobs = scraper.scrape()
    assert jobs[0].dedup_hash != ""


def test_scrape_no_description_fetch_when_disabled():
    posting = {
        "bulletinId": "JR1",
        "externalPath": "/job/Pullman-WA/Eng_JR1",
        "title": "Engineer",
        "location": "Pullman, WA",
        "postedOn": None,
    }
    scraper = _make_scraper(fetch_descriptions=False)
    mock_session = _mock_session([posting])
    scraper.session = mock_session

    scraper.scrape()
    # Only one GET call (the listing page) — no detail fetches
    assert mock_session.get.call_count == 1


def test_scrape_fetches_description_when_enabled():
    posting = {
        "bulletinId": "JR1",
        "externalPath": "/job/Pullman-WA/Eng_JR1",
        "title": "Engineer",
        "location": "Pullman, WA",
        "postedOn": None,
    }
    scraper = _make_scraper(fetch_descriptions=True)
    mock_session = _mock_session([posting])
    # Second GET (detail API) returns a description
    detail_resp = MagicMock()
    detail_resp.status_code = 200
    detail_resp.json.return_value = {"jobDescription": "<p>Great job</p>"}
    mock_session.get.side_effect = [mock_session.get.return_value, detail_resp]
    scraper.session = mock_session

    jobs = scraper.scrape()
    assert mock_session.get.call_count == 2
    assert "Great job" in jobs[0].description


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_json_parses_html_encoded_state():
    scraper = _make_scraper()
    html = '<div data-initial-state="{&quot;jobPostings&quot;: []}"></div>'
    result = scraper._extract_json(html)
    assert result == {"jobPostings": []}


def test_extract_json_returns_empty_dict_on_missing_attribute():
    scraper = _make_scraper()
    assert scraper._extract_json("<html>no state here</html>") == {}


def test_extract_json_returns_empty_dict_on_malformed_json():
    scraper = _make_scraper()
    html = '<div data-initial-state="{bad json"></div>'
    assert scraper._extract_json(html) == {}
