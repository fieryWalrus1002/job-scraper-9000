#!/usr/bin/env python3
"""Legacy-remap remote-filter gold labels to the canonical 3-way axis.

This is a one-time migration helper for historical gold records that still carry
legacy fine-grained ``_human_policy`` values from the retired teacher bootstrap.
It derives ``_human_classification`` from ``_human_policy`` and backfills
structured fields when legacy teacher analysis is present.

Usage:
    uv run scripts/remap_gold_to_4way.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_GOLD = Path("data/eval/ground_truth.jsonl")

POLICY_TO_CLASSIFICATION = {
    "fully_remote": "remote",
    "remote": "remote",
    "onsite": "onsite",
    "hybrid": "hybrid",
    "onsite_disguised": "onsite",
    "location_restricted": "remote",
    "remote_with_monthly_travel": "remote",
    "remote_with_frequent_travel": "remote",
}

TRAVEL_POLICIES = {
    "remote_with_monthly_travel",
    "remote_with_frequent_travel",
}
LOCATION_RESTRICTED_POLICY = "location_restricted"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"Invalid record on {path}:{line_number}: expected object, "
                    f"got {type(record).__name__}"
                )
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _record_id(record: dict[str, Any], index: int) -> str:
    return str(record.get("dedup_hash") or record.get("source_job_id") or index)


def extract_remote_analysis(record: dict[str, Any], index: int) -> dict[str, Any]:
    """Return the legacy teacher/production RemoteAnalysis dict when present."""
    response = record.get("response")
    if not isinstance(response, dict):
        raise ValueError(
            f"Record {_record_id(record, index)} has response "
            f"{type(response).__name__}, expected object"
        )

    if (
        "estimated_travel_days_per_year" in response
        or "location_restrictions" in response
    ):
        return response

    try:
        content = response["body"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"Record {_record_id(record, index)} response does not contain a "
            "RemoteAnalysis dict or batch message content"
        ) from exc

    if not isinstance(content, str):
        raise ValueError(
            f"Record {_record_id(record, index)} batch message content is "
            f"{type(content).__name__}, expected str"
        )

    try:
        analysis = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Record {_record_id(record, index)} has invalid RemoteAnalysis JSON in "
            f"response content: {exc}"
        ) from exc

    if not isinstance(analysis, dict):
        raise ValueError(
            f"Record {_record_id(record, index)} RemoteAnalysis content is "
            f"{type(analysis).__name__}, expected object"
        )
    return analysis


def remap_records(
    records: list[dict[str, Any]],
) -> tuple[Counter[tuple[str, str]], list[str]]:
    remap_counts: Counter[tuple[str, str]] = Counter()
    travel_none_records: list[str] = []

    for index, record in enumerate(records, start=1):
        policy = record.get("_human_policy")
        # Type-check before the dict membership test: a non-hashable policy
        # (list/dict) would raise a bare TypeError on `in` instead of this
        # helpful ValueError.
        if not isinstance(policy, str):
            raise ValueError(
                f"Record {_record_id(record, index)} has non-string _human_policy "
                f"{policy!r}"
            )
        if policy not in POLICY_TO_CLASSIFICATION:
            raise ValueError(
                f"Record {_record_id(record, index)} has unexpected _human_policy "
                f"{policy!r}"
            )

        classification = POLICY_TO_CLASSIFICATION[policy]
        record["_human_classification"] = classification
        remap_counts[(policy, classification)] += 1

        if "_human_travel_days" not in record:
            if policy in TRAVEL_POLICIES:
                analysis = extract_remote_analysis(record, index)
                travel_days = analysis.get("estimated_travel_days_per_year")
                if travel_days is None:
                    record["_human_travel_days"] = None
                    travel_none_records.append(_record_id(record, index))
                elif isinstance(travel_days, int) and not isinstance(travel_days, bool):
                    record["_human_travel_days"] = travel_days
                else:
                    raise ValueError(
                        f"Record {_record_id(record, index)} has invalid "
                        "response.estimated_travel_days_per_year "
                        f"{travel_days!r}; expected int or None"
                    )
            else:
                record["_human_travel_days"] = None

        if policy == LOCATION_RESTRICTED_POLICY:
            analysis = extract_remote_analysis(record, index)
            location_restrictions = analysis.get("location_restrictions")
            if not isinstance(location_restrictions, list):
                raise ValueError(
                    f"Record {_record_id(record, index)} has invalid "
                    "response.location_restrictions "
                    f"{location_restrictions!r}; expected list"
                )
            record["location_restrictions"] = location_restrictions

    return remap_counts, travel_none_records


def print_summary(
    remap_counts: Counter[tuple[str, str]], travel_none_records: list[str]
) -> None:
    print("Remap summary:")
    for (source, target), count in sorted(remap_counts.items()):
        print(f"  {source} -> {target}: {count}")
    if travel_none_records:
        print("Travel rows with response.estimated_travel_days_per_year=None:")
        for record_id in travel_none_records:
            print(f"  {record_id}")
    else:
        print("Travel rows with response.estimated_travel_days_per_year=None: 0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    args = parser.parse_args()

    if not args.gold.exists():
        raise FileNotFoundError(f"Gold file not found: {args.gold}")

    records = load_jsonl(args.gold)
    remap_counts, travel_none_records = remap_records(records)
    write_jsonl(args.gold, records)
    print_summary(remap_counts, travel_none_records)
    print(f"Updated {len(records)} records in {args.gold}")


if __name__ == "__main__":
    main()
