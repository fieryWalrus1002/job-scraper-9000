#!/usr/bin/env python3
"""Pick N records per teacher-predicted band from the proposed pool.

Reads data/staging/skills_fit_seed_proposed.jsonl, groups by
_teacher_fit_score (1-5), randomly samples --per-band from each band, and
writes the selection to a new template JSONL ready for the renderer.

Records already in the gold JSONL (by source_job_id) are excluded so a
re-selection won't re-render records you've already reviewed.

When a band has fewer records than --per-band, all available are kept and a
warning is printed — the upstream pool just doesn't have enough of that band.

Usage:
    uv run scripts/select_skills_fit_review.py --per-band 5
    uv run scripts/select_skills_fit_review.py --per-band 6 --out data/staging/skills_fit_review_template.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_PROPOSED = Path("data/staging/skills_fit_seed_proposed.jsonl")
DEFAULT_GOLD = Path("data/eval/skills_fit_ground_truth.jsonl")
DEFAULT_OUT = Path("data/staging/skills_fit_review_template.jsonl")

VALID_SCORES = (1, 2, 3, 4, 5)


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


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--proposed", default=str(DEFAULT_PROPOSED))
    p.add_argument("--gold", default=str(DEFAULT_GOLD))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument(
        "--per-band", type=int, default=5, help="Records per band 1-5 (default: 5)"
    )
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()

    proposed_path = Path(args.proposed)
    gold_path = Path(args.gold)
    out_path = Path(args.out)

    proposed = load_jsonl(proposed_path)
    if not proposed:
        print(f"No proposed records in {proposed_path}", file=sys.stderr)
        sys.exit(1)

    gold = load_jsonl(gold_path)
    scored_ids = {r.get("source_job_id") for r in gold if r.get("source_job_id")}

    by_band: dict[int, list[dict]] = defaultdict(list)
    for r in proposed:
        sid = r.get("source_job_id")
        score = r.get("_teacher_fit_score")
        if sid in scored_ids:
            continue
        if score not in VALID_SCORES:
            continue
        by_band[score].append(r)

    if args.seed is not None:
        random.seed(args.seed)

    selected: list[dict] = []
    print(f"proposed:    {proposed_path}  ({len(proposed)} records)")
    print(f"gold:        {gold_path}  ({len(scored_ids)} already reviewed, excluded)")
    print(f"per-band:    {args.per_band}")
    print()
    print("Band | available | picked")
    print("---- | --------- | ------")
    for band in VALID_SCORES:
        pool = by_band.get(band, [])
        take = min(args.per_band, len(pool))
        picks = random.sample(pool, take) if take else []
        selected.extend(picks)
        flag = "  <-- short" if take < args.per_band else ""
        print(f"  {band}  |    {len(pool):4d}   |  {take:3d}{flag}")
    print()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for r in selected:
            f.write(json.dumps(r) + "\n")

    print(f"Wrote {len(selected)} records to {out_path}")
    print()
    print("Next:")
    print("  rm -rf data/staging/skills_fit_review/")
    print(f"  uv run scripts/render_skills_fit_review_md.py --in {out_path}")


if __name__ == "__main__":
    main()
