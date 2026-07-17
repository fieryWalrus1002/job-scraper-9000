"""Unit tests for the pure-Python helpers in ``pipeline.scoring`` — no DB,
so they run in the fast (``not docker``) loop unlike the integration suite in
``test_scoring.py``."""

from __future__ import annotations

import pytest

from pipeline.scoring import (
    _passes_location_restrictions,
    _resolve_restriction,
    _travel_days_of,
)
from user_config.models import Location


def _rec(days: object) -> dict:
    return {"_remote_analysis": {"estimated_travel_days_per_year": days}}


def _loc(region: str, *, country: str = "US") -> Location:
    return Location(city="Test", region=region, country=country)


def test_travel_days_reads_int():
    assert _travel_days_of(_rec(40)) == 40


def test_travel_days_none_is_passthrough():
    assert _travel_days_of(_rec(None)) is None
    assert _travel_days_of({}) is None  # missing analysis entirely


def test_corrupt_string_estimate_raises():
    with pytest.raises(TypeError, match="estimated_travel_days_per_year"):
        _travel_days_of(_rec("40"))


def test_bool_estimate_raises():
    """isinstance(True, int) is True, so a stored ``true`` must be rejected
    explicitly rather than silently read as 1 day."""
    with pytest.raises(TypeError, match="estimated_travel_days_per_year"):
        _travel_days_of(_rec(True))


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("US", ("US", None)),
        ("U.S.", ("US", None)),
        ("USA", ("US", None)),
        ("United States", ("US", None)),
        ("US-only", ("US", None)),
        ("US only", ("US", None)),
        ("US-based", ("US", None)),
        ("US based", ("US", None)),
        ("Continental United States", ("US", None)),
        ("America", ("US", None)),
        ("CA", ("US", "CA")),
        ("California", ("US", "CA")),
        ("must reside in CA", ("US", "CA")),
        ("Seattle, WA, USA", ("US", "WA")),
        ("Canada", ("CANADA", None)),
        ("UK", ("UK", None)),
        ("United Kingdom", ("UK", None)),
        ("anywhere-ish gibberish", None),
    ],
)
def test_resolve_restriction(entry, expected):
    assert _resolve_restriction(entry) == expected


@pytest.mark.parametrize(
    ("restrictions", "acceptable", "willing", "expected"),
    [
        ([], [_loc("AZ")], False, True),
        (["Canada"], [], True, True),
        (["Canada"], [_loc("AZ")], True, False),
        (["CA", "NY"], [_loc("AZ")], True, True),
        (["US-only"], [_loc("AZ")], True, True),
        (["CA"], [_loc("AZ")], False, False),
        (["AZ"], [_loc("AZ")], False, True),
        (["Canada", "anywhere-ish gibberish"], [_loc("AZ")], False, True),
        (["Canada", "US-only"], [_loc("AZ")], False, True),
    ],
)
def test_passes_location_restrictions(
    restrictions: list[str],
    acceptable: list[Location],
    willing: bool,
    expected: bool,
):
    assert _passes_location_restrictions(restrictions, acceptable, willing) is expected
