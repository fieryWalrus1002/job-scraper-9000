#!/usr/bin/env python3
"""
Merge an OpenAI Batch API results file back onto the original job records.

Workflow:
  1. prepare_batch.py   → data/raw/gpt_teacher_batch.jsonl   (upload to OpenAI)
  2. [download results] → data/raw/gpt_teacher_results.jsonl
  3. merge_batch_results.py → data/staging/to_review.jsonl   (what the UI reads)

The batch request file uses custom_id = "job-{line_index}" to key each record
back to the original jobs JSONL. This script inverts that mapping and emits one
merged record per job, embedding the teacher's response under the "response" key
(the shape the Streamlit review UI already expects).
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from agents.remote_filter.models import SCHEMA_VERSION  # noqa: E402
from utils.git_info import get_git_metadata, get_prompt_hash  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

JOBS_INPUT = "data/raw"
RESULTS_FILE = "data/batch/gpt_teacher_results.jsonl"
OUTPUT_FILE = "data/staging/to_review.jsonl"
PROMPT_FILE = Path(__file__).parents[1] / "prompts" / "remote_agent" / "system_prompt_v1.txt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jobs", default=JOBS_INPUT, help="JSONL file or directory of JSONL files used to build the batch (default: data/raw/)")
    p.add_argument("--results", default=RESULTS_FILE, help="Downloaded OpenAI batch results JSONL")
    p.add_argument("--output", default=OUTPUT_FILE, help="Merged staging output path")
    p.add_argument("--append", action="store_true", help="Append to output instead of overwriting")
    return p.parse_args()


def load_results(results_path: str) -> dict[str, dict]:
    """Return {custom_id: result_object} for every non-error batch result."""
    results: dict[str, dict] = {}
    errors = 0
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            custom_id = item.get("custom_id", "")
            if item.get("error"):
                log.warning("Batch error for %s: %s", custom_id, item["error"])
                errors += 1
                continue
            results[custom_id] = item.get("response", {})
    if errors:
        log.warning("%d batch items had errors and were skipped", errors)
    return results


def iter_jobs(jobs_path: Path):
    """Yield (idx, job_dict) from one file or all *.jsonl files in a directory (sorted)."""
    files = sorted(jobs_path.glob("*.jsonl")) if jobs_path.is_dir() else [jobs_path]
    idx = 0
    for file in files:
        with open(file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield idx, json.loads(line)
                idx += 1


def merge(jobs_path: Path, results: dict[str, dict], output_path: str, append: bool) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    git_meta = get_git_metadata()
    prompt_hash = get_prompt_hash(PROMPT_FILE) if PROMPT_FILE.exists() else "unknown"
    batch_meta = {
        "schema_version": SCHEMA_VERSION,
        "prompt_hash": prompt_hash,
        "prompt_file": PROMPT_FILE.name,
        "commit": git_meta["commit"],
        "dirty": git_meta["dirty"],
        "merged_at": git_meta["timestamp"],
    }
    log.info("Batch metadata: schema=%s prompt=%s commit=%s dirty=%s", SCHEMA_VERSION, prompt_hash, git_meta["commit"][:12], git_meta["dirty"])

    matched = skipped = 0
    mode = "a" if append else "w"

    with open(output_path, mode) as out_f:
        for idx, job in iter_jobs(jobs_path):
            custom_id = f"job-{idx}"
            response = results.get(custom_id)
            if response is None:
                log.warning("No result for %s (%s @ %s) — skipping", custom_id, job.get("title"), job.get("company"))
                skipped += 1
                continue

            merged = {**job, "response": response, "_batch_custom_id": custom_id, "_batch_metadata": batch_meta}
            out_f.write(json.dumps(merged) + "\n")
            matched += 1

    log.info("Done — %d merged | %d skipped (no batch result)", matched, skipped)
    log.info("Output: %s", output_path)


def main() -> None:
    args = parse_args()

    for path, label in [(args.jobs, "--jobs"), (args.results, "--results")]:
        if not os.path.exists(path):
            log.error("%s file not found: %s", label, path)
            sys.exit(1)

    log.info("Loading batch results from %s", args.results)
    results = load_results(args.results)
    log.info("Loaded %d successful results", len(results))

    log.info("Merging with jobs from %s", args.jobs)
    merge(Path(args.jobs), results, args.output, args.append)


if __name__ == "__main__":
    main()
