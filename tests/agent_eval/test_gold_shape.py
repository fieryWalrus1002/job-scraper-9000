import json
from pathlib import Path

import pytest

from agents.remote_filter.models import REMOTE_CLASSIFICATIONS

REPO_ROOT = Path(__file__).parents[2]
GOLD_PATH = REPO_ROOT / "data" / "eval" / "ground_truth.jsonl"

TRAVEL_POLICIES = {"remote_with_monthly_travel", "remote_with_frequent_travel"}

# The gold corpus (`data/eval/ground_truth.jsonl`) is a local-only artifact —
# it holds scraped job-posting text and is gitignored (`data/**/*.jsonl`), so it
# is absent in CI. These validate the local gold *shape*; skip when the fixture
# isn't present rather than fail a checkout that never had it.
pytestmark = pytest.mark.skipif(
    not GOLD_PATH.exists(),
    reason="local-only gold corpus (data/eval/ground_truth.jsonl) not present",
)


def load_gold_records() -> list[dict]:
    """Deduped last-wins per ``dedup_hash`` — mirrors ``run_remote_filter_eval.load_gold``.

    Gold is append-only: an HITL correction re-appends a row for an existing
    ``dedup_hash`` and the later entry wins at eval time. Validating raw lines
    would double-count corrections, so dedup exactly as the eval loader does.
    Deliberately no pinned record/label *counts*: gold legitimately grows via
    corrections, HITL additions, and dedup passes, and hard-coding magnitudes of
    an untracked local file guarantees false failures on every sanctioned change.
    We assert count-free shape invariants instead.
    """
    last: dict[str, dict] = {}
    for line in GOLD_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        key = record.get("dedup_hash") or record.get("source_url")
        if key:
            last[key] = record
    return list(last.values())


def test_remote_filter_gold_is_three_way_and_verdicted():
    records = load_gold_records()

    assert records, "gold corpus is present but empty"
    assert all(record.get("_human_verdict") is not None for record in records)
    # Every gold label is on the active 3-way axis, and `unclear` is fully retired.
    assert "unclear" not in REMOTE_CLASSIFICATIONS
    assert all(
        record.get("_human_classification") in REMOTE_CLASSIFICATIONS
        for record in records
    )


def test_remote_filter_gold_travel_and_location_fields_are_filled():
    # Durable invariant (survives gold growth): any record still carrying a legacy
    # travel/location policy tag must have its structured field filled. Keyed off
    # the structured data for records that have the tag, not a pinned count — the
    # correction workflow no longer maintains `_human_policy`, so records may drop
    # the tag, but any that keep it must remain internally consistent.
    records = load_gold_records()
    travel_records = [
        record for record in records if record.get("_human_policy") in TRAVEL_POLICIES
    ]
    location_restricted_records = [
        record
        for record in records
        if record.get("_human_policy") == "location_restricted"
    ]

    assert all(
        isinstance(record.get("_human_travel_days"), int) for record in travel_records
    )
    assert all(
        "location_restrictions" in record for record in location_restricted_records
    )
