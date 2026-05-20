#!/usr/bin/env python3
"""Sample candidate jobs for hand-scoring the skills_fit seed gold.

Reads remote_filter_pass.jsonl outputs, picks N diverse records, and writes
them to a template JSONL with empty _human_* fields ready to fill in.

Workflow:
    1. uv run scripts/prepare_skills_fit_seed.py --n 40 --in data/filtered/2026-05-16/
    2. Open data/staging/skills_fit_seed_template.jsonl in your editor
    3. Hand-score, aiming for 5 records per band (1-5), at least 25 total
    4. Save the scored records (drop unused candidates) to data/eval/skills_fit_ground_truth.jsonl

See specs/skills_fit_agent_plan.md Phase R step 3 for the stratification target
and the notes-discipline rules.
"""

import argparse
import json
import random
import sys
from pathlib import Path

DEFAULT_OUT = Path("data/staging/skills_fit_seed_template.jsonl")

EMPTY_HUMAN_FIELDS = {
    "_human_fit_score": None,         # int 1-5
    "_human_confidence": None,        # "low" | "medium" | "high"
    "_human_top_matches": [],
    "_human_gaps": [],
    "_human_hard_concerns": [],
    "_human_notes": "",               # REQUIRED — see Calibration section of spec
}


def load_records(path: Path) -> list[dict]:
    paths = [path] if path.is_file() else sorted(path.glob("**/*.jsonl"))
    records: list[dict] = []
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--in", dest="input",
        default="data/filtered/",
        help="File or directory of remote_filter_pass.jsonl outputs",
    )
    p.add_argument("--n", type=int, default=40, help="Candidate count to sample (default: 40)")
    p.add_argument("--out", default=str(DEFAULT_OUT), help=f"Output template path (default: {DEFAULT_OUT})")
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    records = load_records(input_path)
    if not records:
        print(f"No records found in {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.seed is not None:
        random.seed(args.seed)

    n = min(args.n, len(records))
    sampled = random.sample(records, n)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for r in sampled:
            template = {**r, **EMPTY_HUMAN_FIELDS}
            f.write(json.dumps(template) + "\n")

    print(f"Wrote {n} candidate records to {out_path}")
    print()
    print("Next: hand-score each one, aiming for 5 records per band (1-5).")
    print("Save scored records to data/eval/skills_fit_ground_truth.jsonl.")
    print("See specs/skills_fit_agent_plan.md Phase R step 3.")


if __name__ == "__main__":
    main()
