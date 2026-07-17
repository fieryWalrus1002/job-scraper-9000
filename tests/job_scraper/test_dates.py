from datetime import date, datetime, timezone

import pytest

from job_scraper.dates import normalize_posted_at


@pytest.mark.parametrize(
    "value,expected",
    [
        # date-only strings pass through unchanged
        ("2026-05-31", "2026-05-31"),
        # ISO datetime with offset -> date component (the issue's failure case)
        ("2026-05-11T13:52:29-04:00", "2026-05-11"),
        # ISO datetime with Z
        ("2024-01-15T00:00:00Z", "2024-01-15"),
        # datetime object -> date component dropped
        (datetime(2026, 5, 11, 13, 52, tzinfo=timezone.utc), "2026-05-11"),
        # date object
        (date(2026, 5, 31), "2026-05-31"),
    ],
)
def test_normalizes_to_date_only(value, expected):
    assert normalize_posted_at(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "nan",
        "NaT",
        "none",
        "null",
        float("nan"),
        123.45,  # bare non-NaN float: unknown unit, dropped
        "not a date",
        "2026-13-99",  # syntactically date-ish but invalid
    ],
)
def test_missing_or_unparseable_becomes_none(value):
    assert normalize_posted_at(value) is None


def test_unparseable_string_is_logged(caplog):
    with caplog.at_level("WARNING"):
        assert normalize_posted_at("garbage") is None
    assert "Dropping unparseable posted_at" in caplog.text


def test_pandas_timestamp_and_nat():
    pd = pytest.importorskip("pandas")
    assert (
        normalize_posted_at(pd.Timestamp("2026-05-11T13:52:29-04:00")) == "2026-05-11"
    )
    assert normalize_posted_at(pd.NaT) is None


def test_idempotent_on_already_normalized_value():
    once = normalize_posted_at("2026-05-11T13:52:29-04:00")
    assert normalize_posted_at(once) == once
