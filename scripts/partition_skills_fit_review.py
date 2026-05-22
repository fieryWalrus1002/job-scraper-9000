#!/usr/bin/env python3
"""Pick a stratified overlap subset of an existing review pool and copy the
matching markdowns to a second reviewer's directory.

Use this when you want N reviewers to score an overlapping subset of the
same records so you can measure inter-rater reliability (IRR). The first
reviewer gets the full pool; subsequent reviewers get this stratified
subset.

The picked .md files are *copied* (not moved) — the source dir stays intact
for the first reviewer. The two reviewers work independently in separate
directories; their reviews are then parsed into reviewer-tagged gold JSONLs
and compared.

Usage:
    uv run scripts/partition_skills_fit_review.py \\
      --source-dir data/staging/skills_fit_review_2026-05-21_pool_a \\
      --target-dir data/staging/skills_fit_review_2026-05-21_pool_b \\
      --per-band 1 --seed 42
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import yaml

DEFAULT_TEMPLATE = Path("data/staging/skills_fit_review_template.jsonl")

VALID_SCORES = (1, 2, 3, 4, 5)
YAML_BLOCK_RE = re.compile(r"## YOUR REVIEW.*?```yaml\n(.*?)\n```", re.DOTALL)


def load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def index_md_by_source_id(md_dir: Path) -> dict[str, Path]:
    """Map source_job_id → .md path by reading each file's YAML block."""
    index: dict[str, Path] = {}
    for md_path in sorted(md_dir.glob("*.md")):
        text = md_path.read_text()
        m = YAML_BLOCK_RE.search(text)
        if not m:
            continue
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        sid = (data or {}).get("source_job_id")
        if sid:
            index[sid] = md_path
    return index


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source-dir", required=True)
    p.add_argument("--target-dir", required=True)
    p.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    p.add_argument("--per-band", type=int, default=1, help="Records per band 1-5 (default: 1)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="Show picks but don't copy")
    args = p.parse_args()

    source_dir = Path(args.source_dir)
    target_dir = Path(args.target_dir)
    template_path = Path(args.template)

    if not source_dir.is_dir():
        print(f"Source dir not found: {source_dir}", file=sys.stderr)
        sys.exit(1)
    if not template_path.exists():
        print(f"Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)
    if target_dir.exists() and any(target_dir.iterdir()):
        print(f"Target dir already exists and is non-empty: {target_dir}", file=sys.stderr)
        print("Refusing to overwrite. Remove it first if you want to repartition.", file=sys.stderr)
        sys.exit(1)

    template = load_jsonl(template_path)
    md_index = index_md_by_source_id(source_dir)

    by_band: dict[int, list[dict]] = defaultdict(list)
    missing_md: list[str] = []
    for rec in template:
        sid = rec.get("source_job_id")
        score = rec.get("_teacher_fit_score")
        if score not in VALID_SCORES:
            continue
        if sid not in md_index:
            missing_md.append(f"{sid} (score {score})")
            continue
        by_band[score].append(rec)

    if missing_md:
        print(
            f"Warning: {len(missing_md)} template records have no matching .md "
            f"in {source_dir}:",
            file=sys.stderr,
        )
        for entry in missing_md:
            print(f"  - {entry}", file=sys.stderr)

    if args.seed is not None:
        import random

        random.seed(args.seed)
    import random as _r

    picks: list[dict] = []
    print(f"source dir:   {source_dir}")
    print(f"target dir:   {target_dir}")
    print(f"template:     {template_path}")
    print(f"per-band:     {args.per_band}")
    print()
    print("Band | available | picked")
    print("---- | --------- | ------")
    for band in VALID_SCORES:
        pool = by_band.get(band, [])
        take = min(args.per_band, len(pool))
        chosen = _r.sample(pool, take) if take else []
        picks.extend(chosen)
        flag = "  <-- short" if take < args.per_band else ""
        print(f"  {band}  |    {len(pool):4d}   |  {take:3d}{flag}")
    print()
    print(f"Total picked: {len(picks)}")
    print()

    if not args.dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for rec in picks:
        src_md = md_index[rec["source_job_id"]]
        dst_md = target_dir / src_md.name
        if args.dry_run:
            print(f"  would copy {src_md.name}  (score {rec['_teacher_fit_score']})")
        else:
            shutil.copy2(src_md, dst_md)
            print(f"  copied {src_md.name}  (score {rec['_teacher_fit_score']})")

    if args.dry_run:
        print()
        print("(dry-run — nothing copied)")
    else:
        print()
        print(f"Done. {len(picks)} files in {target_dir}")
        print()
        print("Next: send target dir to reviewer B. After both reviewers return:")
        print(f"  uv run scripts/parse_skills_fit_review_md.py \\")
        print(f"    --review-dir {source_dir} \\")
        print(f"    --gold data/eval/skills_fit_gold_a.jsonl")
        print(f"  uv run scripts/parse_skills_fit_review_md.py \\")
        print(f"    --review-dir {target_dir} \\")
        print(f"    --gold data/eval/skills_fit_gold_b.jsonl")


if __name__ == "__main__":
    main()
