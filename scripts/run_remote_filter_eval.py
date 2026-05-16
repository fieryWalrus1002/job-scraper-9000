#!/usr/bin/env python3
"""Evaluate the remote filter agent against the human-verified golden dataset.

Writes a durable provenance record to runs.jsonl after every run (SC-2).
CLI overrides modify config in-memory only and are reflected in the run record (SC-3).

Usage:
    python scripts/run_remote_filter_eval.py
    python scripts/run_remote_filter_eval.py --gold data/eval/ground_truth.jsonl
    python scripts/run_remote_filter_eval.py --model gpt-4o --temperature 0.0
    python scripts/run_remote_filter_eval.py --provider ollama --model qwen2.5:14b
    python scripts/run_remote_filter_eval.py --run-id my_experiment_label
    python scripts/run_remote_filter_eval.py --no-mismatches
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.remote_filter.utils import REMOTE_FILTER_PROMPT_PATH, analyze_remote, passes_remote_filter
from eval.logger import JsonlRunLogger, RunLogger
from eval.metrics import compute_metrics
from eval.provenance import build_run_record, generate_run_id

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GOLD_FILE = "data/eval/ground_truth.jsonl"
CONFIG_PATH = "config/agent/remote_agent.yml"
RUNS_FILE = "data/eval/runs.jsonl"
PROMPT_PATH = REMOTE_FILTER_PROMPT_PATH

USER_LOCATION = os.environ.get("USER_LOCATION", "USA")
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", None)


class MismatchRecord(BaseModel):
    run_id: str
    record_id: str
    gold: str
    pred: str
    human_policy: str | None
    reason: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--gold", default=GOLD_FILE,
        help=f"Ground truth JSONL (default: {GOLD_FILE})",
    )
    p.add_argument(
        "--config", default=CONFIG_PATH,
        help=f"Agent config YAML (default: {CONFIG_PATH})",
    )
    p.add_argument(
        "--runs-file", default=RUNS_FILE,
        help=f"Run log JSONL (default: {RUNS_FILE})",
    )
    p.add_argument("--model", help="Override llm.model in-memory (SC-3)")
    p.add_argument("--temperature", type=float, help="Override llm.temperature in-memory (SC-3)")
    p.add_argument("--provider", help="Override llm.provider in-memory (SC-3)")
    p.add_argument("--run-id", dest="run_id", help="Custom run label (auto-generated if omitted)")
    p.add_argument("--no-mismatches", action="store_true", help="Skip writing mismatch file")
    return p.parse_args()


def load_gold(path: str) -> list[dict]:
    """Load ground truth; last entry per dedup_hash wins (re-reviews override)."""
    seen: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = r.get("dedup_hash") or r.get("source_url") or str(id(r))
            seen[key] = r
    return list(seen.values())


def run_eval(
    records: list[dict],
    config: dict,
    run_id: str,
) -> tuple[list[MismatchRecord], dict[str, int]]:
    llm_config = config.get("llm")
    tp = fp = tn = fn = skipped = 0
    mismatches: list[MismatchRecord] = []

    for i, job in enumerate(records):
        human_verdict = job.get("_human_verdict")
        if human_verdict not in ("pass", "trash"):
            log.warning(
                "Record %d (%s) has no valid _human_verdict — skipping",
                i, job.get("title"),
            )
            skipped += 1
            continue

        description = job.get("description", "")
        if not description:
            log.warning(
                "Record %d (%s) has no description — skipping",
                i, job.get("title"),
            )
            skipped += 1
            continue

        location = job.get("location") or None
        title = job.get("title") or None
        search_context = {
            **(job.get("search_params") or {}),
            **({"user_timezone": USER_TIMEZONE} if USER_TIMEZONE else {}),
        }

        t0 = time.monotonic()
        analysis = analyze_remote(
            description,
            title=title,
            location=location,
            search_context=search_context or None,
            llm_config=llm_config,
        )
        elapsed = time.monotonic() - t0

        if analysis is None:
            log.warning(
                "Record %d (%s @ %s) — agent failed, skipping",
                i, job.get("title"), job.get("company"),
            )
            skipped += 1
            continue

        ok, reason = passes_remote_filter(analysis, config, USER_LOCATION)
        pred = "pass" if ok else "trash"

        if pred == "pass" and human_verdict == "pass":
            tp += 1
        elif pred == "pass" and human_verdict == "trash":
            fp += 1
        elif pred == "trash" and human_verdict == "trash":
            tn += 1
        else:
            fn += 1

        if pred != human_verdict:
            dedup_hash = job.get("dedup_hash", "")
            mismatches.append(MismatchRecord(
                run_id=run_id,
                record_id=dedup_hash[:8],
                gold=human_verdict,
                pred=pred,
                human_policy=job.get("_human_policy"),
                reason=reason,
            ))

        log.info(
            "[%3d] %-8s → %-8s  %-40s @ %-20s  %.1fs",
            i, human_verdict, pred,
            (job.get("title") or "?")[:40],
            job.get("company", "?")[:20],
            elapsed,
        )

    return mismatches, {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "skipped": skipped}


def print_report(metrics: dict, mismatches: list[MismatchRecord], run_id: str) -> None:
    m = metrics["metrics"]
    print()
    print("=" * 50)
    print("  EVALUATION RESULTS")
    print("=" * 50)
    print(f"  Run ID            : {run_id}")
    print(f"  Records evaluated : {m['evaluated']}  (skipped: {m['skipped']})")
    print(f"  TP / FP / TN / FN : {m['tp']} / {m['fp']} / {m['tn']} / {m['fn']}")
    print("-" * 50)
    print(f"  Accuracy          : {m['accuracy']:.4f}")
    print(f"  Precision         : {m['precision']:.4f}  ← too much trash in inbox?")
    print(f"  Recall            : {m['recall']:.4f}  ← missing good jobs?")
    print(f"  F1                : {m['f1']:.4f}")
    print("=" * 50)

    if mismatches:
        print(f"\n  {len(mismatches)} mismatches:")
        for mm in mismatches:
            tag = "FP" if mm.pred == "pass" else "FN"
            print(
                f"  [{tag}] record={mm.record_id}"
                f"  gold={mm.gold}  pred={mm.pred}"
                f"  policy={mm.human_policy}  reason={mm.reason}"
            )
    print()


def main(run_logger: RunLogger | None = None) -> None:
    args = parse_args()

    if not Path(args.gold).exists():
        log.error("Gold file not found: %s", args.gold)
        sys.exit(1)

    with open(args.config) as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))

    # SC-3: apply CLI overrides in-memory only
    if args.model:
        config.setdefault("llm", {})["model"] = args.model
    if args.temperature is not None:
        config.setdefault("llm", {})["temperature"] = args.temperature
    if args.provider:
        config.setdefault("llm", {})["provider"] = args.provider

    run_id = generate_run_id(args.run_id)

    if run_logger is None:
        run_logger = JsonlRunLogger(args.runs_file)

    records = load_gold(args.gold)
    log.info("Loaded %d gold records from %s", len(records), args.gold)

    mismatches, counts = run_eval(records, config, run_id)

    metrics = compute_metrics(**counts)
    print_report(metrics, mismatches, run_id)

    # SC-4: write mismatch file named mismatches_{run_id}.jsonl
    mismatch_path: Path | None = None
    if mismatches and not args.no_mismatches:
        mismatch_path = Path(f"data/eval/mismatches_{run_id}.jsonl")
        mismatch_path.parent.mkdir(parents=True, exist_ok=True)
        mismatch_path.write_text(
            "\n".join(mm.model_dump_json() for mm in mismatches) + "\n"
        )
        log.info("Mismatches written to %s", mismatch_path)

    # SC-2: build and persist provenance record
    prompt_text = PROMPT_PATH.read_text()
    run_record = build_run_record(
        run_id=run_id,
        gold_file=Path(args.gold),
        prompt_text=prompt_text,
        config=config,
        config_file=args.config,
        metrics=metrics["metrics"],
        mismatch_file=mismatch_path,
    )
    run_logger.log_run(run_record)
    log.info("Run record logged: %s", run_id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — no run record saved.", file=sys.stderr)
        sys.exit(1)
