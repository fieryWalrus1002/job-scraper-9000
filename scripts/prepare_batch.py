#!/usr/bin/env python3
"""
Build an OpenAI Batch API request file from raw scraped job records.

Accepts a single JSONL file or a directory of JSONL files. When given a
directory, all *.jsonl files are read in sorted order — the same order
merge_batch_results.py must use so that custom_id = "job-{idx}" maps back
correctly.

Usage:
    python scripts/prepare_batch.py                          # reads data/raw/
    python scripts/prepare_batch.py --input data/raw/2026-05-11_linkedin.jsonl
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from utils.git_info import get_prompt_hash  # noqa: E402

INPUT_DIR = "data/raw"
BATCH_FILE = "data/batch/gpt_teacher_batch.jsonl"
MODEL = "gpt-4o"

PROMPT_FILE = Path(__file__).parents[1] / "prompts" / "remote_agent_teacher" / "system_prompt_v1.txt"


def iter_jobs(input_path: Path):
    """Yield (idx, job_dict) across one file or all *.jsonl files in a directory."""
    if input_path.is_dir():
        files = sorted(input_path.glob("*.jsonl"))
        if not files:
            raise FileNotFoundError(f"No .jsonl files found in {input_path}")
    else:
        files = [input_path]

    idx = 0
    for file in files:
        with open(file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield idx, json.loads(line)
                idx += 1


def generate_batch(input_path: Path, output_path: Path) -> None:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")
    system_prompt = PROMPT_FILE.read_text()
    prompt_hash = get_prompt_hash(PROMPT_FILE)
    print(f"Prompt: {PROMPT_FILE.name}  sha256:{prompt_hash}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(output_path, "w") as outfile:
        for idx, job in iter_jobs(input_path):
            request = {
                "custom_id": f"job-{idx}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": MODEL,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": job.get("description", "")},
                    ],
                },
            }
            outfile.write(json.dumps(request) + "\n")
            count += 1

    print(f"Created {count} requests → {output_path}")
    print("Upload this file to the OpenAI Batch API dashboard, then download the results.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default=INPUT_DIR, help="JSONL file or directory of JSONL files (default: data/raw/)")
    p.add_argument("--output", default=BATCH_FILE, help="Batch request output path (default: data/batch/gpt_teacher_batch.jsonl)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    generate_batch(input_path, Path(args.output))
