"""Tests for SELJobScraper."""

<<<<<<< HEAD
from unittest.mock import MagicMock, call

from job_scraper.query import SELSearchQuery
from job_scraper.scrapers.sel import SELJobScraper, _JOBS_API, _PAGE_SIZE, _parse_posted_at
=======
import json
from unittest.mock import MagicMock

from job_scraper.query import SELSearchQuery
from job_scraper.scrapers.sel import SELJobScraper
>>>>>>> 9054768 (feat(sel_scraper): added pytest suite)


def _make_scraper(**kwargs) -> SELJobScraper:
    return SELJobScraper(SELSearchQuery(**kwargs))


<<<<<<< HEAD
def _api_response(postings: list[dict], total: int | None = None) -> MagicMock:
    """Build a mock POST response from the Workday CXS jobs API."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "total": total if total is not None else len(postings),
        "jobPostings": postings,
        "facets": [],
    }
    return mock_resp


def _posting(n: int = 1) -> dict:
    return {
        "title": f"Engineer {n}",
        "externalPath": f"/job/Pullman-WA/Engineer_{n}_JR{n:03}",
        "locationsText": "Washington - Pullman",
        "bulletFields": [f"2025-{n:05}"],
    }


# ---------------------------------------------------------------------------
# source_name
=======
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
>>>>>>> 9054768 (feat(sel_scraper): added pytest suite)
# ---------------------------------------------------------------------------


def test_source_name():
    assert _make_scraper().source_name == "sel"


<<<<<<< HEAD
# ---------------------------------------------------------------------------
# API call shape
# ---------------------------------------------------------------------------


def test_scrape_posts_to_cxs_api():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([])

    scraper.scrape()

    scraper.session.post.assert_called_once()
    assert scraper.session.post.call_args.args[0] == _JOBS_API


def test_scrape_does_not_call_get_for_listing():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([])

    scraper.scrape()

    scraper.session.get.assert_not_called()


def test_scrape_payload_contains_applied_facets():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([])

    scraper.scrape()

    payload = scraper.session.post.call_args.kwargs["json"]
    assert "appliedFacets" in payload
    assert payload["appliedFacets"] == scraper.query.to_applied_facets()


def test_scrape_payload_includes_limit_and_offset():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([])

    scraper.scrape()

    payload = scraper.session.post.call_args.kwargs["json"]
    assert payload["limit"] == _PAGE_SIZE
    assert payload["offset"] == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_scrape_paginates_until_total_reached():
    # Workday only returns total on page 1; subsequent pages return total=0
    page1 = [_posting(i) for i in range(1, _PAGE_SIZE + 1)]
    page2 = [_posting(i) for i in range(_PAGE_SIZE + 1, _PAGE_SIZE + 4)]
    total = len(page1) + len(page2)

    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.side_effect = [
        _api_response(page1, total=total),
        _api_response(page2, total=0),   # Workday: total=0 on pages 2+
    ]

    jobs = scraper.scrape()

    assert scraper.session.post.call_count == 2
    assert len(jobs) == total


def test_scrape_second_page_uses_correct_offset():
    page1 = [_posting(i) for i in range(1, _PAGE_SIZE + 1)]
    page2 = [_posting(_PAGE_SIZE + 1)]

    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.side_effect = [
        _api_response(page1, total=_PAGE_SIZE + 1),
        _api_response(page2, total=0),   # Workday: total=0 on pages 2+
    ]

    scraper.scrape()

    offsets = [c.kwargs["json"]["offset"] for c in scraper.session.post.call_args_list]
    assert offsets == [0, _PAGE_SIZE]


def test_scrape_stops_when_postings_empty():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([], total=0)

    jobs = scraper.scrape()

    assert jobs == []
    assert scraper.session.post.call_count == 1


# ---------------------------------------------------------------------------
# JobPosting field mapping
# ---------------------------------------------------------------------------


def test_scrape_maps_title_and_location():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].title == "Engineer 1"
    assert jobs[0].location == "Washington - Pullman"


def test_scrape_source_job_id_from_bullet_fields():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].source_job_id == "2025-00001"


def test_scrape_source_url_uses_domain_and_external_path():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].source_url == "https://selinc.wd1.myworkdayjobs.com/job/Pullman-WA/Engineer_1_JR001"


def test_scrape_company_is_sel():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].company == "SEL"
    assert jobs[0].source == "sel"


def test_scrape_computes_dedup_hash():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].dedup_hash != ""


# ---------------------------------------------------------------------------
# Description fetching
# ---------------------------------------------------------------------------


def test_scrape_does_not_fetch_descriptions_when_disabled():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    scraper.scrape()

    scraper.session.get.assert_not_called()


def test_scrape_fetches_description_per_job_when_enabled():
    scraper = _make_scraper(fetch_descriptions=True)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1), _posting(2)])
    detail_resp = MagicMock()
    detail_resp.status_code = 200
    # Real Workday API: description is under jobPostingInfo, not top-level
    detail_resp.json.return_value = {"jobPostingInfo": {"jobDescription": "<p>Great job</p>", "postedOn": "2026-05-01"}}
    scraper.session.get.return_value = detail_resp

    jobs = scraper.scrape()

    assert scraper.session.get.call_count == 2
    assert "Great job" in jobs[0].description
    assert jobs[0].posted_at == "2026-05-01"


# ---------------------------------------------------------------------------
# SELSearchQuery.to_applied_facets
# ---------------------------------------------------------------------------


def test_to_applied_facets_regular_worker_type():
    q = SELSearchQuery(worker_sub_types=["regular"])
    facets = q.to_applied_facets()
    assert facets["workerSubType"] == ["96e1096563ef1014e495031ab61a6dff"]


def test_to_applied_facets_temporary_worker_type():
    q = SELSearchQuery(worker_sub_types=["temporary"])
    facets = q.to_applied_facets()
    assert facets["workerSubType"] == ["96e1096563ef1014e495069e83966e00"]


def test_to_applied_facets_full_time():
    q = SELSearchQuery(time_types=["full_time"])
    facets = q.to_applied_facets()
    assert facets["timeType"] == ["b0630d66f89e1013409e4b1a1a91c123"]


def test_to_applied_facets_pullman_wa_location():
    q = SELSearchQuery(location_key="pullman_wa")
    facets = q.to_applied_facets()
    assert facets["locations"] == ["df72ee3ddefc1018ebf01de718624e22"]


def test_to_applied_facets_unknown_key_omitted():
    q = SELSearchQuery(location_key="nonexistent", worker_sub_types=["unknown"])
    facets = q.to_applied_facets()
    assert "locations" not in facets
    assert "workerSubType" not in facets


def test_to_applied_facets_multiple_worker_types():
    q = SELSearchQuery(worker_sub_types=["regular", "temporary"])
    facets = q.to_applied_facets()
    assert len(facets["workerSubType"]) == 2


# ---------------------------------------------------------------------------
# _parse_posted_at — relative date → ISO date
# ---------------------------------------------------------------------------

_REF = "2026-05-14T15:00:00+00:00"


def test_parse_posted_at_today():
    assert _parse_posted_at("Posted Today", _REF) == "2026-05-14"


def test_parse_posted_at_yesterday():
    assert _parse_posted_at("Posted Yesterday", _REF) == "2026-05-13"


def test_parse_posted_at_n_days_ago():
    assert _parse_posted_at("Posted 8 Days Ago", _REF) == "2026-05-06"


def test_parse_posted_at_30plus_days_ago():
    assert _parse_posted_at("Posted 30+ Days Ago", _REF) == "2026-04-14"


def test_parse_posted_at_unrecognised_passthrough():
    assert _parse_posted_at("Some weird string", _REF) == "Some weird string"


def test_parse_posted_at_none_returns_none():
    assert _parse_posted_at(None, _REF) is None


def test_parse_posted_at_already_iso_passthrough():
    assert _parse_posted_at("2026-05-01", _REF) == "2026-05-01"


# ---------------------------------------------------------------------------
# Multi-location fallback
# ---------------------------------------------------------------------------


def _multi_location_posting(n: int = 1) -> dict:
    p = _posting(n)
    p["locationsText"] = "2 Locations"
    return p


def test_scrape_replaces_multi_location_with_query_location():
    scraper = _make_scraper(fetch_descriptions=False, location_key="pullman_wa")
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_multi_location_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].location == "Washington - Pullman"


def test_scrape_preserves_single_location():
    scraper = _make_scraper(fetch_descriptions=False, location_key="pullman_wa")
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])

    jobs = scraper.scrape()

    assert jobs[0].location == "Washington - Pullman"


def test_scrape_strips_title_whitespace():
    scraper = _make_scraper(fetch_descriptions=False)
    scraper.session = MagicMock()
    posting = _posting(1)
    posting["title"] = "Engineer 1 "
    scraper.session.post.return_value = _api_response([posting])

    jobs = scraper.scrape()

    assert jobs[0].title == "Engineer 1"


def test_scrape_posted_at_parsed_from_relative_string():
    scraper = _make_scraper(fetch_descriptions=True)
    scraper.session = MagicMock()
    scraper.session.post.return_value = _api_response([_posting(1)])
    detail_resp = MagicMock()
    detail_resp.status_code = 200
    detail_resp.json.return_value = {"jobPostingInfo": {"jobDescription": "<p>ok</p>", "postedOn": "Posted Yesterday"}}
    scraper.session.get.return_value = detail_resp

    jobs = scraper.scrape()

    # posted_at should be an ISO date, not the raw relative string
    assert jobs[0].posted_at is not None
    assert "Posted" not in jobs[0].posted_at
    assert len(jobs[0].posted_at) == 10  # YYYY-MM-DD
=======
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
>>>>>>> 9054768 (feat(sel_scraper): added pytest suite)
