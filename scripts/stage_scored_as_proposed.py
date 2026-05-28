#!/usr/bin/env python3
"""Promote a scored JSONL file into the proposed pool by mapping _skills_fit_* → _teacher_*.

The production run on 2026-05-27 already called the same model and prompt used
by propose_more_skills_fit.py.  Rather than paying to re-propose, we map the
scored fields directly.

Records already present in the existing proposed file (by source_job_id) are
skipped so this is safe to re-run.

Usage:
    uv run scripts/stage_scored_as_proposed.py \\
        --scored data/scored/2026-05-27/skills_fit_scored.jsonl \\
        --out    data/staging/skills_fit_seed_proposed.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_SCORED = Path("data/scored/2026-05-27/skills_fit_scored.jsonl")
DEFAULT_OUT = Path("data/staging/skills_fit_seed_proposed.jsonl")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def promote(rec: dict) -> dict:
    meta = rec.get("_skills_fit_metadata") or {}
    return {
        **rec,
        "_teacher_fit_score": rec.get("_skills_fit_score"),
        "_teacher_confidence": rec.get("_skills_fit_confidence"),
        "_teacher_score_rationale": rec.get("_skills_fit_rationale"),
        "_teacher_top_matches": list(rec.get("_skills_fit_top_matches") or []),
        "_teacher_gaps": list(rec.get("_skills_fit_gaps") or []),
        "_teacher_hard_concerns": list(rec.get("_skills_fit_hard_concerns") or []),
        "_teacher_model": meta.get("model"),
        "_teacher_profile_version": meta.get("profile_version"),
        "_teacher_prompt_file": meta.get("prompt_file"),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--scored", default=str(DEFAULT_SCORED))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument(
        "--filter-score",
        type=int,
        nargs="+",
        default=None,
        metavar="N",
        help="Only stage records with _skills_fit_score in this list (e.g. --filter-score 3 4 5)",
    )
    args = p.parse_args()

    scored_path = Path(args.scored)
    out_path = Path(args.out)

    if not scored_path.exists():
        print(f"Scored file not found: {scored_path}", file=sys.stderr)
        sys.exit(1)

    scored = load_jsonl(scored_path)
    existing = load_jsonl(out_path)
    done_ids = {r.get("source_job_id") for r in existing if r.get("source_job_id")}

    score_filter = set(args.filter_score) if args.filter_score else None

    added = skipped_dup = skipped_filter = skipped_no_score = 0
    for rec in scored:
        sid = rec.get("source_job_id")
        if sid in done_ids:
            skipped_dup += 1
            continue
        score = rec.get("_skills_fit_score")
        if score is None:
            skipped_no_score += 1
            continue
        if score_filter and score not in score_filter:
            skipped_filter += 1
            continue
        append_jsonl(out_path, promote(rec))
        done_ids.add(sid)
        added += 1

    print(f"scored file:   {scored_path}  ({len(scored)} records)")
    print(f"proposed file: {out_path}  ({len(existing)} already present)")
    print(f"added:         {added}")
    print(f"skipped (dup): {skipped_dup}")
    if skipped_filter:
        print(f"skipped (score filter): {skipped_filter}")
    if skipped_no_score:
        print(f"skipped (no score):     {skipped_no_score}")
    print()
    print("Next: uv run scripts/select_skills_fit_review.py --per-band 5")


if __name__ == "__main__":
    main()
