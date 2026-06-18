"""Unit tests for the pure-Python helpers in ``pipeline.scoring`` — no DB,
so they run in the fast (``not docker``) loop unlike the integration suite in
``test_scoring.py``."""

from __future__ import annotations

import pytest

from pipeline.scoring import _travel_days_of


def _rec(days: object) -> dict:
    return {"_remote_analysis": {"estimated_travel_days_per_year": days}}


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
