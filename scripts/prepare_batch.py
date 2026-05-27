#!/usr/bin/env python3
"""
Build an OpenAI Batch API request file from raw scraped job records.

Always writes two files into the run directory (default: data/batch/YYYY-MM-DD/):
  gpt_teacher_batch.jsonl  — the request file to upload to OpenAI
  gpt_teacher_jobs.jsonl   — the exact jobs that went in, in order
                              (merge_batch_results.py reads this)

The sidecar eliminates the need to pass matching --input flags to both scripts.

Usage:
    # random sample of 100 jobs from all of data/raw/ (recommended)
    python scripts/prepare_batch.py --sample 100

    # specific file, no sampling
    python scripts/prepare_batch.py --input data/raw/2026-05-11_linkedin_ai-engineer.jsonl

    # custom run directory (e.g. re-running yesterday's batch)
    python scripts/prepare_batch.py --sample 100 --run-dir data/batch/2026-05-11
"""

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from utils.git_info import get_prompt_hash  # noqa: E402

INPUT_DIR = "data/raw"
DEFAULT_RUN_DIR = f"data/batch/{date.today().isoformat()}"
MODEL = "gpt-4o"

PROMPT_FILE = (
    Path(__file__).parents[1] / "prompts" / "remote_agent_teacher" / "system_prompt.txt"
)


def load_all_jobs(input_path: Path) -> list[dict]:
    """Load every job from one file or all *.jsonl files in a directory."""
    if input_path.is_dir():
        files = sorted(input_path.glob("*.jsonl"))
        if not files:
            raise FileNotFoundError(f"No .jsonl files found in {input_path}")
    else:
        files = [input_path]

    jobs = []
    for file in files:
        with open(file) as f:
            for line in f:
                line = line.strip()
                if line:
                    jobs.append(json.loads(line))
    return jobs


def _build_user_content(job: dict) -> str:
    parts = []
    if title := job.get("title"):
        parts.append(f"Job title: {title}")
    if location := job.get("location"):
        parts.append(f"Location field: {location}")
    search_params = job.get("search_params") or {}
    ctx = []
    if kw := search_params.get("keywords"):
        ctx.append(f'keywords="{kw}"')
    if wp := search_params.get("workplace"):
        ctx.append(f"workplace_filter={wp}")
    if jt := search_params.get("job_type"):
        ctx.append(f"job_type={jt}")
    if ctx:
        parts.append(f"Search context: {', '.join(ctx)}")
    description = job.get("description", "")
    if parts:
        return "\n".join(f"[{p}]" for p in parts) + "\n\n---\n\n" + description
    return description


def generate_batch(input_path: Path, run_dir: Path, sample: int | None) -> None:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")
    system_prompt = PROMPT_FILE.read_text()
    prompt_hash = get_prompt_hash(PROMPT_FILE)
    print(f"Prompt: {PROMPT_FILE.name}  sha256:{prompt_hash}")

    jobs = load_all_jobs(input_path)
    print(f"Loaded {len(jobs)} jobs from {input_path}")

    if sample is not None:
        if sample > len(jobs):
            print(f"Warning: --sample {sample} > available {len(jobs)}, using all")
            sample = len(jobs)
        jobs = random.sample(jobs, sample)
        print(f"Sampled {len(jobs)} jobs at random")

    run_dir.mkdir(parents=True, exist_ok=True)
    batch_path = run_dir / "gpt_teacher_batch.jsonl"
    sidecar_path = run_dir / "gpt_teacher_jobs.jsonl"

    with open(sidecar_path, "w") as sidecar_f, open(batch_path, "w") as batch_f:
        for idx, job in enumerate(jobs):
            sidecar_f.write(json.dumps(job) + "\n")
            request = {
                "custom_id": f"job-{idx}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": MODEL,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": _build_user_content(job)},
                    ],
                },
            }
            batch_f.write(json.dumps(request) + "\n")

    print(f"Wrote {len(jobs)} requests → {batch_path}")
    print(f"Wrote {len(jobs)} jobs     → {sidecar_path}")
    print(f"Next: uv run python scripts/submit_batch.py --run-dir {run_dir}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--input",
        default=INPUT_DIR,
        help="JSONL file or directory (default: data/raw/)",
    )
    p.add_argument(
        "--run-dir",
        default=DEFAULT_RUN_DIR,
        help=f"Output directory for this batch run (default: {DEFAULT_RUN_DIR})",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Randomly sample N jobs instead of using all",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    generate_batch(input_path, Path(args.run_dir), args.sample)
