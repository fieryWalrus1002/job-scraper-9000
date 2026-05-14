from unittest.mock import MagicMock, patch

from job_scraper.scrapers.ashby import AshbyScraper, AshbyQuery


def _mock_response(json_data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _sample_api_response(n: int = 2) -> dict:
    return {
        "jobs": [
            {
                "id": f"uuid-{i}",
                "title": f"Engineer {i}",
                "jobUrl": f"https://jobs.ashbyhq.com/acme/uuid-{i}",
                "location": "Remote",
                "publishedAt": "2024-01-15T00:00:00.000Z",
                "descriptionPlain": f"Plain description for role {i}.",
                "descriptionHtml": f"<p>HTML description for role {i}.</p>",
            }
            for i in range(n)
        ]
    }


# ---------------------------------------------------------------------------
# Basic properties
# ---------------------------------------------------------------------------


def test_source_name():
    assert AshbyScraper(AshbyQuery(company="acme")).source_name == "ashby:acme"


def test_describe():
    info = AshbyScraper(AshbyQuery(company="acme")).describe()
    assert info["source"] == "ashby:acme"
    assert info["company"] == "acme"


# ---------------------------------------------------------------------------
# scrape()
# ---------------------------------------------------------------------------


def test_scrape_returns_job_postings():
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(3))
    ):
        jobs = scraper.scrape()
    assert len(jobs) == 3
    assert all(j.source == "ashby:acme" for j in jobs)


def test_scrape_maps_fields_correctly():
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()
    job = jobs[0]
    assert job.title == "Engineer 0"
    assert job.source_job_id == "uuid-0"
    assert job.source_url == "https://jobs.ashbyhq.com/acme/uuid-0"
    assert job.location == "Remote"
    assert job.company == "acme"
    assert job.description == "Plain description for role 0."
    assert job.posted_at == "2024-01-15T00:00:00.000Z"


def test_scrape_prefers_description_plain_over_html():
    item = _sample_api_response(1)["jobs"][0]
    item["descriptionPlain"] = "Plain text"
    item["descriptionHtml"] = "<p>HTML</p>"
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response({"jobs": [item]})
    ):
        jobs = scraper.scrape()
    assert jobs[0].description == "Plain text"


def test_scrape_falls_back_to_html_description():
    item = _sample_api_response(1)["jobs"][0]
    del item["descriptionPlain"]
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response({"jobs": [item]})
    ):
        jobs = scraper.scrape()
    assert "<p>" in jobs[0].description


def test_scrape_no_descriptions():
    scraper = AshbyScraper(AshbyQuery(company="acme", fetch_descriptions=False))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(2))
    ):
        jobs = scraper.scrape()
    assert all(j.description == "" for j in jobs)


def test_scrape_empty_board():
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response({"jobs": []})
    ):
        jobs = scraper.scrape()
    assert jobs == []


def test_scrape_computes_dedup_hash():
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()
    assert jobs[0].dedup_hash != ""


def test_scrape_missing_location_defaults_empty():
    item = _sample_api_response(1)["jobs"][0]
    del item["location"]
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session, "get", return_value=_mock_response({"jobs": [item]})
    ):
        jobs = scraper.scrape()
    assert jobs[0].location == ""
