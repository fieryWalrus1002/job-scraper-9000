from datetime import date

from job_scraper.scrapers.jobspy import _date_str


def test_date_str_none():
    assert _date_str(None) is None


def test_date_str_float_nan():
    assert _date_str(float("nan")) is None


def test_date_str_date_object():
    assert _date_str(date(2026, 5, 31)) == "2026-05-31"


def test_date_str_string_nan():
    assert _date_str("nan") is None


def test_date_str_string_nat():
    assert _date_str("NaT") is None


def test_date_str_valid_string():
    assert _date_str("2026-05-31") == "2026-05-31"
