"""Remote-filter-specific evaluation core."""

import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from agent_eval.costing import add_token_totals, empty_token_totals
from agent_eval.metrics import compute_categorical_metrics
from agent_eval.stats import latency_summary

from .models import REMOTE_CLASSIFICATIONS
from .utils import _build_user_message, analyze_remote, build_search_context

log = logging.getLogger(__name__)

RESOLVED_USER_MESSAGE_HASH_LENGTH = 12
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", None)


def _user_timezone() -> str | None:
    return (
        USER_TIMEZONE if USER_TIMEZONE is not None else os.environ.get("USER_TIMEZONE")
    )


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

    rf_input = build_search_context(job, _user_timezone())
    resolved_user_message_hash = _resolved_user_message_hash(rf_input)

    token_totals = empty_token_totals()

    def usage_callback(usage: dict[str, int]) -> None:
        add_token_totals(token_totals, usage)

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
        # Invalid _human_classification is not a skip — _evaluate_record raises on
        # it (fail fast on bad gold), so only missing_description / agent_failed
        # reach here.
        if result.skip_reason == "missing_description":
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
    # Per-call cost signal: reasoning models inflate completion tokens, and grammar-
    # constrained decoding is slower per token — surfacing both makes a slow local
    # run diagnosable instead of just "the eval is taking forever".
    tokens = result.token_totals
    log.debug(
        "[%3d] latency=%.2fs prompt_tokens=%d completion_tokens=%d cached_tokens=%d",
        result.index,
        result.elapsed,
        tokens.get("input_tokens", 0),
        tokens.get("output_tokens", 0),
        tokens.get("cached_input_tokens", 0),
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
    token_totals = empty_token_totals()

    for result in results:
        add_token_totals(token_totals, result.token_totals)
        # elapsed == 0.0 marks a record that never called the model (e.g. a
        # missing_description skip returns before timing); a real call is always
        # > 0. agent_failed records DID call and carry real elapsed, so this keeps
        # them in the latency summary while excluding pre-call skips.
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
    metrics.update(latency_summary(metrics_input.elapsed_seconds))
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
        # Context manager guarantees shutdown on ANY exception (e.g. a ValueError
        # from invalid gold), not just the success/KeyboardInterrupt paths —
        # otherwise a mid-map failure would leak worker threads.
        with ThreadPoolExecutor(max_workers=workers) as executor:
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
