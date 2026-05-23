#!/usr/bin/env python3
"""Evaluate the skills_fit agent against the human-verified gold dataset.

Supports two scorers via --scorer:
    llm     — calls analyze_skills_fit() (structured LLM via OpenAI/Ollama)
    keyword — calls keyword_overlap_analyze() (deterministic baseline)

Writes a durable provenance record to runs.jsonl after every run.

Usage:
    uv run scripts/run_skills_fit_eval.py --scorer llm
    uv run scripts/run_skills_fit_eval.py --scorer keyword
    uv run scripts/run_skills_fit_eval.py --scorer llm --model gpt-4o --temperature 0.0
    uv run scripts/run_skills_fit_eval.py --scorer llm --provider ollama --model qwen2.5:14b
    uv run scripts/run_skills_fit_eval.py --scorer llm --workers 4 --run-id baseline
"""

import argparse
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.skills_fit.baselines import keyword_overlap_analyze
from agents.skills_fit.models import SCHEMA_VERSION
from agents.skills_fit.utils import (
    SKILLS_FIT_PROMPT_PATH,
    analyze_skills_fit,
    load_candidate_profile,
    load_gold,
)
from agent_eval.logger import JsonlRunLogger, RunLogger
from agent_eval.metrics import compute_ordinal_metrics
from agent_eval.provenance import build_run_record, generate_run_id, hash_file

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GOLD_FILE = "data/eval/skills_fit_ground_truth.jsonl"
CONFIG_PATH = "config/agent/skills_fit.yml"
RUNS_FILE = "data/eval/runs.jsonl"
OLD_PROFILES_DIR = Path("config/profile/old_profiles")


class MismatchRecord(BaseModel):
    run_id: str
    record_id: str
    gold_score: int
    pred_score: int
    delta: int
    human_confidence: str | None
    pred_confidence: str | None
    human_notes: str | None
    score_rationale: str


@dataclass(frozen=True)
class RecordEvalResult:
    index: int
    job: dict
    gold_score: int | None
    pred_score: int | None
    pred_confidence: str | None
    pred_rationale: str | None
    elapsed: float
    skipped: bool = False
    skip_reason: str | None = None
    mismatch: MismatchRecord | None = None


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
        "--runs-file", default=RUNS_FILE, help=f"Run log JSONL (default: {RUNS_FILE})"
    )
    p.add_argument(
        "--scorer",
        choices=["llm", "keyword"],
        default="llm",
        help="Which scorer to evaluate (default: llm)",
    )
    p.add_argument("--model", help="Override llm.model in-memory")
    p.add_argument(
        "--temperature", type=float, help="Override llm.temperature in-memory"
    )
    p.add_argument("--provider", help="Override llm.provider in-memory")
    p.add_argument(
        "--prompt",
        help=f"Override the system prompt file (default: {SKILLS_FIT_PROMPT_PATH})",
    )
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
        help="Concurrent inference workers (default: 1). Performance only.",
    )
    p.add_argument(
        "--positive-threshold",
        type=int,
        default=4,
        choices=[1, 2, 3, 4, 5],
        help="Min gold score for precision_at_k (default: 4)",
    )
    args = p.parse_args()
    if args.workers < 1:
        p.error("--workers must be >= 1")
    if args.scorer == "keyword" and args.workers > 1:
        log.warning("keyword scorer is CPU-only and fast; --workers is ignored")
    return args


def _evaluate_record(
    i: int,
    job: dict,
    *,
    scorer: str,
    profile: dict,
    llm_config: dict | None,
    prompt_path: Path,
    run_id: str,
) -> RecordEvalResult:
    gold_score = job.get("_human_fit_score")
    if not isinstance(gold_score, int) or not (1 <= gold_score <= 5):
        return RecordEvalResult(
            index=i,
            job=job,
            gold_score=None,
            pred_score=None,
            pred_confidence=None,
            pred_rationale=None,
            elapsed=0.0,
            skipped=True,
            skip_reason="invalid_human_fit_score",
        )

    description = job.get("description", "")
    if not description:
        return RecordEvalResult(
            index=i,
            job=job,
            gold_score=gold_score,
            pred_score=None,
            pred_confidence=None,
            pred_rationale=None,
            elapsed=0.0,
            skipped=True,
            skip_reason="missing_description",
        )

    title = job.get("title") or None
    location = job.get("location") or None

    t0 = time.monotonic()
    if scorer == "keyword":
        analysis = keyword_overlap_analyze(
            description, candidate_profile=profile, title=title
        )
    else:
        analysis = analyze_skills_fit(
            description,
            candidate_profile=profile,
            title=title,
            location=location,
            llm_config=llm_config,
            prompt_path=prompt_path,
        )
    elapsed = time.monotonic() - t0

    if analysis is None:
        return RecordEvalResult(
            index=i,
            job=job,
            gold_score=gold_score,
            pred_score=None,
            pred_confidence=None,
            pred_rationale=None,
            elapsed=elapsed,
            skipped=True,
            skip_reason="agent_failed",
        )

    pred = analysis.fit_score
    mismatch = None
    if pred != gold_score:
        mismatch = MismatchRecord(
            run_id=run_id,
            record_id=(job.get("dedup_hash", "") or "")[:8],
            gold_score=gold_score,
            pred_score=pred,
            delta=pred - gold_score,
            human_confidence=job.get("_human_confidence"),
            pred_confidence=analysis.confidence,
            human_notes=job.get("_human_notes"),
            score_rationale=analysis.score_rationale,
        )

    return RecordEvalResult(
        index=i,
        job=job,
        gold_score=gold_score,
        pred_score=pred,
        pred_confidence=analysis.confidence,
        pred_rationale=analysis.score_rationale,
        elapsed=elapsed,
        mismatch=mismatch,
    )


def _log_record_result(result: RecordEvalResult) -> None:
    job = result.job
    if result.skipped:
        log.warning(
            "Record %d (%s) skipped — %s",
            result.index,
            job.get("title"),
            result.skip_reason,
        )
        return
    delta = (result.pred_score or 0) - (result.gold_score or 0)
    delta_marker = "  " if delta == 0 else (f"+{delta}" if delta > 0 else f"{delta}")
    log.info(
        "[%3d] gold=%d pred=%d (%s)  %-40s @ %-20s  %.1fs",
        result.index,
        result.gold_score,
        result.pred_score,
        delta_marker,
        (job.get("title") or "?")[:40],
        (job.get("company") or "?")[:20],
        result.elapsed,
    )


def run_eval(
    records: list[dict],
    *,
    scorer: str,
    profile: dict,
    llm_config: dict | None,
    prompt_path: Path,
    run_id: str,
    workers: int,
) -> tuple[list[MismatchRecord], list[int], list[int], list[str], int]:
    if workers == 1 or scorer == "keyword":
        results = [
            _evaluate_record(
                i,
                job,
                scorer=scorer,
                profile=profile,
                llm_config=llm_config,
                prompt_path=prompt_path,
                run_id=run_id,
            )
            for i, job in enumerate(records)
        ]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            try:
                results = list(
                    executor.map(
                        lambda item: _evaluate_record(
                            item[0],
                            item[1],
                            scorer=scorer,
                            profile=profile,
                            llm_config=llm_config,
                            prompt_path=prompt_path,
                            run_id=run_id,
                        ),
                        enumerate(records),
                    )
                )
            except KeyboardInterrupt:
                executor.shutdown(wait=False, cancel_futures=True)
                raise

    preds: list[int] = []
    golds: list[int] = []
    record_ids: list[str] = []
    mismatches: list[MismatchRecord] = []
    skipped = 0

    for r in results:
        _log_record_result(r)
        if r.skipped:
            skipped += 1
            continue
        preds.append(r.pred_score)
        golds.append(r.gold_score)
        # Use full dedup_hash for tie-break stability; truncation collisions
        # would reintroduce input-order dependence. Per-record index fallback
        # keeps every id unique when dedup_hash is missing.
        record_ids.append(r.job.get("dedup_hash") or f"_idx_{r.index}")
        if r.mismatch is not None:
            mismatches.append(r.mismatch)

    return mismatches, preds, golds, record_ids, skipped


def print_report(
    metrics: dict, mismatches: list[MismatchRecord], run_id: str, scorer: str
) -> None:
    m = metrics["metrics"]
    print()
    print("=" * 60)
    print(f"  SKILLS_FIT EVAL — scorer={scorer}")
    print("=" * 60)
    print(f"  Run ID            : {run_id}")
    print(f"  Records evaluated : {m['evaluated']}  (skipped: {m['skipped']})")
    print("-" * 60)
    print(f"  exact_match_acc            : {m['exact_match_acc']:.4f}")
    print(f"  off_by_one_acc             : {m['off_by_one_acc']:.4f}")
    print(f"  mae                        : {m['mae']:.4f}")
    print(f"  bias                       : {m['bias']:+.4f}  (+ = model scores high)")
    print(f"  spearman_rho               : {m['spearman_rho']:.4f}")
    threshold = m["positive_threshold"]
    print(
        f"  precision_at_5 (gold>={threshold})   : {m['precision_at_5']:.4f}  ← top-of-list metric"
    )
    print(f"  precision_at_10 (gold>={threshold})  : {m['precision_at_10']:.4f}")
    print(f"  mean_gold_score_at_top_10  : {m['mean_gold_score_at_top_10']:.4f}")
    print(f"  top_bucket_purity (pred=5) : {m['top_bucket_purity']:.4f}")
    print("-" * 60)
    print("  confusion_5x5 (rows=pred, cols=gold, idx 0-4 = scores 1-5):")
    for i, row in enumerate(m["confusion_5x5"]):
        print(f"    pred={i + 1}: {row}")
    print("=" * 60)

    if mismatches:
        print(f"\n  {len(mismatches)} mismatches:")
        for mm in mismatches[:20]:
            print(
                f"  [delta={mm.delta:+d}] record={mm.record_id}  "
                f"gold={mm.gold_score}  pred={mm.pred_score}  "
                f"conf={mm.pred_confidence}"
            )
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more (see mismatch file)")
    print()


def snapshot_profile(profile_path: Path, profile_version: str) -> Path | None:
    if profile_version == "unknown":
        log.warning(
            "Skipping profile snapshot: candidate_profile.yml has no profile_version"
        )
        return None
    OLD_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = OLD_PROFILES_DIR / f"candidate_profile_{profile_version}.yml"
    if archive_path.exists():
        return archive_path
    shutil.copy(profile_path, archive_path)
    log.info("Profile snapshot written: %s", archive_path)
    return archive_path


def main(run_logger: RunLogger | None = None) -> None:
    args = parse_args()

    gold_path = Path(args.gold)
    if not gold_path.exists():
        log.error("Gold file not found: %s", gold_path)
        log.error(
            "Hand-score the seed gold set first. See specs/skills_fit_agent_plan.md Phase R step 3."
        )
        sys.exit(1)

    with open(args.config) as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))

    # CLI overrides modify config in-memory only; resolved values land in the run record.
    if args.model:
        config.setdefault("llm", {})["model"] = args.model
    if args.temperature is not None:
        config.setdefault("llm", {})["temperature"] = args.temperature
    if args.provider:
        config.setdefault("llm", {})["provider"] = args.provider

    profile_path = Path(
        config.get("profile_file", "config/profile/candidate_profile.yml")
    )
    if not profile_path.exists():
        log.error("Profile file not found: %s", profile_path)
        sys.exit(1)
    profile = load_candidate_profile(profile_path)
    snapshot_profile(profile_path, profile.get("profile_version", "unknown"))

    prompt_path = Path(args.prompt) if args.prompt else SKILLS_FIT_PROMPT_PATH
    if not prompt_path.exists():
        log.error("Prompt file not found: %s", prompt_path)
        sys.exit(1)

    run_id = generate_run_id(args.run_id)
    if run_logger is None:
        run_logger = JsonlRunLogger(args.runs_file)

    records = load_gold(gold_path)
    if not records:
        log.error("Gold file is empty: %s", gold_path)
        sys.exit(1)
    log.info("Loaded %d gold records from %s", len(records), gold_path)
    log.info("Scorer: %s", args.scorer)

    llm_config = config.get("llm") if args.scorer == "llm" else None
    mismatches, preds, golds, record_ids, skipped = run_eval(
        records,
        scorer=args.scorer,
        profile=profile,
        llm_config=llm_config,
        prompt_path=prompt_path,
        run_id=run_id,
        workers=args.workers,
    )

    metrics = compute_ordinal_metrics(
        preds,
        golds,
        skipped=skipped,
        positive_threshold=args.positive_threshold,
        record_ids=record_ids,
    )
    print_report(metrics, mismatches, run_id, args.scorer)

    mismatch_path: Path | None = None
    if mismatches and not args.no_mismatches:
        mismatch_path = Path(f"data/eval/mismatches_{run_id}.jsonl")
        mismatch_path.parent.mkdir(parents=True, exist_ok=True)
        mismatch_path.write_text(
            "\n".join(mm.model_dump_json() for mm in mismatches) + "\n"
        )
        log.info("Mismatches written to %s", mismatch_path)

    prompt_text = prompt_path.read_text()
    run_record = build_run_record(
        run_id=run_id,
        gold_file=gold_path,
        prompt_text=prompt_text,
        config=config,
        config_file=args.config,
        metrics=metrics["metrics"],
        mismatch_file=mismatch_path,
    )
    # Skills_fit-specific provenance: scorer choice + profile hash/version + prompt file.
    run_record["scorer"] = args.scorer
    run_record["profile_file"] = str(profile_path)
    run_record["profile_hash"] = hash_file(profile_path)
    run_record["profile_version"] = profile.get("profile_version", "unknown")
    run_record["prompt_file"] = str(prompt_path)
    run_record["skills_fit_schema_version"] = SCHEMA_VERSION
    # The default policy_thresholds field isn't applicable here; null it out
    # rather than misrepresenting remote-filter policy on a skills-fit run.
    run_record["config"]["policy_thresholds"] = None

    run_logger.log_run(run_record)
    log.info("Run record logged: %s", run_id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — no run record saved.", file=sys.stderr)
        sys.exit(1)
