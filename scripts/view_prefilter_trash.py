#!/usr/bin/env python3
"""View prefilter-trashed jobs in a human-readable format.

Usage:
    uv run scripts/view_prefilter_trash.py [RUN_DATE]
    uv run scripts/view_prefilter_trash.py 2026-05-25 --reason banned_term
    uv run scripts/view_prefilter_trash.py 2026-05-25 --summary
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date

TRASH_DIR = Path("data/trash")


def load_trash(run_date: str) -> list[dict]:
    path = TRASH_DIR / run_date / "prefilter_trash.jsonl"
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def print_summary(jobs: list[dict]):
    reasons: dict[str, int] = {}
    sources: dict[str, int] = {}
    companies: dict[str, int] = {}
    for j in jobs:
        r = j.get("_prefilter_reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1
        sources[j.get("source", "unknown")] = (
            sources.get(j.get("source", "unknown"), 0) + 1
        )
        companies[j.get("company", "unknown")] = (
            companies.get(j.get("company", "unknown"), 0) + 1
        )

    print(f"\nTotal rejected: {len(jobs)}\n")
    print("By reason:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {c:4d}  {r}")

    print("\nBy source:")
    for s, c in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {c:4d}  {s}")

    print("\nTop companies:")
    for co, c in sorted(companies.items(), key=lambda x: -x[1])[:20]:
        print(f"  {c:4d}  {co}")


def print_jobs(jobs: list[dict]):
    for i, j in enumerate(jobs, 1):
        reason = j.get("_prefilter_reason", "unknown")
        meta = j.get("_prefilter_metadata", {})
        matched = meta.get("matched_rules", [])
        trace = meta.get("rule_trace", [])
        dedup_hash = j.get("dedup_hash", "?")

        print(f"\n{'─' * 72}")
        print(f"  {i:3d}. [{reason}] {j.get('title', '?')} @ {j.get('company', '?')}")
        print(
            f"      {j.get('location', '?')}  |  source={j.get('source', '?')}  |  posted={j.get('posted_at', '?')}"
        )
        if matched:
            print(f"      rules: {', '.join(matched)}")
        if trace:
            print(f"      trace: {' → '.join(trace)}")
        if dedup_hash != "?":
            print(f"      dedup_hash: {dedup_hash}")
        url = j.get("source_url", "")
        if url:
            print(f"      {url}")


def main():
    parser = argparse.ArgumentParser(description="View prefilter-trashed jobs")
    parser.add_argument(
        "run_date",
        nargs="?",
        default=date.today().isoformat(),
        help="Run date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--reason", "-r", help="Filter by reject reason (e.g. banned_term)"
    )
    parser.add_argument(
        "--summary", "-s", action="store_true", help="Show summary only"
    )
    parser.add_argument(
        "--companies",
        "-c",
        action="store_true",
        help="Show unique companies per reason",
    )
    args = parser.parse_args()

    jobs = load_trash(args.run_date)

    if args.reason:
        jobs = [j for j in jobs if j.get("_prefilter_reason") == args.reason]
        print(f"Filtered to reason='{args.reason}': {len(jobs)} jobs\n")

    if args.summary:
        print_summary(jobs)
        return

    if args.companies:
        by_reason: dict[str, set[str]] = {}
        for j in jobs:
            r = j.get("_prefilter_reason", "unknown")
            by_reason.setdefault(r, set()).add(j.get("company", "?"))
        for r in sorted(by_reason):
            print(f"\n[{r}] ({len(by_reason[r])} companies)")
            for co in sorted(by_reason[r]):
                print(f"  {co}")
        return

    print(f"Run: {args.run_date}  |  {len(jobs)} rejected jobs\n")

    print_jobs(jobs)

    # print the summary at the end as well for convenience
    print_summary(jobs)


if __name__ == "__main__":
    main()
