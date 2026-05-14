#!/usr/bin/env python3
"""
Merge an OpenAI Batch API results file back onto the original job records.

Reads from the run directory (default: data/batch/YYYY-MM-DD/) and always
APPENDS to data/staging/to_review.jsonl so that unreviewed records from a
prior batch are never clobbered.

Workflow:
    prepare_batch.py → submit_batch.py → merge_batch_results.py → Streamlit UI

Usage:
    python scripts/merge_batch_results.py                              # today's run dir
    python scripts/merge_batch_results.py --run-dir data/batch/2026-05-11
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from agents.remote_filter.models import SCHEMA_VERSION  # noqa: E402
from utils.git_info import get_git_metadata, get_prompt_hash  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_RUN_DIR = f"data/batch/{date.today().isoformat()}"
STAGING_FILE = "data/staging/to_review.jsonl"
PROMPT_FILE = (
    Path(__file__).parents[1]
    / "prompts"
    / "remote_agent_teacher"
    / "system_prompt_v1.txt"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--run-dir",
        default=DEFAULT_RUN_DIR,
        help=f"Batch run directory (default: {DEFAULT_RUN_DIR})",
    )
    p.add_argument(
        "--output",
        default=STAGING_FILE,
        help=f"Staging file to append to (default: {STAGING_FILE})",
    )
    return p.parse_args()


def load_results(results_path: Path) -> dict[str, dict]:
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
    """Yield (idx, job_dict) from the sidecar file."""
    with open(jobs_path) as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if line:
                yield idx, json.loads(line)


def merge(jobs_path: Path, results: dict[str, dict], output_path: str) -> None:
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
    log.info(
        "Batch metadata: schema=%s prompt=%s commit=%s dirty=%s",
        SCHEMA_VERSION,
        prompt_hash,
        git_meta["commit"][:12],
        git_meta["dirty"],
    )

    matched = skipped = 0

    with open(output_path, "a") as out_f:
        for idx, job in iter_jobs(jobs_path):
            custom_id = f"job-{idx}"
            response = results.get(custom_id)
            if response is None:
                log.warning(
                    "No result for %s (%s @ %s) — skipping",
                    custom_id,
                    job.get("title"),
                    job.get("company"),
                )
                skipped += 1
                continue

            merged = {
                **job,
                "response": response,
                "_batch_custom_id": custom_id,
                "_batch_metadata": batch_meta,
            }
            out_f.write(json.dumps(merged) + "\n")
            matched += 1

    log.info(
        "Done — %d appended to staging | %d skipped (no batch result)", matched, skipped
    )
    log.info("Output: %s", output_path)


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)

    jobs_path = run_dir / "gpt_teacher_jobs.jsonl"
    results_path = run_dir / "gpt_teacher_results.jsonl"

    for path, label in [(jobs_path, "jobs sidecar"), (results_path, "batch results")]:
        if not path.exists():
            log.error("%s not found: %s", label, path)
            sys.exit(1)

    log.info("Loading batch results from %s", results_path)
    results = load_results(results_path)
    log.info("Loaded %d successful results", len(results))

    log.info("Merging with jobs from %s", jobs_path)
    merge(jobs_path, results, args.output)

    print("\nNext step: uv run streamlit run src/review_ui/app.py")


if __name__ == "__main__":
    main()
