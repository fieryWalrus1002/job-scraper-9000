#!/usr/bin/env python3
"""Poll an OpenAI Batch API remote-filter eval and log results when complete.

This is the processing half of SC-7. It reads the sidecar written by
submit_eval_batch.py, checks batch status, and when complete downloads the Batch
API output, computes normal remote-filter metrics, writes mismatches, and appends
a standard run record to data/eval/runs.jsonl.

Usage:
    uv run python scripts/poll_eval_batch.py
    uv run python scripts/poll_eval_batch.py --sidecar data/eval/eval_batch_<run_id>.json
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from utils import batch_api
from utils.batch_api import TERMINAL_STATUSES
from utils.run_logger import JsonlRunLogger
from agent_eval.metrics import compute_metrics
from agent_eval.provenance import build_run_record, hash_file, hash_string
from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.utils import REMOTE_FILTER_PROMPT_PATH, passes_remote_filter
from scripts.run_remote_filter_eval import MismatchRecord, load_gold, print_report

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

SIDECAR_GLOB = "data/eval/eval_batch_*.json"
RUNS_FILE = "data/eval/runs.jsonl"
INCOMPLETE_STATUSES = {
    "validating",
    "in_progress",
    "finalizing",
    "cancelling",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--sidecar",
        help=f"Sidecar JSON path (default: newest {SIDECAR_GLOB})",
    )
    p.add_argument(
        "--runs-file",
        default=RUNS_FILE,
        help=f"Run log JSONL (default: {RUNS_FILE})",
    )
    p.add_argument(
        "--no-mismatches",
        action="store_true",
        help="Skip writing mismatch JSONL even if mismatches exist",
    )
    return p.parse_args()


def latest_sidecar() -> Path:
    paths = sorted(Path().glob(SIDECAR_GLOB), key=lambda p: p.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"No sidecar files found matching {SIDECAR_GLOB}")
    return paths[-1]


def load_sidecar(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_counts(batch) -> str:
    counts = getattr(batch, "request_counts", None)
    if counts is None:
        return "counts unavailable"
    return f"completed={counts.completed}/{counts.total} failed={counts.failed}"


def _download_file(client: OpenAI, file_id: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = client.files.content(file_id).text
    path.write_text(content, encoding="utf-8")
    log.info("Downloaded %s → %s", file_id, path)


def ensure_results_file(
    client: OpenAI, batch, sidecar: dict[str, Any], sidecar_path: Path
) -> Path:
    existing = sidecar.get("output_file")
    if existing and Path(existing).exists():
        return Path(existing)

    output_file_id = getattr(batch, "output_file_id", None)
    content = batch_api.download_results(client, batch)

    run_id = sidecar["run_id"]
    output_file = Path("data/eval/batch") / f"eval_results_{run_id}.jsonl"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8")
    log.info("Downloaded %s → %s", output_file_id, output_file)

    sidecar["output_file_id"] = output_file_id
    sidecar["output_file"] = str(output_file)
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return output_file


def load_results(results_path: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            custom_id = item.get("custom_id")
            if custom_id:
                results[custom_id] = item
    return results


def parse_analysis(item: dict[str, Any]) -> RemoteAnalysis | None:
    if item.get("error"):
        log.warning("Batch item %s errored: %s", item.get("custom_id"), item["error"])
        return None

    response = item.get("response") or {}
    status_code = response.get("status_code")
    if status_code != 200:
        log.warning(
            "Batch item %s returned status=%s", item.get("custom_id"), status_code
        )
        return None

    try:
        content = response["body"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        log.warning(
            "Batch item %s missing message content: %s", item.get("custom_id"), exc
        )
        return None

    try:
        return RemoteAnalysis.model_validate_json(content)
    except ValidationError as exc:
        log.warning(
            "Batch item %s failed schema validation: %s", item.get("custom_id"), exc
        )
        return None


def evaluate_batch_results(
    records: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    sidecar: dict[str, Any],
) -> tuple[list[MismatchRecord], dict[str, int]]:
    config = sidecar["config"]
    user_location = sidecar.get("user_location") or os.environ.get(
        "USER_LOCATION", "USA"
    )
    run_id = sidecar["run_id"]

    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "skipped": 0}
    mismatches: list[MismatchRecord] = []

    for idx, job in enumerate(records):
        human_verdict = job.get("_human_verdict")
        if human_verdict not in ("pass", "trash"):
            counts["skipped"] += 1
            log.warning(
                "Record %d (%s) has no valid _human_verdict — skipping",
                idx,
                job.get("title"),
            )
            continue

        item = results.get(f"job-{idx}")
        if item is None:
            counts["skipped"] += 1
            log.warning(
                "No batch result for job-%d (%s @ %s) — skipping",
                idx,
                job.get("title"),
                job.get("company"),
            )
            continue

        analysis = parse_analysis(item)
        if analysis is None:
            counts["skipped"] += 1
            continue

        ok, reason = passes_remote_filter(analysis, config, user_location)
        pred = "pass" if ok else "trash"

        if pred == "pass" and human_verdict == "pass":
            counts["tp"] += 1
        elif pred == "pass" and human_verdict == "trash":
            counts["fp"] += 1
        elif pred == "trash" and human_verdict == "trash":
            counts["tn"] += 1
        else:
            counts["fn"] += 1

        if pred != human_verdict:
            dedup_hash = job.get("dedup_hash", "")
            mismatches.append(
                MismatchRecord(
                    run_id=run_id,
                    record_id=dedup_hash[:8],
                    gold=human_verdict,
                    pred=pred,
                    human_policy=job.get("_human_policy"),
                    reason=reason,
                )
            )

        log.info(
            "[%3d] %-8s → %-8s  %-40s @ %-20s",
            idx,
            human_verdict,
            pred,
            (job.get("title") or "?")[:40],
            job.get("company", "?")[:20],
        )

    return mismatches, counts


def _prompt_text_for_record(sidecar: dict[str, Any]) -> str:
    """Return current prompt text; caller overwrites prompt_hash from sidecar if needed."""
    return REMOTE_FILTER_PROMPT_PATH.read_text()


def write_run_record(
    *,
    sidecar: dict[str, Any],
    metrics: dict[str, Any],
    mismatch_file: Path | None,
    runs_file: str,
) -> None:
    prompt_text = _prompt_text_for_record(sidecar)
    run_record = build_run_record(
        run_id=sidecar["run_id"],
        gold_file=Path(sidecar["gold_file"]),
        prompt_text=prompt_text,
        config=sidecar["config"],
        config_file=sidecar["config_file"],
        metrics=metrics,
        mismatch_file=mismatch_file,
    )

    submitted_prompt_hash = sidecar.get("prompt_hash")
    current_prompt_hash = hash_string(prompt_text)
    if submitted_prompt_hash and submitted_prompt_hash != current_prompt_hash:
        log.warning(
            "Current prompt hash differs from submitted batch prompt; preserving sidecar prompt_hash"
        )
        run_record["prompt_hash"] = submitted_prompt_hash

    JsonlRunLogger(runs_file).log_run(run_record)
    log.info("Run record logged: %s", sidecar["run_id"])


def main() -> None:
    args = parse_args()
    try:
        sidecar_path = Path(args.sidecar) if args.sidecar else latest_sidecar()
    except FileNotFoundError as exc:
        log.error(str(exc))
        sys.exit(1)

    sidecar = load_sidecar(sidecar_path)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.error("OPENAI_API_KEY not set")
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    batch = client.batches.retrieve(sidecar["batch_id"])
    log.info("Batch %s status=%s %s", batch.id, batch.status, _request_counts(batch))

    if batch.status in INCOMPLETE_STATUSES or batch.status not in TERMINAL_STATUSES:
        print(f"Batch {batch.id} is {batch.status}; nothing to do yet.")
        return

    if batch.status != "completed":
        log.error("Batch ended with status=%s", batch.status)
        if getattr(batch, "error_file_id", None):
            error_file = (
                Path("data/eval/batch") / f"eval_errors_{sidecar['run_id']}.jsonl"
            )
            _download_file(client, batch.error_file_id, error_file)
            log.error("Error file written to %s", error_file)
        sys.exit(1)

    gold_file = Path(sidecar["gold_file"])
    if hash_file(gold_file) != sidecar.get("gold_hash"):
        log.error(
            "Gold file hash mismatch for %s; refusing to score against drifted dataset",
            gold_file,
        )
        sys.exit(1)

    results_path = ensure_results_file(client, batch, sidecar, sidecar_path)
    records = load_gold(str(gold_file))
    results = load_results(results_path)
    mismatches, counts = evaluate_batch_results(records, results, sidecar)

    metrics = compute_metrics(**counts)
    print_report(metrics, mismatches, sidecar["run_id"])

    mismatch_path: Path | None = None
    if mismatches and not args.no_mismatches:
        mismatch_path = Path(f"data/eval/mismatches_{sidecar['run_id']}.jsonl")
        mismatch_path.parent.mkdir(parents=True, exist_ok=True)
        mismatch_path.write_text(
            "\n".join(mm.model_dump_json() for mm in mismatches) + "\n",
            encoding="utf-8",
        )
        log.info("Mismatches written to %s", mismatch_path)

    write_run_record(
        sidecar=sidecar,
        metrics=metrics["metrics"],
        mismatch_file=mismatch_path,
        runs_file=args.runs_file,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — no run record saved.", file=sys.stderr)
        sys.exit(1)
