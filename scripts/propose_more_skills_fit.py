#!/usr/bin/env python3
"""Extend the skills_fit proposed set by running the teacher over more pool records.

Reads a pool directory (typically data/staging/skills_fit_pool_<date>/), finds
records not yet present in data/staging/skills_fit_seed_proposed.jsonl, and
runs the teacher on up to --n of them. Appends results to the same proposed
file. Use this to grow the proposed pool so a downstream stratified selector
(select_skills_fit_review.py) has enough high-band candidates to pick from.

Resume-safe: re-running skips records already proposed.

Usage:
    uv run scripts/propose_more_skills_fit.py --pool-dir data/staging/skills_fit_pool_2026-05-21/
    uv run scripts/propose_more_skills_fit.py --pool-dir <dir> --n 200 --model gpt-5.4
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agents.skills_fit.utils import (
    SKILLS_FIT_PROMPT_PATH,
    analyze_skills_fit,
    load_candidate_profile,
)

load_dotenv()

DEFAULT_OUT = Path("data/staging/skills_fit_seed_proposed.jsonl")
DEFAULT_CONFIG = Path("config/agent/skills_fit.yml")


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


def load_pool(pool_dir: Path) -> list[dict]:
    """Glob *.jsonl under pool_dir, dedupe by source_job_id (first wins)."""
    seen: set[str] = set()
    records: list[dict] = []
    for p in sorted(pool_dir.glob("*.jsonl")):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                sid = rec.get("source_job_id")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                records.append(rec)
    return records


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--pool-dir", required=True, help="Directory of *.jsonl pool files")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--model", default=None)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument(
        "--prompt",
        default=None,
        help=f"Override the system prompt (default: {SKILLS_FIT_PROMPT_PATH})",
    )
    p.add_argument(
        "--n",
        type=int,
        default=None,
        help="Cap number of new records to propose (default: all unproposed)",
    )
    p.add_argument("--seed", type=int, default=None, help="Random seed when --n is set")
    args = p.parse_args()

    pool_dir = Path(args.pool_dir)
    out_path = Path(args.out)
    config_path = Path(args.config)
    prompt_path = Path(args.prompt) if args.prompt else SKILLS_FIT_PROMPT_PATH

    if not pool_dir.is_dir():
        print(f"Pool dir not found: {pool_dir}", file=sys.stderr)
        sys.exit(1)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = yaml.safe_load(config_path.read_text()) or {}
    llm_config = dict(config.get("llm") or {})
    if args.model:
        llm_config["model"] = args.model
    if args.temperature is not None:
        llm_config["temperature"] = args.temperature

    profile_path = config.get("profile_file", "config/profile/candidate_profile.yml")
    profile = load_candidate_profile(profile_path)
    profile_version = profile.get("profile_version", "unknown")

    pool = load_pool(pool_dir)
    existing = load_jsonl(out_path)
    done_ids = {r.get("source_job_id") for r in existing if r.get("source_job_id")}
    unproposed = [r for r in pool if r.get("source_job_id") not in done_ids]

    if args.seed is not None:
        random.seed(args.seed)
    if args.n is not None and len(unproposed) > args.n:
        unproposed = random.sample(unproposed, args.n)

    print(f"pool dir:    {pool_dir}  ({len(pool)} unique records)")
    print(f"proposed:    {out_path}  ({len(existing)} already proposed)")
    print(f"to propose:  {len(unproposed)}")
    print(f"model:       {llm_config.get('model', '<default>')}")
    print(f"profile:     {profile_path}  (version: {profile_version})")
    print(f"prompt:      {prompt_path}")
    print()

    failures = 0
    for idx, rec in enumerate(unproposed, start=1):
        title = rec.get("title", "<no title>")
        company = rec.get("company", "")
        print(f"[{idx}/{len(unproposed)}] {title} @ {company}", flush=True)

        analysis = analyze_skills_fit(
            rec.get("description", ""),
            candidate_profile=profile,
            title=rec.get("title"),
            location=rec.get("location"),
            llm_config=llm_config,
            prompt_path=prompt_path,
        )

        if analysis is None:
            print("  ! teacher call failed — skipping", flush=True)
            failures += 1
            continue

        proposed = {
            **rec,
            "_teacher_fit_score": analysis.fit_score,
            "_teacher_confidence": analysis.confidence,
            "_teacher_score_rationale": analysis.score_rationale,
            "_teacher_top_matches": list(analysis.top_matches),
            "_teacher_gaps": list(analysis.gaps),
            "_teacher_hard_concerns": list(analysis.hard_concerns),
            "_teacher_model": llm_config.get("model"),
            "_teacher_profile_version": profile_version,
            "_teacher_prompt_file": str(prompt_path),
        }
        append_jsonl(out_path, proposed)
        print(f"  → {analysis.fit_score} ({analysis.confidence})", flush=True)

    print()
    print(f"Done. {len(unproposed) - failures} proposed, {failures} failed.")
    print(f"Output: {out_path}")
    print()
    print("Next: uv run scripts/select_skills_fit_review.py --per-band 5")


if __name__ == "__main__":
    main()
