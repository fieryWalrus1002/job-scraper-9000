#!/usr/bin/env python3
"""Pretty-print top jobs from a scored JSONL file, sorted by fit score.

Usage:
    uv run scripts/view_top_20_jobs.py
    uv run scripts/view_top_20_jobs.py --score 5       # only score 5
    uv run scripts/view_top_20_jobs.py --min-score 4   # score >= 4
    uv run scripts/view_top_20_jobs.py --limit 50      # show 50 instead of 20
    uv run scripts/view_top_20_jobs.py --path data/scored/2026-05-24/skills_fit_scored.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PATH = Path("data/scored/2026-05-25/skills_fit_scored.jsonl")
SCORE_FIELD = "_skills_fit_score"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PATH,
        help="Path to scored JSONL file (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Number of records to show (default: 20)",
    )
    parser.add_argument(
        "--score",
        type=int,
        default=None,
        help="Show only records with exactly this score",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="Show only records with score >= this value",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.path.exists():
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict] = []
    with open(args.path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    total = len(rows)

    # Filter
    if args.score is not None:
        rows = [r for r in rows if r.get(SCORE_FIELD) == args.score]
    if args.min_score is not None:
        rows = [r for r in rows if (r.get(SCORE_FIELD) or 0) >= args.min_score]

    # Sort by score descending
    rows.sort(key=lambda r: r.get(SCORE_FIELD) or 0, reverse=True)

    # Slice
    shown = rows[: args.limit]

    if not shown:
        print("No matching records.")
        return

    # Print
    for r in shown:
        score = r.get(SCORE_FIELD, "?")
        title = r.get("title", "?")
        company = r.get("company", "?")
        dedup = r.get("dedup_hash", "?")[:16]
        gaps = r.get("_skills_fit_gaps", [])
        concerns = r.get("_skills_fit_hard_concerns", [])

        print(f"Score: {score}  |  {title}  @  {company}")
        print(f"       {dedup}...")
        if gaps:
            print(f"       Gaps: {', '.join(gaps)}")
        if concerns:
            print(f"       Concerns: {', '.join(concerns)}")
        print()

    print(f"Showing {len(shown)} of {total} records")


if __name__ == "__main__":
    main()
