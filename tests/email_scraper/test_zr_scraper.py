"""Tests for email_scraper.zr_scraper — ZR job page scraping.

Covers: JSON-LD extraction, DOM fallback, posted date parsing (relative → ISO),
missing fields, network errors, and edge cases.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


from email_scraper.zr_scraper import (
    _extract_from_json_ld,
    _parse_html,
    _parse_posted_date,
    fetch_job_details_from_url,
)

# ---------------------------------------------------------------------------
# Fixtures — HTML matching ZR's actual Next.js SPA structure
# ---------------------------------------------------------------------------

FIXTURE_URL = "https://www.ziprecruiter.com/jobs/v2/abc123"

# Real ZR structure: DOM-only, no JSON-LD
FULL_HTML = """\
<html>
<body>
  <div data-testid="job-details-scroll-container">
    <div class="flex flex-col">
      <h2>Job description</h2>
      <div class="text-primary whitespace-pre-line">
        <div>
          <div>We are looking for a talented engineer.<br/>
            <strong>Requirements:<br/></strong><br/>
            5+ years experience<br/>
            Python expertise<br/>
            <strong>Benefits:<br/></strong>
            Competitive salary and remote work.
          </div>
        </div>
      </div>
    </div>
    <p class="text-primary normal-case text-body-md">Posted 3 days ago</p>
  </div>
</body>
</html>
"""

# Page with JSON-LD (e.g. Indeed, Glassdoor)
JSON_LD_HTML = """\
<html>
<body>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior Engineer",
    "description": "<p>Build great things.</p><p>Must know Python.</p>",
    "datePosted": "2024-06-15",
    "hiringOrganization": {"@type": "Organization", "name": "Acme Corp"}
  }
  </script>
</body>
</html>
"""

# JSON-LD as a list of schemas
JSON_LD_LIST_HTML = """\
<html>
<body>
  <script type="application/ld+json">
  [
    {"@type": "WebPage", "name": "Job Page"},
    {
      "@type": "JobPosting",
      "description": "Full description from structured data.",
      "datePosted": "2024-07-01"
    }
  ]
  </script>
</body>
</html>
"""

# JSON-LD takes precedence over DOM
JSON_LD_AND_DOM_HTML = """\
<html>
<body>
  <script type="application/ld+json">
  {
    "@type": "JobPosting",
    "description": "JSON-LD description wins.",
    "datePosted": "2024-08-01"
  }
  </script>
  <div data-testid="job-details-scroll-container">
    <div class="text-primary whitespace-pre-line">DOM description loses.</div>
    <p>Posted 1 day ago</p>
  </div>
</body>
</html>
"""

NO_DESCRIPTION_HTML = """\
<html>
<body>
  <div data-testid="job-details-scroll-container">
    <p class="text-primary normal-case text-body-md">Posted 2 hours ago</p>
  </div>
</body>
</html>
"""

EMPTY_DESCRIPTION_HTML = """\
<html>
<body>
  <div data-testid="job-details-scroll-container">
    <div class="text-primary whitespace-pre-line"></div>
    <p class="text-primary normal-case text-body-md">Posted 1 day ago</p>
  </div>
</body>
</html>
"""

NO_DATE_HTML = """\
<html>
<body>
  <div data-testid="job-details-scroll-container">
    <div class="text-primary whitespace-pre-line">
      <p>Some job description here.</p>
    </div>
  </div>
</body>
</html>
"""

BARE_HTML = """\
<html><body><p>Nothing useful here.</p></body></html>
"""

MISSING_CONTAINER_HTML = """\
<html>
<body>
  <div class="job-description">
    <p>This description is outside the expected container.</p>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_playwright(html: str):
    """Patch sync_playwright to return a mock that yields the given HTML."""
    mock_page = MagicMock()
    mock_page.content.return_value = html
    mock_page.goto = MagicMock()
    mock_page.wait_for_load_state = MagicMock()

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_context.add_init_script = MagicMock()

    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close = MagicMock()

    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser

    mock_sync_playwright = MagicMock()
    mock_sync_playwright.__enter__ = MagicMock(return_value=mock_p)
    mock_sync_playwright.__exit__ = MagicMock(return_value=False)

    return patch(
        "email_scraper.zr_scraper.sync_playwright", return_value=mock_sync_playwright
    )


# ---------------------------------------------------------------------------
# Happy path — DOM parsing (ZR's actual structure)
# ---------------------------------------------------------------------------


def test_extracts_description_and_posted_date():
    """Full page with description and date returns both fields."""
    with _mock_playwright(FULL_HTML):
        description, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert "talented engineer" in description
    assert "Python expertise" in description
    assert "Competitive salary" in description
    assert posted_at is not None
    assert "T" in posted_at  # ISO format


def test_description_strips_html_tags():
    """Raw HTML tags are stripped from description text."""
    with _mock_playwright(FULL_HTML):
        description, _ = fetch_job_details_from_url(FIXTURE_URL)

    assert "<p>" not in description
    assert "</p>" not in description
    assert "<strong>" not in description


def test_description_preserves_paragraph_structure():
    """Paragraphs are separated by newlines in the extracted text."""
    with _mock_playwright(FULL_HTML):
        description, _ = fetch_job_details_from_url(FIXTURE_URL)

    lines = [line.strip() for line in description.strip().split("\n") if line.strip()]
    assert len(lines) >= 3  # At least 3 distinct content lines


def test_posted_date_is_iso_format():
    """Posted date is converted from relative to ISO 8601."""
    with _mock_playwright(FULL_HTML):
        _, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert posted_at is not None
    assert "T" in posted_at
    assert posted_at.endswith("Z")


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


def test_json_ld_single_dict():
    """Single JSON-LD JobPosting dict is extracted."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    description, posted_at = _extract_from_json_ld(soup)

    assert "Build great things" in description
    assert "Must know Python" in description
    assert posted_at == "2024-06-15"


def test_json_ld_list_of_schemas():
    """JSON-LD as a list finds the JobPosting item."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(JSON_LD_LIST_HTML, "html.parser")
    description, posted_at = _extract_from_json_ld(soup)

    assert "Full description from structured data" in description
    assert posted_at == "2024-07-01"


def test_json_ld_strips_html_from_description():
    """HTML tags in JSON-LD description are stripped."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    description, _ = _extract_from_json_ld(soup)

    assert "<p>" not in description
    assert "</p>" not in description


def test_json_ld_no_match():
    """No JobPosting in JSON-LD returns (None, None)."""
    from bs4 import BeautifulSoup

    html = (
        '<html><script type="application/ld+json">{"@type": "WebPage"}</script></html>'
    )
    soup = BeautifulSoup(html, "html.parser")
    description, posted_at = _extract_from_json_ld(soup)

    assert description is None
    assert posted_at is None


def test_json_ld_takes_precedence_over_dom():
    """When both JSON-LD and DOM data exist, JSON-LD wins."""
    description, posted_at = _parse_html(JSON_LD_AND_DOM_HTML)

    assert "JSON-LD description wins" in description
    assert "DOM description" not in description
    assert posted_at == "2024-08-01"


# ---------------------------------------------------------------------------
# Missing / empty fields
# ---------------------------------------------------------------------------


def test_missing_description_returns_none():
    """No description element on page returns None for description."""
    with _mock_playwright(NO_DESCRIPTION_HTML):
        description, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert description is None
    assert posted_at is not None


def test_empty_description_returns_none():
    """Description element exists but is empty returns None."""
    with _mock_playwright(EMPTY_DESCRIPTION_HTML):
        description, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert description is None
    assert posted_at is not None


def test_missing_posted_date_returns_none():
    """No posted date element returns None for posted_at."""
    with _mock_playwright(NO_DATE_HTML):
        description, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert description is not None
    assert posted_at is None


def test_bare_page_returns_none_none():
    """Page with neither description nor date returns (None, None)."""
    with _mock_playwright(BARE_HTML):
        description, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert description is None
    assert posted_at is None


def test_missing_container_returns_none_none():
    """Page without job-details-scroll-container returns (None, None)."""
    with _mock_playwright(MISSING_CONTAINER_HTML):
        description, posted_at = fetch_job_details_from_url(FIXTURE_URL)

    assert description is None
    assert posted_at is None


# ---------------------------------------------------------------------------
# Network / Playwright errors
# ---------------------------------------------------------------------------


def test_timeout_returns_none_none():
    """Playwright timeout returns (None, None) without raising."""
    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("Timeout")

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_context.add_init_script = MagicMock()

    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close = MagicMock()

    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser

    mock_sync_playwright = MagicMock()
    mock_sync_playwright.__enter__ = MagicMock(return_value=mock_p)
    mock_sync_playwright.__exit__ = MagicMock(return_value=False)

    with patch(
        "email_scraper.zr_scraper.sync_playwright", return_value=mock_sync_playwright
    ):
        result = fetch_job_details_from_url(FIXTURE_URL)

    assert result == (None, None)


# ---------------------------------------------------------------------------
# Posted date parsing
# ---------------------------------------------------------------------------


def test_parse_posted_date_days_ago():
    result = _parse_posted_date("Posted 3 days ago")
    assert result is not None
    expected = datetime.now(timezone.utc) - timedelta(days=3)
    diff = abs(
        (
            datetime.fromisoformat(result.replace("Z", "+00:00")) - expected
        ).total_seconds()
    )
    assert diff < 60  # Within 1 minute


def test_parse_posted_date_hours_ago():
    result = _parse_posted_date("Posted 2 hours ago")
    expected = datetime.now(timezone.utc) - timedelta(hours=2)
    diff = abs(
        (
            datetime.fromisoformat(result.replace("Z", "+00:00")) - expected
        ).total_seconds()
    )
    assert diff < 60


def test_parse_posted_date_today():
    result = _parse_posted_date("Posted today")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result.startswith(today)


def test_parse_posted_date_singular():
    result = _parse_posted_date("Posted 1 day ago")
    assert result is not None


def test_parse_posted_date_unknown_format():
    assert _parse_posted_date("Just now") is None
    assert _parse_posted_date("Posted yesterday") is None
    assert _parse_posted_date("") is None


# ---------------------------------------------------------------------------
# _parse_html direct tests (no Playwright mocking needed)
# ---------------------------------------------------------------------------


def test_parse_html_full():
    description, posted_at = _parse_html(FULL_HTML)
    assert "talented engineer" in description
    assert posted_at is not None


def test_parse_html_no_description():
    description, posted_at = _parse_html(NO_DESCRIPTION_HTML)
    assert description is None
    assert posted_at is not None


def test_parse_html_bare():
    description, posted_at = _parse_html(BARE_HTML)
    assert description is None
    assert posted_at is None


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_returns_tuple_of_length_two():
    """Function always returns a 2-tuple (description, posted_at)."""
    with _mock_playwright(FULL_HTML):
        result = fetch_job_details_from_url(FIXTURE_URL)

    assert isinstance(result, tuple)
    assert len(result) == 2
