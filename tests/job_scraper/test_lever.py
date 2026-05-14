from unittest.mock import MagicMock, patch

from job_scraper.scrapers.lever import LeverScraper, LeverQuery


def _mock_response(json_data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _sample_api_response(n: int = 2) -> list:
    return [
        {
            "id": f"uuid-{i}",
            "text": f"Engineer {i}",
            "hostedUrl": f"https://jobs.lever.co/acme/uuid-{i}",
            "categories": {
                "location": "Remote",
                "team": "Engineering",
                "commitment": "Full-time",
            },
            "descriptionPlain": f"Plain description for role {i}.",
            "description": f"<p>HTML description for role {i}.</p>",
            "createdAt": 1_700_000_000_000 + i * 1000,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Basic properties
# ---------------------------------------------------------------------------


def test_source_name():
    scraper = LeverScraper(LeverQuery(company="acme"))
    assert scraper.source_name == "lever:acme"


def test_describe():
    scraper = LeverScraper(LeverQuery(company="acme"))
    info = scraper.describe()
    assert info["source"] == "lever:acme"
    assert info["company"] == "acme"


# ---------------------------------------------------------------------------
# scrape()
# ---------------------------------------------------------------------------


def test_scrape_returns_job_postings():
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(3))
    ):
        jobs = scraper.scrape()
    assert len(jobs) == 3
    assert all(j.source == "lever:acme" for j in jobs)


def test_scrape_maps_fields_correctly():
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()
    job = jobs[0]
    assert job.title == "Engineer 0"
    assert job.source_job_id == "uuid-0"
    assert job.source_url == "https://jobs.lever.co/acme/uuid-0"
    assert job.location == "Remote"
    assert job.company == "acme"
    assert job.description == "Plain description for role 0."


def test_scrape_prefers_description_plain_over_html():
    item = _sample_api_response(1)[0]
    item["descriptionPlain"] = "Plain text"
    item["description"] = "<p>HTML</p>"
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(scraper.session, "get", return_value=_mock_response([item])):
        jobs = scraper.scrape()
    assert jobs[0].description == "Plain text"


def test_scrape_falls_back_to_html_description():
    item = _sample_api_response(1)[0]
    del item["descriptionPlain"]
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(scraper.session, "get", return_value=_mock_response([item])):
        jobs = scraper.scrape()
    assert "<p>" in jobs[0].description


def test_scrape_created_at_converted_to_iso():
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()
    assert jobs[0].posted_at is not None
    assert "T" in jobs[0].posted_at


def test_scrape_missing_created_at_is_none():
    item = _sample_api_response(1)[0]
    del item["createdAt"]
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(scraper.session, "get", return_value=_mock_response([item])):
        jobs = scraper.scrape()
    assert jobs[0].posted_at is None


def test_scrape_no_descriptions():
    scraper = LeverScraper(LeverQuery(company="acme", fetch_descriptions=False))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(2))
    ):
        jobs = scraper.scrape()
    assert all(j.description == "" for j in jobs)


def test_scrape_empty_board():
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(scraper.session, "get", return_value=_mock_response([])):
        jobs = scraper.scrape()
    assert jobs == []


def test_scrape_computes_dedup_hash():
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()
    assert jobs[0].dedup_hash != ""


def test_scrape_missing_categories_location_defaults_empty():
    item = _sample_api_response(1)[0]
    item["categories"] = {}
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(scraper.session, "get", return_value=_mock_response([item])):
        jobs = scraper.scrape()
    assert jobs[0].location == ""
