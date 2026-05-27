#!/usr/bin/env python3
"""Run a teacher LLM over the skills_fit seed template, write proposals.

Reads data/staging/skills_fit_seed_template.jsonl, calls analyze_skills_fit()
for each record, and writes each record to data/staging/skills_fit_seed_proposed.jsonl
with _teacher_* fields populated. The hand-scorer reads the proposed file when
present and shows the teacher's labels alongside the posting so the human
reviewer can accept, flip, or edit rather than score from blank.

Resume-safe: re-running skips records whose source_job_id is already in the
output file.

Usage:
    uv run scripts/propose_skills_fit_seed.py --model gpt-4o
    uv run scripts/propose_skills_fit_seed.py --limit 5     # smoke test
"""

from __future__ import annotations

import argparse
import json
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

DEFAULT_IN = Path("data/staging/skills_fit_seed_template.jsonl")
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


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--in", dest="input", default=str(DEFAULT_IN))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument(
        "--model", default=None, help="Override the model in the config (e.g. gpt-4o)"
    )
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument(
        "--prompt",
        default=None,
        help=f"Override the system prompt file (default: {SKILLS_FIT_PROMPT_PATH})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of records (smoke testing)",
    )
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.out)
    config_path = Path(args.config)
    prompt_path = Path(args.prompt) if args.prompt else SKILLS_FIT_PROMPT_PATH

    if not in_path.exists():
        print(f"Template not found: {in_path}", file=sys.stderr)
        sys.exit(1)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    if not prompt_path.exists():
        print(f"Prompt not found: {prompt_path}", file=sys.stderr)
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

    candidates = load_jsonl(in_path)
    existing = load_jsonl(out_path)
    done_ids = {r.get("source_job_id") for r in existing if r.get("source_job_id")}
    remaining = [c for c in candidates if c.get("source_job_id") not in done_ids]
    if args.limit is not None:
        remaining = remaining[: args.limit]

    print(f"template:   {in_path}  ({len(candidates)} candidates)")
    print(f"output:     {out_path}  ({len(existing)} already proposed)")
    print(f"to propose: {len(remaining)}")
    print(f"model:      {llm_config.get('model', '<default>')}")
    print(f"profile:    {profile_path}  (version: {profile_version})")
    print(f"prompt:     {prompt_path}")
    print()

    failures = 0
    for idx, rec in enumerate(remaining, start=1):
        title = rec.get("title", "<no title>")
        company = rec.get("company", "")
        print(f"[{idx}/{len(remaining)}] {title} @ {company}", flush=True)

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
    print(f"Done. {len(remaining) - failures} proposed, {failures} failed.")
    print(f"Output: {out_path}")
    print()
    print("Next: uv run scripts/score_skills_fit_seed.py")


if __name__ == "__main__":
    main()
