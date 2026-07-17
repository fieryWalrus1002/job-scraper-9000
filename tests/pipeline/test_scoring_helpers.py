"""Unit tests for the pure-Python helpers in ``pipeline.scoring`` — no DB,
so they run in the fast (``not docker``) loop unlike the integration suite in
``test_scoring.py``."""

from __future__ import annotations

import pytest

from pipeline.scoring import (
    _passes_location_restrictions,
    _resolve_restriction,
)
from user_config.models import Location


def _loc(region: str, *, country: str = "US") -> Location:
    return Location(city="Test", region=region, country=country)


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
        # "washington dc" must beat the "washington" prefix → DC, not WA.
        ("Washington DC", ("US", "DC")),
        ("District of Columbia", ("US", "DC")),
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
