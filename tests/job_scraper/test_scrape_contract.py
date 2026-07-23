from __future__ import annotations

import sys
from dataclasses import asdict
from types import SimpleNamespace
from typing import get_args
from unittest.mock import MagicMock, patch

from job_scraper.models import JobPosting
from job_scraper.query import LinkedInSearchQuery, SELSearchQuery, TIME_ANY
from job_scraper.scrapers.ashby import AshbyQuery, AshbyScraper
from job_scraper.scrapers.greenhouse import GreenhouseQuery, GreenhouseScraper
from job_scraper.scrapers.jobspy import JobSpyQuery, JobSpyScraper
from job_scraper.scrapers.lever import LeverQuery, LeverScraper
from job_scraper.scrapers.linkedin import LinkedInJobScraper
from job_scraper.scrapers.sel import SELJobScraper
from job_scraper.search_provenance import _CANONICAL, _JOB_TYPE, _OPAQUE_ALLOWED
from user_config.models import EmploymentType

_ALLOWED_SEARCH_PARAM_KEYS = set(_CANONICAL) | _OPAQUE_ALLOWED


def _mock_json_response(json_data: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_text_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _assert_contract(job: JobPosting) -> None:
    serialized = asdict(job)
    assert serialized["source"]
    assert serialized["source_job_id"]
    assert serialized["source_url"].startswith("http")
    assert serialized["title"]
    assert serialized["company"]
    assert serialized["location"]
    assert serialized["posted_at"] is not None
    assert len(serialized["posted_at"]) == len("YYYY-MM-DD")
    assert serialized["description"].strip()
    assert serialized["scraped_at"]
    assert serialized["dedup_hash"]
    assert set(serialized["search_params"]) <= _ALLOWED_SEARCH_PARAM_KEYS
    assert all(
        not isinstance(value, dict) for value in serialized["search_params"].values()
    )


def test_employment_type_contract_stays_with_search_provenance_job_type_allowlist():
    assert set(get_args(EmploymentType)) <= _JOB_TYPE


def test_jobspy_scrape_contract(monkeypatch):
    class FakeJobSpyResult:
        def iterrows(self):
            yield (
                0,
                {
                    "site": "indeed",
                    "job_url": "https://example.test/jobs/jobspy-1",
                    "title": "Data Engineer",
                    "company": "Acme",
                    "location": "Remote, USA",
                    "date_posted": "2024-01-15",
                    "description": "Build reliable data pipelines for remote teams.",
                },
            )

    def fake_scrape_jobs(**_kwargs):
        return FakeJobSpyResult()

    monkeypatch.setitem(
        sys.modules, "jobspy", SimpleNamespace(scrape_jobs=fake_scrape_jobs)
    )

    scraper = JobSpyScraper(
        JobSpyQuery(
            search_term="data engineer",
            site_name=["indeed"],
            location="USA",
            is_remote=True,
            job_type="fulltime",
        )
    )

    [job] = scraper.scrape()

    _assert_contract(job)
    assert job.search_params["workplace"] == "remote"
    assert job.search_params["keywords"] == "data engineer"


def test_linkedin_scrape_contract():
    search_html = """
    <html><body>
      <div class="base-card">
        <a class="base-card__full-link"
           href="https://www.linkedin.com/jobs/view/engineer-at-acme-1234567890?trk=xyz"></a>
        <h3 class="base-search-card__title">Senior Engineer</h3>
        <h4 class="base-search-card__subtitle">Acme Corp</h4>
        <span class="job-search-card__location">Remote</span>
        <time datetime="2024-01-15">2 days ago</time>
      </div>
    </body></html>
    """
    detail_html = """
    <div class="show-more-less-html__markup">
      <p>Build Python services for distributed remote teams.</p>
    </div>
    """
    scraper = LinkedInJobScraper(
        LinkedInSearchQuery(keywords="python", time_posted=TIME_ANY, max_results=1)
    )

    with patch.object(
        scraper.session,
        "get",
        side_effect=[
            _mock_text_response(search_html),
            _mock_text_response(detail_html),
        ],
    ):
        with patch.object(scraper, "_sleep"):
            [job] = scraper.scrape()

    _assert_contract(job)
    assert job.search_params["workplace"] == "remote"
    assert job.search_params["keywords"] == "python"


def test_sel_scrape_contract():
    scraper = SELJobScraper(SELSearchQuery(fetch_descriptions=True))
    scraper.session = MagicMock()
    scraper.session.post.return_value = _mock_json_response(
        {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Software Engineer",
                    "externalPath": "/job/Remote/Software-Engineer_JR001",
                    "locationsText": "Remote",
                    "bulletFields": ["JR001"],
                }
            ],
            "facets": [],
        }
    )
    scraper.session.get.return_value = _mock_json_response(
        {
            "jobPostingInfo": {
                "location": "Remote",
                "timeType": "Full time",
                "jobReqId": "JR001",
                "jobDescription": "<p>Build embedded software tools remotely.</p>",
                "postedOn": "2024-01-15",
            }
        }
    )

    [job] = scraper.scrape()

    _assert_contract(job)
    assert job.search_params["workplace"] == "remote"
    assert job.search_params["job_type"] == "fulltime"
    assert job.search_params["source_detail_location"] == "Remote"


def test_greenhouse_scrape_contract():
    scraper = GreenhouseScraper(GreenhouseQuery(board_token="acme"))
    with patch.object(
        scraper.session,
        "get",
        return_value=_mock_json_response(
            {
                "jobs": [
                    {
                        "id": 1000,
                        "title": "Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1000",
                        "location": {"name": "Remote"},
                        "first_published": "2024-01-15T10:35:43-04:00",
                        "content": "<p>Build developer tools for customers.</p>",
                    }
                ]
            }
        ),
    ):
        [job] = scraper.scrape()

    _assert_contract(job)
    assert job.search_params == {"board_token": "acme"}


def test_ashby_scrape_contract():
    scraper = AshbyScraper(AshbyQuery(company="acme"))
    with patch.object(
        scraper.session,
        "get",
        return_value=_mock_json_response(
            {
                "jobs": [
                    {
                        "id": "uuid-1",
                        "title": "Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/uuid-1",
                        "location": "Remote",
                        "publishedAt": "2024-01-15T00:00:00.000Z",
                        "descriptionPlain": "Build product features with Python.",
                    }
                ]
            }
        ),
    ):
        [job] = scraper.scrape()

    _assert_contract(job)
    assert job.search_params == {"company": "acme"}


def test_lever_scrape_contract():
    scraper = LeverScraper(LeverQuery(company="acme"))
    with patch.object(
        scraper.session,
        "get",
        return_value=_mock_json_response(
            [
                {
                    "id": "uuid-1",
                    "text": "Engineer",
                    "hostedUrl": "https://jobs.lever.co/acme/uuid-1",
                    "categories": {"location": "Remote"},
                    "descriptionPlain": "Build APIs and operate production systems.",
                    "createdAt": 1_700_000_000_000,
                }
            ]
        ),
    ):
        [job] = scraper.scrape()

    _assert_contract(job)
    assert job.search_params == {"company": "acme"}
