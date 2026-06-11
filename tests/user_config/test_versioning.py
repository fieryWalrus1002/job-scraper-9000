"""Tests for the content-hash profile_version (spec §2)."""

from __future__ import annotations

from datetime import date

from user_config import canonical_json, compute_profile_version


def test_canonical_json_is_key_order_independent():
    a = {"summary": "x", "level": "y", "core_skills": ["py"]}
    b = {"core_skills": ["py"], "level": "y", "summary": "x"}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_has_no_incidental_whitespace():
    assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_version_format_is_date_dot_sha12():
    v = compute_profile_version({"summary": "x"}, today=date(2026, 6, 11))
    prefix, _, digest = v.partition(".")
    assert prefix == "2026-06-11"
    assert len(digest) == 12
    assert all(c in "0123456789abcdef" for c in digest)


def test_version_is_deterministic_for_same_content():
    payload = {"summary": "x", "core_skills": ["py", "sql"]}
    today = date(2026, 6, 11)
    assert compute_profile_version(payload, today=today) == compute_profile_version(
        {"core_skills": ["py", "sql"], "summary": "x"}, today=today
    )


def test_version_changes_when_content_changes():
    today = date(2026, 6, 11)
    v1 = compute_profile_version({"summary": "x"}, today=today)
    v2 = compute_profile_version({"summary": "y"}, today=today)
    assert v1 != v2
