from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup

from job_scraper.scrapers.linkedin import LinkedInJobScraper, _parse_card
from job_scraper.query import LinkedInSearchQuery, TIME_ANY


# --- HTML fixtures -----------------------------------------------------------


def _card_html(
    url="https://www.linkedin.com/jobs/view/senior-engineer-at-acme-1234567890",
    title="Senior Engineer",
    company="Acme Corp",
    location="Remote",
    datetime_attr="2024-01-15",
):
    return f"""
    <div class="base-card">
      <a class="base-card__full-link" href="{url}?trk=xyz"></a>
      <h3 class="base-search-card__title">{title}</h3>
      <h4 class="base-search-card__subtitle">{company}</h4>
      <span class="job-search-card__location">{location}</span>
      <time datetime="{datetime_attr}">2 days ago</time>
    </div>
    """


def _soup_card(html: str):
    return BeautifulSoup(html, "html.parser").find("div", class_="base-card")


def _make_query(**overrides) -> LinkedInSearchQuery:
    defaults = dict(keywords="Python", time_posted=TIME_ANY, fetch_descriptions=False)
    return LinkedInSearchQuery(**{**defaults, **overrides})


def _make_search_html(cards_html: str) -> str:
    return f"<html><body>{cards_html}</body></html>"


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


# --- _parse_card tests -------------------------------------------------------


def test_parse_card_extracts_all_fields():
    card = _soup_card(_card_html())
    result = _parse_card(card)
    assert result["title"] == "Senior Engineer"
    assert result["company"] == "Acme Corp"
    assert result["location"] == "Remote"
    assert result["posted_at"] == "2024-01-15"


def test_parse_card_strips_tracking_params_from_url():
    card = _soup_card(
        _card_html(url="https://linkedin.com/jobs/view/engineer-at-x-999?trk=abc")
    )
    result = _parse_card(card)
    assert "?" not in result["source_url"]
    assert result["source_url"] == "https://linkedin.com/jobs/view/engineer-at-x-999"


def test_parse_card_extracts_job_id():
    card = _soup_card(
        _card_html(url="https://linkedin.com/jobs/view/engineer-at-acme-1234567890")
    )
    result = _parse_card(card)
    assert result["source_job_id"] == "1234567890"


def test_parse_card_missing_optional_fields():
    html = '<div class="base-card"></div>'
    card = _soup_card(html)
    result = _parse_card(card)
    assert result["title"] == ""
    assert result["company"] == ""
    assert result["location"] == ""
    assert result["source_url"] == ""
    assert result["source_job_id"] == ""
    assert result["posted_at"] is None


def test_parse_card_no_id_in_url():
    card = _soup_card(_card_html(url="https://linkedin.com/jobs/view/no-id-here"))
    result = _parse_card(card)
    assert result["source_job_id"] == ""


# --- LinkedInJobScraper tests ------------------------------------------------


def test_source_name():
    scraper = LinkedInJobScraper(_make_query())
    assert scraper.source_name == "linkedin"


def test_fetch_search_page_returns_parsed_cards():
    query = _make_query()
    scraper = LinkedInJobScraper(query)
    card = _card_html(url="https://linkedin.com/jobs/view/eng-at-acme-111", title="Dev")

    with patch.object(
        scraper.session, "get", return_value=_mock_response(_make_search_html(card))
    ):
        results = scraper.fetch_search_page(start=0)

    assert len(results) == 1
    assert results[0]["title"] == "Dev"
    assert results[0]["source_job_id"] == "111"


def test_fetch_search_page_rate_limit_returns_empty():
    scraper = LinkedInJobScraper(_make_query())

    with patch.object(
        scraper.session, "get", return_value=_mock_response("", status_code=429)
    ):
        with patch("time.sleep"):
            results = scraper.fetch_search_page()

    assert results == []


def test_fetch_description_returns_text():
    scraper = LinkedInJobScraper(_make_query())
    html = '<div class="show-more-less-html__markup">Great role with Python.</div>'

    with patch.object(scraper.session, "get", return_value=_mock_response(html)):
        desc = scraper.fetch_description("999")

    assert "Great role with Python." in desc


def test_fetch_description_returns_raw_structured_html():
    scraper = LinkedInJobScraper(_make_query())
    html = """
    <div class="show-more-less-html__markup">
      <p><strong>Key Responsibilities</strong></p>
      <ul>
        <li>Build Python services</li>
        <li>Support production systems</li>
      </ul>
      <p>Contact hiring@example.com or 555-867-5309.</p>
    </div>
    """

    with patch.object(scraper.session, "get", return_value=_mock_response(html)):
        desc = scraper.fetch_description("999")

    assert "Key Responsibilities" in desc
    assert "Build Python services" in desc
    assert "555-867-5309" in desc
    assert "<li>" in desc


def test_scrape_cleans_linkedin_description_to_markdown_and_scrubs_pii():
    scraper = LinkedInJobScraper(_make_query(fetch_descriptions=True, max_results=1))
    stub = {
        "source_job_id": "999",
        "source_url": "https://linkedin.com/jobs/view/eng-999",
        "title": "Dev",
        "company": "Acme",
        "location": "Remote",
        "posted_at": "2024-01-15",
    }
    raw_description = """
    <div class="show-more-less-html__markup">
      <p><strong>Key Responsibilities</strong></p>
      <ul><li>Build Python services</li></ul>
      <p>Contact hiring@example.com or 555-867-5309.</p>
    </div>
    """

    with patch.object(scraper, "fetch_search_page", return_value=[stub]):
        with patch.object(scraper, "fetch_description", return_value=raw_description):
            with patch.object(scraper, "_sleep"):
                [job] = scraper.scrape()

    assert "**Key Responsibilities**" in job.description
    assert "- Build Python services" in job.description
    assert "hiring@example.com" not in job.description
    assert "555-867-5309" not in job.description
    assert job.scrub_counts == {"email": 1, "phone": 1}


def test_fetch_description_bad_status_returns_empty():
    scraper = LinkedInJobScraper(_make_query())

    with patch.object(
        scraper.session, "get", return_value=_mock_response("", status_code=404)
    ):
        desc = scraper.fetch_description("999")

    assert desc == ""


def test_scrape_deduplicates_by_job_id():
    card = _card_html(url="https://linkedin.com/jobs/view/eng-222", title="Dev")
    page_html = _make_search_html(card + card)
    scraper = LinkedInJobScraper(_make_query(max_results=10))

    with patch.object(scraper.session, "get", return_value=_mock_response(page_html)):
        with patch.object(scraper, "_sleep"):
            jobs = scraper.scrape()

    assert len(jobs) == 1


def test_scrape_respects_max_results():
    cards = "".join(
        _card_html(url=f"https://linkedin.com/jobs/view/eng-{i}", title=f"Job {i}")
        for i in range(10)
    )
    scraper = LinkedInJobScraper(_make_query(max_results=3))

    with patch.object(
        scraper.session, "get", return_value=_mock_response(_make_search_html(cards))
    ):
        with patch.object(scraper, "_sleep"):
            jobs = scraper.scrape()

    assert len(jobs) == 3
