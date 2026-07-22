import sys
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from agents.remote_filter.input_models import RemoteFilterInput
from job_scraper.scrapers.jobspy import JobSpyQuery, JobSpyScraper
from job_scraper.search_provenance import build_search_params


def test_build_search_params_keeps_canonical_and_opaque_fields_flat():
    assert build_search_params(
        workplace="remote",
        keywords="data engineer",
        job_type="fulltime",
        source_detail_location="Remote; Seattle",
        board_token="acme",
    ) == {
        "workplace": "remote",
        "keywords": "data engineer",
        "job_type": "fulltime",
        "source_detail_location": "Remote; Seattle",
        "board_token": "acme",
    }


def test_build_search_params_drops_none_fields():
    assert build_search_params(
        workplace=None,
        keywords="data engineer",
        job_type=None,
        board_token=None,
    ) == {"keywords": "data engineer"}


def test_build_search_params_rejects_unknown_classifier_relevant_key():
    with pytest.raises(ValueError, match="unknown key"):
        build_search_params(is_remote=True)


def test_build_search_params_rejects_bad_workplace():
    with pytest.raises(ValueError, match="search_params.workplace"):
        build_search_params(workplace="somewhere")


def test_build_search_params_rejects_bad_job_type():
    with pytest.raises(ValueError, match="search_params.job_type"):
        build_search_params(job_type="gig")


def test_jobspy_remote_search_params_round_trip_to_remote_filter(monkeypatch):
    class FakeJobSpyResult:
        def iterrows(self):
            yield (
                0,
                {
                    "site": "indeed",
                    "job_url": "https://example.test/jobs/123",
                    "title": "Data Engineer",
                    "company": "Acme",
                    "location": "Remote, USA",
                    "date_posted": "2024-01-15",
                    "description": "Remote data platform role.",
                },
            )

    def fake_scrape_jobs(**_kwargs):
        return FakeJobSpyResult()

    monkeypatch.setitem(
        sys.modules, "jobspy", SimpleNamespace(scrape_jobs=fake_scrape_jobs)
    )

    query = JobSpyQuery(
        search_term="data engineer",
        site_name=["indeed"],
        location="USA",
        is_remote=True,
        job_type="fulltime",
    )

    [job] = JobSpyScraper(query).scrape()
    serialized = asdict(job)

    assert serialized["search_params"]["workplace"] == "remote"
    assert serialized["search_params"]["keywords"] == "data engineer"
    assert "is_remote" not in serialized["search_params"]
    assert "search_term" not in serialized["search_params"]
    assert RemoteFilterInput.from_posting(serialized).workplace == "remote"
