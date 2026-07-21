#!/usr/bin/env python3
"""Evaluate the remote filter agent against the human-verified golden dataset.

Writes a durable provenance record to runs.jsonl after every run (SC-2).
CLI overrides modify config in-memory only and are reflected in the run record (SC-3).

Usage:
    uv run scripts/run_remote_filter_eval.py
    uv run scripts/run_remote_filter_eval.py --gold data/eval/ground_truth.jsonl
    uv run scripts/run_remote_filter_eval.py --model gpt-4o --temperature 0.0
    uv run scripts/run_remote_filter_eval.py --provider ollama --model qwen2.5:14b
    uv run scripts/run_remote_filter_eval.py --run-id my_experiment_label
    uv run scripts/run_remote_filter_eval.py --no-mismatches
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.remote_filter.models import REMOTE_CLASSIFICATIONS
from agents.remote_filter.utils import (
    REMOTE_FILTER_PROMPT_PATH,
    _build_user_message,
    analyze_remote,
    build_search_context,
)
from agent_eval.metrics import compute_categorical_metrics
from agent_eval.provenance import build_run_record, generate_run_id
from utils.openai_pricing import estimate_cost
from utils.run_logger import JsonlRunLogger, RunLogger

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GOLD_FILE = "data/eval/ground_truth.jsonl"
CONFIG_PATH = "config/agent/remote_agent.yml"
RUNS_FILE = "data/eval/runs.jsonl"
PROMPT_PATH = REMOTE_FILTER_PROMPT_PATH
RESOLVED_USER_MESSAGE_HASH_LENGTH = 12

USER_TIMEZONE = os.environ.get("USER_TIMEZONE", None)


class MismatchRecord(BaseModel):
    run_id: str
    record_id: str
    gold: str
    pred: str
    human_policy: str | None
    reason: str
    resolved_user_message_hash: str | None = None


class ResolvedUserMessageHashRecord(BaseModel):
    run_id: str
    index: int
    # Full provenance id (not the 8-char MismatchRecord.record_id) — named
    # distinctly so the two schemas aren't mistaken for a joinable key.
    dedup_hash: str
    resolved_user_message_hash: str


@dataclass(frozen=True)
class RecordEvalResult:
    index: int
    job: dict[str, Any]
    gold_classification: str | None
    pred_classification: str | None
    gold_travel_days: int | None
    pred_travel_days: int | None
    reason: str | None
    elapsed: float
    resolved_user_message_hash: str | None = None
    token_totals: dict[str, int] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str | None = None
    mismatch: MismatchRecord | None = None


@dataclass(frozen=True)
class EvalMetricsInput:
    preds: list[str] = field(default_factory=list)
    golds: list[str] = field(default_factory=list)
    pred_travel_days: list[int] = field(default_factory=list)
    gold_travel_days: list[int] = field(default_factory=list)
    elapsed_seconds: list[float] = field(default_factory=list)
    gold_travel_present: int = 0
    pred_travel_present: int = 0
    skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    token_totals: dict[str, int] = field(default_factory=dict)


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
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent inference workers (default: 1). Performance only; not recorded in provenance.",
    )
    args = p.parse_args()
    if args.workers < 1:
        p.error("--workers must be >= 1")
    return args


def _empty_token_totals() -> dict[str, int]:
    return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}


def _add_token_totals(target: dict[str, int], usage: dict[str, int]) -> None:
    for key in _empty_token_totals():
        target[key] = target.get(key, 0) + int(usage.get(key, 0) or 0)


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


def _resolved_user_message_hash(rf_input: Any) -> str:
    return hashlib.sha256(_build_user_message(rf_input).encode("utf-8")).hexdigest()[
        :RESOLVED_USER_MESSAGE_HASH_LENGTH
    ]


def _record_provenance_id(job: dict[str, Any], index: int) -> str:
    return str(job.get("dedup_hash") or job.get("source_job_id") or index)


def _aggregate_resolved_user_message_hashes(
    records: list[ResolvedUserMessageHashRecord],
) -> str:
    hashes = sorted(record.resolved_user_message_hash for record in records)
    return hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()[
        :RESOLVED_USER_MESSAGE_HASH_LENGTH
    ]


def _evaluate_record(
    i: int,
    job: dict[str, Any],
    config: dict[str, Any],
    run_id: str,
) -> RecordEvalResult:
    llm_config = config.get("llm")
    gold_classification = job.get("_human_classification")
    if gold_classification not in REMOTE_CLASSIFICATIONS:
        allowed = ", ".join(REMOTE_CLASSIFICATIONS)
        record_id = _record_provenance_id(job, i)
        log.error(
            "Record %d (%s, id=%s) has invalid _human_classification %r; "
            "expected one of: %s",
            i,
            job.get("title"),
            record_id,
            gold_classification,
            allowed,
        )
        raise ValueError(
            f"record {i} ({job.get('title')}, id={record_id}) has invalid "
            f"_human_classification {gold_classification!r}; expected one of: {allowed}"
        )

    gold_travel_days = job.get("_human_travel_days")

    description = job.get("description", "")
    if not description:
        return RecordEvalResult(
            index=i,
            job=job,
            gold_classification=gold_classification,
            pred_classification=None,
            gold_travel_days=gold_travel_days,
            pred_travel_days=None,
            reason=None,
            elapsed=0.0,
            skipped=True,
            skip_reason="missing_description",
        )

    rf_input = build_search_context(job, USER_TIMEZONE)
    resolved_user_message_hash = _resolved_user_message_hash(rf_input)

    token_totals = _empty_token_totals()

    def usage_callback(usage: dict[str, int]) -> None:
        _add_token_totals(token_totals, usage)

    t0 = time.monotonic()
    analysis = analyze_remote(
        rf_input,
        llm_config=llm_config,
        usage_callback=usage_callback,
    )
    elapsed = time.monotonic() - t0

    if analysis is None:
        return RecordEvalResult(
            index=i,
            job=job,
            gold_classification=gold_classification,
            pred_classification=None,
            gold_travel_days=gold_travel_days,
            pred_travel_days=None,
            reason=None,
            elapsed=elapsed,
            resolved_user_message_hash=resolved_user_message_hash,
            token_totals=token_totals,
            skipped=True,
            skip_reason="agent_failed",
        )

    pred_classification = analysis.remote_classification
    pred_travel_days = analysis.estimated_travel_days_per_year
    reason = analysis.reasoning_trace

    mismatch = None
    if pred_classification != gold_classification:
        mismatch = MismatchRecord(
            run_id=run_id,
            # Short display id, derived from the same always-populated
            # provenance helper so it's never blank when dedup_hash is missing.
            record_id=_record_provenance_id(job, i)[:8],
            gold=gold_classification,
            pred=pred_classification,
            human_policy=job.get("_human_policy"),
            reason=reason,
            resolved_user_message_hash=resolved_user_message_hash,
        )

    return RecordEvalResult(
        index=i,
        job=job,
        gold_classification=gold_classification,
        pred_classification=pred_classification,
        gold_travel_days=gold_travel_days,
        pred_travel_days=pred_travel_days,
        reason=reason,
        elapsed=elapsed,
        resolved_user_message_hash=resolved_user_message_hash,
        token_totals=token_totals,
        mismatch=mismatch,
    )


def _log_record_result(result: RecordEvalResult) -> None:
    job = result.job
    if result.skipped:
        if result.skip_reason == "invalid_human_classification":
            log.warning(
                "Record %d (%s) has no valid _human_classification — skipping",
                result.index,
                job.get("title"),
            )
        elif result.skip_reason == "missing_description":
            log.warning(
                "Record %d (%s) has no description — skipping",
                result.index,
                job.get("title"),
            )
        else:
            log.warning(
                "Record %d (%s @ %s) — agent failed, skipping",
                result.index,
                job.get("title"),
                job.get("company"),
            )
        return

    log.info(
        "[%3d] %-8s → %-8s  travel=%s→%s  %-40s @ %-20s  %.1fs",
        result.index,
        result.gold_classification,
        result.pred_classification,
        result.gold_travel_days,
        result.pred_travel_days,
        (job.get("title") or "?")[:40],
        job.get("company", "?")[:20],
        result.elapsed,
    )


def _metrics_input_from_results(results: list[RecordEvalResult]) -> EvalMetricsInput:
    preds: list[str] = []
    golds: list[str] = []
    pred_travel_days: list[int] = []
    gold_travel_days: list[int] = []
    gold_travel_present = 0
    pred_travel_present = 0
    elapsed_seconds: list[float] = []
    skipped = 0
    skip_reasons: dict[str, int] = {}
    token_totals = _empty_token_totals()

    for result in results:
        _add_token_totals(token_totals, result.token_totals)
        if result.elapsed > 0:
            elapsed_seconds.append(result.elapsed)
        if result.skipped:
            skipped += 1
            reason = result.skip_reason or "unknown"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        if result.pred_classification is None or result.gold_classification is None:
            raise ValueError(
                f"record {result.index} was not skipped but lacks classification labels"
            )
        preds.append(result.pred_classification)
        golds.append(result.gold_classification)
        if result.gold_travel_days is not None:
            gold_travel_present += 1
        if result.pred_travel_days is not None:
            pred_travel_present += 1
        if result.pred_travel_days is not None and result.gold_travel_days is not None:
            pred_travel_days.append(result.pred_travel_days)
            gold_travel_days.append(result.gold_travel_days)

    return EvalMetricsInput(
        preds=preds,
        golds=golds,
        pred_travel_days=pred_travel_days,
        gold_travel_days=gold_travel_days,
        elapsed_seconds=elapsed_seconds,
        gold_travel_present=gold_travel_present,
        pred_travel_present=pred_travel_present,
        skipped=skipped,
        skip_reasons=skip_reasons,
        token_totals=token_totals,
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 <= percentile <= 100:
        raise ValueError(f"percentile must be between 0 and 100: {percentile}")
    sorted_values = sorted(values)
    index = round((percentile / 100) * (len(sorted_values) - 1))
    return sorted_values[index]


def assemble_metrics(metrics_input: EvalMetricsInput) -> dict[str, Any]:
    metrics = compute_categorical_metrics(
        metrics_input.preds,
        metrics_input.golds,
        REMOTE_CLASSIFICATIONS,
        skipped=metrics_input.skipped,
    )["metrics"]
    if len(metrics_input.pred_travel_days) != len(metrics_input.gold_travel_days):
        # Built in lockstep by _metrics_input_from_results today, but guard the
        # invariant: a silent zip-truncation would divide by the wrong denominator.
        raise ValueError(
            "pred_travel_days and gold_travel_days must align "
            f"({len(metrics_input.pred_travel_days)} != "
            f"{len(metrics_input.gold_travel_days)})"
        )
    travel_n = len(metrics_input.pred_travel_days)
    travel_mae = (
        sum(
            abs(pred - gold)
            for pred, gold in zip(
                metrics_input.pred_travel_days, metrics_input.gold_travel_days
            )
        )
        / travel_n
        if travel_n
        else None
    )
    metrics["travel_mae"] = travel_mae
    metrics["travel_n"] = travel_n
    gold_n = metrics_input.gold_travel_present
    pred_n = metrics_input.pred_travel_present
    metrics["travel_gold_n"] = gold_n
    metrics["travel_pred_n"] = pred_n
    metrics["travel_coverage"] = (travel_n / gold_n) if gold_n else None
    metrics["travel_spurious_rate"] = ((pred_n - travel_n) / pred_n) if pred_n else None
    metrics["skip_reasons"] = dict(metrics_input.skip_reasons)
    metrics["agent_failed"] = metrics_input.skip_reasons.get("agent_failed", 0)
    latency_n = len(metrics_input.elapsed_seconds)
    metrics["latency_n"] = latency_n
    metrics["latency_avg_s"] = (
        sum(metrics_input.elapsed_seconds) / latency_n if latency_n else None
    )
    metrics["latency_p95_s"] = _percentile(metrics_input.elapsed_seconds, 95)
    return {"metrics": metrics}


def run_eval(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    run_id: str,
    workers: int = 1,
) -> tuple[list[MismatchRecord], EvalMetricsInput, list[ResolvedUserMessageHashRecord]]:
    mismatches: list[MismatchRecord] = []
    resolved_user_message_hashes: list[ResolvedUserMessageHashRecord] = []

    if workers == 1:
        results = [
            _evaluate_record(i, job, config, run_id) for i, job in enumerate(records)
        ]
    else:
        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            results = list(
                executor.map(
                    lambda item: _evaluate_record(item[0], item[1], config, run_id),
                    enumerate(records),
                )
            )
        except KeyboardInterrupt:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown()

    for result in results:
        _log_record_result(result)
        if result.resolved_user_message_hash is not None:
            resolved_user_message_hashes.append(
                ResolvedUserMessageHashRecord(
                    run_id=run_id,
                    index=result.index,
                    dedup_hash=_record_provenance_id(result.job, result.index),
                    resolved_user_message_hash=result.resolved_user_message_hash,
                )
            )
        if result.mismatch is not None:
            mismatches.append(result.mismatch)

    return (
        mismatches,
        _metrics_input_from_results(results),
        resolved_user_message_hashes,
    )


def _correct_count(metrics: dict[str, Any]) -> int:
    confusion = metrics.get("confusion") or []
    if not isinstance(confusion, list):
        return int((metrics.get("micro_accuracy") or 0.0) * metrics.get("evaluated", 0))
    return sum(
        int(row[i])
        for i, row in enumerate(confusion)
        if isinstance(row, list) and i < len(row)
    )


def build_cost_summary(
    config: dict[str, Any], metrics: dict[str, Any], token_totals: dict[str, int]
) -> dict[str, Any]:
    """Build the eval cost block from observed token usage and list pricing."""
    llm_config = config.get("llm") or {}
    provider = llm_config.get("provider")
    model = llm_config.get("model")
    evaluated = int(metrics.get("evaluated") or 0)
    correct = _correct_count(metrics)

    estimated_total: float | None
    breakdown: dict[str, float] | None
    pricing_note: str
    if provider == "openai" and model:
        breakdown = estimate_cost(model, batch=False, **token_totals)
        if breakdown is None:
            estimated_total = None
            pricing_note = "missing_openai_pricing_entry"
        else:
            estimated_total = breakdown["total"]
            pricing_note = "openai_list_price_estimate"
    else:
        # Local/ollama-compatible runs have no API invoice. Tokens may still be
        # present for observability, but estimated dollar cost is intentionally $0.
        breakdown = None
        estimated_total = 0.0
        pricing_note = "local_provider_zero_api_cost"

    return {
        "token_totals": dict(token_totals),
        "estimated_cost_usd": estimated_total,
        "estimated_cost_per_record_usd": (
            estimated_total / evaluated
            if estimated_total is not None and evaluated
            else None
        ),
        "estimated_cost_per_correct_usd": (
            estimated_total / correct
            if estimated_total is not None and correct
            else None
        ),
        "correct": correct,
        "breakdown": breakdown,
        "pricing_note": pricing_note,
    }


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
        config.setdefault("llm", {})["provider"] = args.provider

    run_id = generate_run_id(args.run_id)

    if run_logger is None:
        run_logger = JsonlRunLogger(args.runs_file)

    records = load_gold(args.gold)
    log.info("Loaded %d gold records from %s", len(records), args.gold)

    mismatches, metrics_input, resolved_user_message_hashes = run_eval(
        records, config, run_id, workers=args.workers
    )

    metrics = assemble_metrics(metrics_input)
    cost = build_cost_summary(config, metrics["metrics"], metrics_input.token_totals)
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
