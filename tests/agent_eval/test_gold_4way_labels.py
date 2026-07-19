import json
from pathlib import Path

import pytest

from agents.remote_filter.models import REMOTE_CLASSIFICATIONS

REPO_ROOT = Path(__file__).parents[2]
GOLD_PATH = REPO_ROOT / "data" / "eval" / "ground_truth.jsonl"
EXPECTED_RECORD_COUNT = 106
TRAVEL_POLICIES = {"remote_with_monthly_travel", "remote_with_frequent_travel"}

# The gold corpus (`data/eval/ground_truth.jsonl`) is a local-only artifact —
# it holds scraped job-posting text and is gitignored (`data/**/*.jsonl`), so it
# is absent in CI. These are validation checks for the local remap output
# (`scripts/remap_gold_to_4way.py`); skip when the fixture isn't present rather
# than fail a checkout that never had it.
pytestmark = pytest.mark.skipif(
    not GOLD_PATH.exists(),
    reason="local-only gold corpus (data/eval/ground_truth.jsonl) not present",
)


def load_gold_records() -> list[dict]:
    return [json.loads(line) for line in GOLD_PATH.read_text().splitlines() if line]


def test_remote_filter_gold_records_have_4way_human_classification():
    records = load_gold_records()

    assert len(records) == EXPECTED_RECORD_COUNT
    assert all(record.get("_human_verdict") is not None for record in records)
    assert all(
        record.get("_human_classification") in REMOTE_CLASSIFICATIONS
        for record in records
    )


def test_remote_filter_gold_travel_and_location_fields_are_filled():
    records = load_gold_records()
    travel_records = [
        record for record in records if record.get("_human_policy") in TRAVEL_POLICIES
    ]
    location_restricted_records = [
        record
        for record in records
        if record.get("_human_policy") == "location_restricted"
    ]

    assert len(travel_records) == 3
    assert all(
        isinstance(record.get("_human_travel_days"), int) for record in travel_records
    )
    assert len(location_restricted_records) == 2
    assert all(
        "location_restrictions" in record for record in location_restricted_records
    )
