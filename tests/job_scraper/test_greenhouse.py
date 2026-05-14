from unittest.mock import MagicMock, patch
from job_scraper.scrapers.greenhouse import GreenhouseScraper, GreenhouseQuery


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _sample_api_response(n: int = 2) -> dict:
    return {
        "jobs": [
            {
                "id": 1000 + i,
                "title": f"Engineer {i}",
                "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{1000 + i}",
                "location": {"name": "Remote"},
                "updated_at": "2024-01-15T00:00:00Z",
                "content": f"Job description for role {i}.",
            }
            for i in range(n)
        ]
    }


def test_source_name():
    scraper = GreenhouseScraper(GreenhouseQuery(board_token="acme"))
    assert scraper.source_name == "greenhouse:acme"


def test_scrape_returns_job_postings():
    scraper = GreenhouseScraper(GreenhouseQuery(board_token="acme"))

    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(3))
    ):
        jobs = scraper.scrape()

    assert len(jobs) == 3
    assert all(j.source == "greenhouse:acme" for j in jobs)


def test_scrape_maps_fields_correctly():
    scraper = GreenhouseScraper(GreenhouseQuery(board_token="acme"))

    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()

    job = jobs[0]
    assert job.title == "Engineer 0"
    assert job.source_job_id == "1000"
    assert "boards.greenhouse.io" in job.source_url
    assert job.location == "Remote"
    assert job.description == "Job description for role 0."


def test_scrape_empty_board():
    scraper = GreenhouseScraper(GreenhouseQuery(board_token="acme"))

    with patch.object(
        scraper.session, "get", return_value=_mock_response({"jobs": []})
    ):
        jobs = scraper.scrape()

    assert jobs == []


def test_scrape_computes_dedup_hash():
    scraper = GreenhouseScraper(GreenhouseQuery(board_token="acme"))

    with patch.object(
        scraper.session, "get", return_value=_mock_response(_sample_api_response(1))
    ):
        jobs = scraper.scrape()

    assert jobs[0].dedup_hash != ""
