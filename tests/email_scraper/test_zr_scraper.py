"""Tests for email_scraper.zr_scraper — ZR URL detail fetching.

Currently a stub (returns None, None). Tests verify the contract until
the real implementation lands.
"""

from email_scraper.zr_scraper import fetch_job_details_from_url


def test_stub_returns_none_tuple():
    """Current placeholder returns (None, None)."""
    result = fetch_job_details_from_url("https://www.ziprecruiter.com/km/abc123")
    assert result == (None, None)


def test_stub_returns_tuple_of_length_two():
    """Contract: function returns a 2-tuple (description, posted_at)."""
    result = fetch_job_details_from_url("https://example.com")
    assert isinstance(result, tuple)
    assert len(result) == 2
