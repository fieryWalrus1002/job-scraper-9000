import pytest

from scripts.remap_gold_to_4way import remap_records


def test_legacy_remap_preserves_existing_travel_days_for_non_travel_policy():
    records = [
        {
            "dedup_hash": "sel",
            "_human_policy": "onsite",
            "_human_travel_days": 187,
            "response": {"estimated_travel_days_per_year": None},
        }
    ]

    remap_records(records)

    assert records[0]["_human_classification"] == "onsite"
    assert records[0]["_human_travel_days"] == 187


def test_legacy_remap_rejects_retired_unclear_policy():
    records = [{"dedup_hash": "unclear", "_human_policy": "unclear"}]

    with pytest.raises(ValueError, match="unexpected _human_policy 'unclear'"):
        remap_records(records)
