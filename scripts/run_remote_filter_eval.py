#!/usr/bin/env python3
"""Evaluate the remote filter agent against the human-verified golden dataset.

Writes a durable provenance record to runs.jsonl after every run (SC-2).
CLI overrides modify config in-memory only and are reflected in the run record (SC-3).

Usage:
    uv run scripts/run_remote_filter_eval.py
    uv run scripts/run_remote_filter_eval.py --gold data/eval/ground_truth.jsonl
    uv run scripts/run_remote_filter_eval.py --model gpt-4o --temperature 0.0
    uv run scripts/run_remote_filter_eval.py --provider ollama --model qwen-27b-mtp
    uv run scripts/run_remote_filter_eval.py --run-id my_experiment_label
    uv run scripts/run_remote_filter_eval.py --no-mismatches
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.remote_filter.eval import (
    RESOLVED_USER_MESSAGE_HASH_LENGTH,
    MismatchRecord,
    _aggregate_resolved_user_message_hashes,
    assemble_metrics,
    run_eval,
)
from agents.remote_filter.utils import (
    REMOTE_FILTER_PROMPT_PATH,
    resolve_provider_and_model,
)
from agent_eval.costing import build_cost_summary
from utils.openai_pricing import estimate_cost
from agent_eval.provenance import build_run_record, generate_run_id
from utils.run_logger import JsonlRunLogger, RunLogger

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GOLD_FILE = "data/eval/ground_truth.jsonl"
CONFIG_PATH = "config/agent/remote_agent.yml"
RUNS_FILE = "data/eval/runs.jsonl"
PROMPT_PATH = REMOTE_FILTER_PROMPT_PATH


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--gold",
        default=GOLD_FILE,
        help=f"Ground truth JSONL (default: {GOLD_FILE})",
    )
    p.add_argument(
        "--config",
        default=CONFIG_PATH,
        help=f"Agent config YAML (default: {CONFIG_PATH})",
    )
    p.add_argument(
        "--runs-file",
        default=RUNS_FILE,
        help=f"Run log JSONL (default: {RUNS_FILE})",
    )
    p.add_argument("--model", help="Override llm.model in-memory (SC-3)")
    p.add_argument(
        "--temperature", type=float, help="Override llm.temperature in-memory (SC-3)"
    )
    p.add_argument("--provider", help="Override llm.provider in-memory (SC-3)")
    p.add_argument(
        "--run-id", dest="run_id", help="Custom run label (auto-generated if omitted)"
    )
    p.add_argument(
        "--no-mismatches", action="store_true", help="Skip writing mismatch file"
    )
    p.add_argument(
        "--allow-unpriced",
        action="store_true",
        help="Run even if the OpenAI model has no pricing entry (quality-only, null cost)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent inference workers (default: 1). Performance only; not recorded in provenance.",
    )
    args = p.parse_args()
    if args.workers < 1:
        p.error("--workers must be >= 1")
    return args


def load_gold(path: str) -> list[dict[str, Any]]:
    """Load ground truth; last entry per dedup_hash wins (re-reviews override)."""
    seen: dict[str, dict[str, Any]] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = r.get("dedup_hash") or r.get("source_url") or str(id(r))
            seen[key] = r
    return list(seen.values())


def _format_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _format_money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.6f}"


def print_report(
    metrics: dict[str, Any],
    mismatches: list[MismatchRecord],
    run_id: str,
    cost: dict[str, Any] | None = None,
) -> None:
    m = metrics["metrics"]
    labels = m["labels"]
    print()
    print("=" * 72)
    print("  REMOTE FILTER CATEGORICAL EVAL RESULTS")
    print("=" * 72)
    print(f"  Run ID            : {run_id}")
    print(f"  Records evaluated : {m['evaluated']}  (skipped: {m['skipped']})")
    print(f"  Micro accuracy    : {m['micro_accuracy']:.4f}")
    print(f"  Macro precision   : {m['macro_precision']:.4f}")
    print(f"  Macro recall      : {m['macro_recall']:.4f}")
    print(f"  Macro F1          : {m['macro_f1']:.4f}")
    if cost is not None:
        print(
            "  Est. cost         : "
            f"{_format_money(cost['estimated_cost_usd'])}  "
            f"({_format_money(cost['estimated_cost_per_record_usd'])}/record, "
            f"{_format_money(cost['estimated_cost_per_correct_usd'])}/correct)"
        )
    print(
        "  Latency           : "
        f"avg={_format_float(m['latency_avg_s'])}s  "
        f"p95={_format_float(m['latency_p95_s'])}s  (n={m['latency_n']})"
    )
    print(
        f"  Travel MAE        : {_format_float(m['travel_mae'])}  (n={m['travel_n']})"
    )
    print(
        "  Travel coverage   : "
        f"{_format_float(m['travel_coverage'])}  "
        f"({m['travel_n']}/{m['travel_gold_n']} gold-travel rows populated)"
    )
    print(
        "  Travel spurious   : "
        f"{_format_float(m['travel_spurious_rate'])}  "
        f"({m['travel_pred_n'] - m['travel_n']}/{m['travel_pred_n']} "
        "model-travel rows gold-None)"
    )
    print("-" * 72)
    print("  Confusion matrix (rows=pred, columns=gold)")
    header = "pred\\gold".ljust(14) + "".join(label.rjust(10) for label in labels)
    print(f"  {header}")
    for label, row in zip(labels, m["confusion"]):
        cells = "".join(str(count).rjust(10) for count in row)
        print(f"  {label.ljust(14)}{cells}")
    print("-" * 72)
    print("  Per-class metrics")
    print(
        "  "
        + "class".ljust(14)
        + "precision".rjust(11)
        + "recall".rjust(10)
        + "f1".rjust(10)
        + "support".rjust(10)
    )
    for label in labels:
        cls = m["per_class"][label]
        print(
            "  "
            + label.ljust(14)
            + f"{cls['precision']:>11.4f}"
            + f"{cls['recall']:>10.4f}"
            + f"{cls['f1']:>10.4f}"
            + f"{cls['support']:>10}"
        )
    print("=" * 72)

    if mismatches:
        print(f"\n  {len(mismatches)} classification mismatches:")
        for mm in mismatches:
            print(
                f"  record={mm.record_id}"
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
        llm = config.setdefault("llm", {})
        # Fail fast: overriding provider alone leaves the config's model (authored
        # for the original provider) pointed at the new endpoint — e.g.
        # `--provider ollama` sending `gpt-5.4-mini` to llama.cpp and recording a
        # bogus zero-cost run. Require an explicit --model on a provider switch.
        if not args.model and args.provider != llm.get("provider"):
            log.error(
                "--provider overrides provider to %r but model is still %r from "
                "config %s. Pass --model <%s-model> (e.g. qwen-27b-mtp) so the run "
                "uses a model that exists on that provider.",
                args.provider,
                llm.get("model"),
                args.config,
                args.provider,
            )
            sys.exit(1)
        llm["provider"] = args.provider

    # Resolve the provider/model the run will actually use (same resolver as
    # inference and costing) so we can price-check before spending anything.
    provider, model = resolve_provider_and_model(config.get("llm"))

    # Pre-flight: fail fast BEFORE any paid API call if an OpenAI model has no
    # pricing entry. Otherwise a typo'd/new --model runs the full gold set, costs
    # real money, and only whispers `missing_openai_pricing_entry` into the run
    # record afterward. --allow-unpriced opts into a quality-only (uncosted) run.
    if (
        provider == "openai"
        and not args.allow_unpriced
        and estimate_cost(model, input_tokens=1, cached_input_tokens=0, output_tokens=0)
        is None
    ):
        log.error(
            "OpenAI model %r has no pricing entry in config/pricing/openai.yml, so "
            "this run would record null cost. Add verified rates for it, or pass "
            "--allow-unpriced for a quality-only run.",
            model,
        )
        sys.exit(1)

    run_id = generate_run_id(args.run_id)

    if run_logger is None:
        run_logger = JsonlRunLogger(args.runs_file)

    records = load_gold(args.gold)
    log.info("Loaded %d gold records from %s", len(records), args.gold)

    mismatches, metrics_input, resolved_user_message_hashes = run_eval(
        records, config, run_id, workers=args.workers
    )

    metrics = assemble_metrics(metrics_input)
    # Price against the resolved provider/model (computed at pre-flight above).
    cost = build_cost_summary(
        provider, model, metrics["metrics"], metrics_input.token_totals
    )
    print_report(metrics, mismatches, run_id, cost)

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
    run_record["token_totals"] = dict(metrics_input.token_totals)
    run_record["cost"] = cost
    run_record["resolved_user_message_hashes"] = {
        "algorithm": "sha256",
        "length": RESOLVED_USER_MESSAGE_HASH_LENGTH,
        "count": len(resolved_user_message_hashes),
        "aggregate": _aggregate_resolved_user_message_hashes(
            resolved_user_message_hashes
        ),
        "records": [record.model_dump() for record in resolved_user_message_hashes],
    }
    run_logger.log_run(run_record)
    log.info("Run record logged: %s", run_id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — no run record saved.", file=sys.stderr)
        sys.exit(1)
