import pytest

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
