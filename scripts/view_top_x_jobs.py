#!/usr/bin/env python3
"""Print top jobs from a scored JSONL file to Markdown, sorted by fit score.

Compliant with strict markdownlint spacing regulations and escapes math symbols
to prevent downstream KaTeX / ParseError bugs.

Usage:
    uv run scripts/view_top_20_jobs.py > review_report.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCORE_FIELD = "_skills_fit_score"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-date",
        type=Path,
        help="Date of the run (format: YYYY-MM-DD) to infer the path to the scored JSONL file",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Starting index for slicing the records (default: 0)",
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


def sanitize_markdown(text: str) -> str:
    """Escapes raw dollar signs to prevent Markdown engines from failing on KaTeX math parses."""
    if not text:
        return ""
    # Look for dollar signs and escape them if they aren't already escaped
    return re.sub(r"(?<!\\)\$", r"\$", text)


def main() -> None:
    args = parse_args()

    if not args.run_date:
        print("Error: --run-date is required", file=sys.stderr)
        sys.exit(1)

    path = Path(f"data/scored/{args.run_date}/skills_fit_scored.jsonl")
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict] = []
    with open(path) as f:
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
    shown = rows[args.start : args.start + args.limit]

    if not shown:
        print("# No matching records found.\n")
        return

    # Print Report Header (MD022)
    print("# Skills Fit Analysis Report\n")
    print(
        f"Showing **{len(shown)}** of **{total}** total records from `{path.name}`.\n"
    )
    print("---")

    for i, r in enumerate(shown):
        slice_index = args.start + i + 1
        score = r.get(SCORE_FIELD, "?")
        title = r.get("title", "Unknown Title")
        company = r.get("company", "Unknown Company")
        dedup = r.get("dedup_hash", "NoHash")

        # Extract and sanitize fields that might contain financial figures
        rationale = sanitize_markdown(
            r.get("_skills_fit_rationale", "No rationale provided.")
        )
        confidence = r.get("_skills_fit_confidence", "N/A").upper()

        # FIX: Extract core_job_duties from the nested analysis dictionary
        analysis_data = r.get("_skills_fit_analysis", {})
        core_job_duties = analysis_data.get("core_job_duties", [])

        matches = [sanitize_markdown(m) for m in r.get("_skills_fit_top_matches", [])]
        gaps = [sanitize_markdown(g) for g in r.get("_skills_fit_gaps", [])]
        concerns = [
            sanitize_markdown(c) for c in r.get("_skills_fit_hard_concerns", [])
        ]

        url = r.get("source_url") or r.get("url") or "N/A"
        location = r.get("location", "N/A")

        remote_analysis = r.get("_remote_analysis", {})
        classification = remote_analysis.get("remote_classification", "UNKNOWN").upper()

        if score and str(score).isdigit():
            s_val = int(score)
            status_indicator = "🟢" if s_val >= 4 else ("🟡" if s_val == 3 else "🔴")
        else:
            status_indicator = "⚪"

        # Record Header Block (MD022)
        print(
            f"## {status_indicator} [Score {score}] {title} @ {company} [{slice_index} of {len(rows)}]\n"
        )

        # Metadata List (MD032)
        print(f"- **Scrape Date:** {args.run_date}")
        print(f"- **Confidence:** {confidence}")
        print(f"- **Location:** {location}")
        print(f"- **Classification:** {classification}")
        print(f"- **Hash:** `{dedup}`")
        print(f"- **URL:** {url}\n")

        # Full Job Description Block
        print("> **Full Job Description**\n>")
        raw_desc = sanitize_markdown(
            r.get("description", "No description text.")
        ).strip()
        for block in raw_desc.split("\n"):
            block = block.strip()
            if block:
                print(f"> {block}")
            else:
                print(">")
        print()  # Ends blockquote block safely

        # Rationale Blockquote
        clean_rationale = rationale.strip().replace("\n", "\n> ")
        print(f"> **Rationale**\n>\n> {clean_rationale}\n")

        # Model identified core job duties (MD032 & MD036 Compliant layout)
        print("- **Core Job Duties Identified by Model:**")
        if core_job_duties:
            for duty in core_job_duties:
                print(f"  - {sanitize_markdown(duty)}")
        else:
            print("  - No core duties identified.")
        print()  # Spacing after duties list block

        # Combined List Structure
        has_analysis_details = bool(matches or gaps or concerns)
        if has_analysis_details:
            print("- **Analysis Details:**")

            if matches:
                print("  - **Job Fit Successes:**")
                for match in matches:
                    print(f"    - {match}")

            if gaps:
                print("  - **Identified Gaps:**")
                for gap in gaps:
                    print(f"    - {gap}")

            if concerns:
                print("  - **Critical Concerns:**")
                for concern in concerns:
                    print(f"    - {concern}")

            print()  # Closes list block cleanly

        # Visual Markdown Horizontal Divider
        print("---")


if __name__ == "__main__":
    main()
