#!/usr/bin/env python3
"""Sample production remote-filter classifications into HITL review staging.

The remote-filter gold flow no longer uses a separate teacher/bootstrap prompt.
Run the production classifier first, then sample its classified output for human
ratification in ``src/review_ui/app.py``.

Usage:
    uv run scripts/sample_for_review.py --n 50
    uv run scripts/sample_for_review.py --source data/filtered/2026-06-08/remote_filter_classified.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = Path("data/filtered/remote_filter_classified.jsonl")
DEFAULT_TARGET = Path("data/staging/to_review.jsonl")
DEFAULT_GOLD = Path("data/eval/ground_truth.jsonl")

log = logging.getLogger(__name__)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def dedup_key(record: dict[str, Any]) -> str | None:
    value = (
        record.get("dedup_hash")
        or record.get("source_job_id")
        or record.get("source_url")
    )
    return str(value) if value else None


def reviewed_keys(gold_path: Path) -> set[str]:
    if not gold_path.exists():
        return set()
    keys: set[str] = set()
    for record in load_jsonl(gold_path):
        key = dedup_key(record)
        if key:
            keys.add(key)
    return keys


def _record_label(record: dict[str, Any], index: int) -> str:
    title = record.get("title") or "<untitled>"
    company = record.get("company") or "<unknown company>"
    return f"#{index} {title} @ {company}"


def eligible_records(
    records: list[dict[str, Any]], reviewed: set[str], include_reviewed: bool
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    missing_key_records: list[str] = []
    missing_analysis_records: list[str] = []
    for index, record in enumerate(records, start=1):
        has_analysis = isinstance(record.get("_remote_analysis"), dict)
        key = dedup_key(record)
        if not key:
            if has_analysis:
                missing_key_records.append(_record_label(record, index))
            continue
        if key in seen:
            continue
        seen.add(key)
        if not has_analysis:
            # A keyed classified row with no `_remote_analysis` is malformed
            # upstream — the production classifier should have attached it.
            # Surface it rather than drop it silently (fail loud, per CLAUDE.md).
            missing_analysis_records.append(_record_label(record, index))
            continue
        if not include_reviewed and key in reviewed:
            continue
        eligible.append(record)
    if missing_key_records:
        log.warning(
            "Skipped %d classified review candidates without a stable dedup key "
            "(dedup_hash, source_job_id, or source_url): %s",
            len(missing_key_records),
            "; ".join(missing_key_records[:5]),
        )
    if missing_analysis_records:
        log.warning(
            "Skipped %d classified review candidates missing _remote_analysis "
            "(production classifier output is required for HITL review): %s",
            len(missing_analysis_records),
            "; ".join(missing_analysis_records[:5]),
        )
    return eligible, missing_key_records, missing_analysis_records


def sample_records(
    records: list[dict[str, Any]], n: int, seed: int | None = None
) -> list[dict[str, Any]]:
    if n < 1:
        raise ValueError("sample size must be >= 1")
    rng = random.Random(seed)
    if n >= len(records):
        sampled = list(records)
        rng.shuffle(sampled)
        return sampled
    return rng.sample(records, n)


def create_review_sample(
    source_path: Path = DEFAULT_SOURCE,
    target_path: Path = DEFAULT_TARGET,
    *,
    n: int = 50,
    gold_path: Path = DEFAULT_GOLD,
    seed: int | None = None,
    include_reviewed: bool = False,
) -> list[dict[str, Any]]:
    source_records = load_jsonl(source_path)
    reviewed = reviewed_keys(gold_path) if not include_reviewed else set()
    eligible, missing_key_records, missing_analysis_records = eligible_records(
        source_records, reviewed, include_reviewed
    )
    if not eligible:
        details = []
        if missing_key_records:
            details.append(
                "classified rows missing stable keys: "
                + "; ".join(missing_key_records[:5])
            )
        if missing_analysis_records:
            details.append(
                "classified rows missing _remote_analysis: "
                + "; ".join(missing_analysis_records[:5])
            )
        detail = ("; " + "; ".join(details)) if details else ""
        raise ValueError(
            f"No eligible records in {source_path}; expected production-classified "
            f"rows with _remote_analysis{detail}"
        )
    sample = sample_records(eligible, n, seed)
    write_jsonl(target_path, sample)
    return sample


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--n", type=int, default=50, help="Records to sample")
    parser.add_argument("--seed", type=int, help="Random seed for reproducible samples")
    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="Allow records already present in the gold file",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    sample = create_review_sample(
        args.source,
        args.output,
        n=args.n,
        gold_path=args.gold,
        seed=args.seed,
        include_reviewed=args.include_reviewed,
    )
    print(f"Wrote {len(sample)} records → {args.output}")
    print("Next: uv run streamlit run src/review_ui/app.py")


if __name__ == "__main__":
    main()
