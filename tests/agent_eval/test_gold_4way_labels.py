import json
from collections import Counter
from pathlib import Path

import pytest

from agents.remote_filter.models import REMOTE_CLASSIFICATIONS

REPO_ROOT = Path(__file__).parents[2]
GOLD_PATH = REPO_ROOT / "data" / "eval" / "ground_truth.jsonl"
# Phase 32 (#519 re-ratification + #520 unclear retirement): dropped the 2
# recruiting-spam non-jobs that used to carry `unclear`. Axis is now 3-way.
EXPECTED_RECORD_COUNT = 104
EXPECTED_CLASSIFICATION_COUNTS = {"onsite": 55, "remote": 35, "hybrid": 14}
EXPECTED_TRAVEL_RECORD_COUNT = 2
EXPECTED_LOCATION_RESTRICTED_RECORD_COUNT = 1
TRAVEL_POLICIES = {"remote_with_monthly_travel", "remote_with_frequent_travel"}

# The gold corpus (`data/eval/ground_truth.jsonl`) is a local-only artifact —
# it holds scraped job-posting text and is gitignored (`data/**/*.jsonl`), so it
# is absent in CI. These validate the local gold shape; skip when the fixture
# isn't present rather than fail a checkout that never had it.
pytestmark = pytest.mark.skipif(
    not GOLD_PATH.exists(),
    reason="local-only gold corpus (data/eval/ground_truth.jsonl) not present",
)


def load_gold_records() -> list[dict]:
    return [json.loads(line) for line in GOLD_PATH.read_text().splitlines() if line]


def test_remote_filter_gold_records_have_3way_human_classification():
    records = load_gold_records()

    assert len(records) == EXPECTED_RECORD_COUNT
    assert all(record.get("_human_verdict") is not None for record in records)
    # Every gold label is on the 3-way axis, and `unclear` is fully retired.
    assert all(
        record.get("_human_classification") in REMOTE_CLASSIFICATIONS
        for record in records
    )
    assert (
        Counter(record.get("_human_classification") for record in records)
        == EXPECTED_CLASSIFICATION_COUNTS
    )
    assert "unclear" not in REMOTE_CLASSIFICATIONS
    assert not any(
        record.get("_human_classification") == "unclear" for record in records
    )


def test_remote_filter_gold_travel_and_location_fields_are_filled():
    # Invariant (durable across gold re-ratification): any record still carrying a
    # legacy travel/location policy tag must have its structured field filled.
    # Pin counts too so accidental corpus-shape drift is visible; update these
    # intentionally when #520 2b retires the fine-grained policy tags.
    records = load_gold_records()
    travel_records = [
        record for record in records if record.get("_human_policy") in TRAVEL_POLICIES
    ]
    location_restricted_records = [
        record
        for record in records
        if record.get("_human_policy") == "location_restricted"
    ]

    assert len(travel_records) == EXPECTED_TRAVEL_RECORD_COUNT
    assert all(
        isinstance(record.get("_human_travel_days"), int) for record in travel_records
    )
    assert len(location_restricted_records) == EXPECTED_LOCATION_RESTRICTED_RECORD_COUNT
    assert all(
        "location_restrictions" in record for record in location_restricted_records
    )
