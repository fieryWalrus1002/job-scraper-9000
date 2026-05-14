#!/usr/bin/env python3
"""
Evaluate the Student model against the Human-verified Golden Dataset.

For each record in the gold file, runs analyze_remote() + passes_remote_filter()
and compares the result to the human-confirmed verdict. Reports precision, recall,
accuracy, and F1, then writes mismatches to data/eval/mismatches_YYYY-MM-DD.jsonl
so you can review failures and iterate on the student prompt.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --gold data/eval/051126/ground_truth.jsonl
    python scripts/run_eval.py --no-mismatches   # skip mismatch file output
"""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.remote_filter.utils import analyze_remote, passes_remote_filter

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GOLD_FILE = "data/eval/ground_truth.jsonl"
CONFIG_PATH = "config/agent/remote_agent.yml"
USER_LOCATION = os.environ.get("USER_LOCATION", "USA")
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", None)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--gold", default=GOLD_FILE, help=f"Ground truth JSONL (default: {GOLD_FILE})"
    )
    p.add_argument(
        "--config",
        default=CONFIG_PATH,
        help=f"Agent config YAML (default: {CONFIG_PATH})",
    )
    p.add_argument(
        "--no-mismatches", action="store_true", help="Skip writing mismatch file"
    )
    return p.parse_args()


def load_gold(path: str) -> list[dict]:
    """Load ground truth, keeping only the last entry per dedup_hash (re-reviews override)."""
    seen: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = r.get("dedup_hash") or r.get("source_url") or id(r)
            seen[key] = r
    return list(seen.values())


def run_eval(records: list[dict], config: dict) -> tuple[list[dict], dict]:
    llm_config = config.get("llm")
    tp = fp = tn = fn = skipped = 0
    mismatches = []

    for i, job in enumerate(records):
        human_verdict = job.get("_human_verdict")
        if human_verdict not in ("pass", "trash"):
            log.warning(
                "Record %d (%s) has no valid _human_verdict — skipping",
                i,
                job.get("title"),
            )
            skipped += 1
            continue

        description = job.get("description", "")
        if not description:
            log.warning(
                "Record %d (%s) has no description — skipping", i, job.get("title")
            )
            skipped += 1
            continue

        location = job.get("location") or None
        title = job.get("title") or None
        search_context = {
            **(job.get("search_params") or {}),
            **({"user_timezone": USER_TIMEZONE} if USER_TIMEZONE else {}),
        }

        analysis = analyze_remote(
            description,
            title=title,
            location=location,
            search_context=search_context or None,
            llm_config=llm_config,
        )

        if analysis is None:
            log.warning(
                "Record %d (%s @ %s) — student agent failed, skipping",
                i,
                job.get("title"),
                job.get("company"),
            )
            skipped += 1
            continue

        ok, reason = passes_remote_filter(analysis, config, USER_LOCATION)
        student_verdict = "pass" if ok else "trash"

        if student_verdict == "pass" and human_verdict == "pass":
            tp += 1
        elif student_verdict == "pass" and human_verdict == "trash":
            fp += 1
        elif student_verdict == "trash" and human_verdict == "trash":
            tn += 1
        else:
            fn += 1

        if student_verdict != human_verdict:
            mismatches.append(
                {
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "human_verdict": human_verdict,
                    "human_policy": job.get("_human_policy"),
                    "corrected": job.get("_corrected", False),
                    "student_verdict": student_verdict,
                    "student_classification": analysis.remote_classification,
                    "student_filter_reason": reason,
                    "student_reasoning": analysis.reasoning_trace,
                    "url": job.get("source_url", ""),
                }
            )

        log.info(
            "[%3d] %-8s → %-8s  %s @ %s",
            i,
            human_verdict,
            student_verdict,
            job.get("title", "?")[:40],
            job.get("company", "?"),
        )

    counts = {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "skipped": skipped}
    return mismatches, counts


def print_report(counts: dict, mismatches: list[dict]) -> None:
    tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]
    total = tp + fp + tn + fn

    accuracy = (tp + tn) / total if total else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print()
    print("=" * 44)
    print("  EVALUATION RESULTS")
    print("=" * 44)
    print(f"  Records evaluated : {total}  (skipped: {counts['skipped']})")
    print(f"  TP / FP / TN / FN : {tp} / {fp} / {tn} / {fn}")
    print("-" * 44)
    print(f"  Accuracy          : {accuracy:.1%}")
    print(f"  Precision         : {precision:.1%}  ← too much trash in inbox?")
    print(f"  Recall            : {recall:.1%}  ← missing good jobs?")
    print(f"  F1                : {f1:.1%}")
    print("=" * 44)

    if mismatches:
        print(f"\n  {len(mismatches)} mismatches — check data/eval/mismatches_*.jsonl")
        for m in mismatches:
            tag = "FP" if m["student_verdict"] == "pass" else "FN"
            print(f"  [{tag}] {m['title']} @ {m['company']}")
            print(
                f"        human={m['human_policy']}  student={m['student_classification']}  reason={m['student_filter_reason']}"
            )
    print()


def main() -> None:
    args = parse_args()

    if not Path(args.gold).exists():
        log.error("Gold file not found: %s", args.gold)
        sys.exit(1)

    with open(args.config) as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))

    records = load_gold(args.gold)
    log.info("Loaded %d gold records from %s", len(records), args.gold)

    mismatches, counts = run_eval(records, config)
    print_report(counts, mismatches)

    if mismatches and not args.no_mismatches:
        out = Path(f"data/eval/mismatches_{date.today().isoformat()}.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(json.dumps(m) for m in mismatches) + "\n")
        log.info("Mismatches written to %s", out)


if __name__ == "__main__":
    main()
