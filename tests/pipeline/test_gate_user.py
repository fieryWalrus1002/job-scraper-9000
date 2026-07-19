"""DB-free unit tests for the per-user scoring policy gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pipeline.scoring import _gate_user
from pipeline.worker import run_user_dir

RUN_ID = "overnight-2026-06-12"
EMAIL = "user@example.com"


def _profile(runs_dir: Path, email: str = EMAIL) -> None:
    profile_dir = run_user_dir(runs_dir, RUN_ID, email)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "candidate_profile.yml").write_text("{}", encoding="utf-8")


def _posting(
    dedup_hash: str,
    classification: str,
    *,
    travel_days: int | None = None,
    requires_relocation: bool = False,
    requires_local_presence: bool = False,
    location: str | None = None,
    location_restrictions: list[str] | None = None,
) -> dict[str, Any]:
    analysis: dict[str, Any] = {
        "remote_classification": classification,
        "estimated_travel_days_per_year": travel_days,
        "requires_relocation": requires_relocation,
        "requires_local_presence": requires_local_presence,
    }
    if location_restrictions is not None:
        analysis["location_restrictions"] = location_restrictions

    rec: dict[str, Any] = {
        "dedup_hash": dedup_hash,
        "title": "Engineer",
        "description": "Build useful things.",
        "_remote_analysis": analysis,
    }
    if location is not None:
        rec["location"] = location
    return rec


def _gate(
    tmp_path: Path,
    *,
    policies: dict[str, Any] | None,
    postings: list[dict[str, Any]],
    write_profile: bool,
):
    if write_profile:
        _profile(tmp_path)
    summary = {
        "postings_unclassified": 0,
        "users_skipped_no_postings": 0,
        "per_user": [],
    }
    row = {
        "email": EMAIL,
        "policies": policies,
        "dedup_hashes": [posting["dedup_hash"] for posting in postings],
    }
    classified = {posting["dedup_hash"]: posting for posting in postings}
    return _gate_user(
        row,
        classified,
        runs_dir=tmp_path,
        run_id=RUN_ID,
        summary=summary,
    )


@pytest.mark.parametrize(
    (
        "case_id",
        "policies",
        "posting",
        "expected_hashes",
    ),
    [
        (
            "remote classification survives remote-only policy",
            {"remote": {"acceptable_classifications": ["remote"]}},
            _posting("h-remote", "remote"),
            {"h-remote"},
        ),
        (
            "onsite classification drops under remote-only policy",
            {"remote": {"acceptable_classifications": ["remote"]}},
            _posting("h-onsite", "onsite"),
            set(),
        ),
        (
            "unclear survives default permissive policy",
            None,
            _posting("h-unclear", "unclear"),
            {"h-unclear"},
        ),
        (
            "high travel is display-only and does not gate",
            {
                "remote": {
                    "acceptable_classifications": ["remote"],
                    "max_travel_days": 15,
                }
            },
            _posting("h-travel", "remote", travel_days=300),
            {"h-travel"},
        ),
        (
            "required relocation drops when relocation is not allowed",
            {"remote": {"acceptable_classifications": ["remote"]}},
            _posting("h-relocation", "remote", requires_relocation=True),
            set(),
        ),
        (
            "required relocation survives when relocation is allowed",
            {
                "remote": {"acceptable_classifications": ["remote"]},
                "relocation": {"allow_required_relocation": True},
            },
            _posting("h-relocation-allowed", "remote", requires_relocation=True),
            {"h-relocation-allowed"},
        ),
        (
            "local presence survives for an acceptable local posting",
            {
                "remote": {"acceptable_classifications": ["remote"]},
                "relocation": {
                    "acceptable_locations": [
                        {"city": "Seattle", "region": "WA", "country": "US"}
                    ]
                },
            },
            _posting(
                "h-local-seattle",
                "remote",
                requires_local_presence=True,
                location="Seattle, WA",
            ),
            {"h-local-seattle"},
        ),
        (
            "local presence drops for an out-of-area posting",
            {
                "remote": {"acceptable_classifications": ["remote"]},
                "relocation": {
                    "acceptable_locations": [
                        {"city": "Seattle", "region": "WA", "country": "US"}
                    ]
                },
            },
            _posting(
                "h-local-austin",
                "remote",
                requires_local_presence=True,
                location="Austin, TX",
            ),
            set(),
        ),
        (
            "us-only location restriction survives for a us acceptable location",
            {
                "remote": {"acceptable_classifications": ["remote"]},
                "relocation": {
                    "acceptable_locations": [
                        {"city": "Seattle", "region": "WA", "country": "US"}
                    ]
                },
            },
            _posting(
                "h-us-only",
                "remote",
                location_restrictions=["US-only"],
            ),
            {"h-us-only"},
        ),
    ],
)
def test_gate_user_policy_table(
    tmp_path: Path,
    case_id: str,
    policies: dict[str, Any] | None,
    posting: dict[str, Any],
    expected_hashes: set[str],
):
    result = _gate(
        tmp_path,
        policies=policies,
        postings=[posting],
        write_profile=bool(expected_hashes),
    )

    assert case_id
    if not expected_hashes:
        assert result is None
        return

    assert result is not None
    assert {rec["dedup_hash"] for rec in result.survivors} == expected_hashes
    assert len(result.survivors) == len(expected_hashes)


def test_gate_user_keeps_only_matching_membership_survivors(tmp_path: Path):
    postings = [
        _posting("h-remote", "remote"),
        _posting("h-onsite", "onsite"),
    ]

    result = _gate(
        tmp_path,
        policies={"remote": {"acceptable_classifications": ["remote"]}},
        postings=postings,
        write_profile=True,
    )

    assert result is not None
    assert [rec["dedup_hash"] for rec in result.survivors] == ["h-remote"]
