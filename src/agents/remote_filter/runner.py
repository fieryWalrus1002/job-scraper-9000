import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from agents.remote_filter.cache import DEFAULT_CACHE_PATH, AnalysisCache
from agents.remote_filter.models import SCHEMA_VERSION
from agents.remote_filter.utils import (
    REMOTE_FILTER_PROMPT_PATH,
    analyze_remote,
    context_fingerprint,
    load_raw_jobs,
    passes_remote_filter,
    resolve_provider_and_model,
)
from utils.dedup import dedup_jobs
from utils.git_info import get_git_metadata, get_prompt_hash
from utils.openai_pricing import estimate_cost
from utils.run_tracker import RunTracker

log = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path("data/prefiltered/remote_filter_input.jsonl")
DEFAULT_PASS_PATH = Path("data/filtered/remote_filter_pass.jsonl")
DEFAULT_TRASH_PATH = Path("data/trash/remote_filter_trash.jsonl")
DEFAULT_CONFIG_PATH = Path("config/agent/remote_agent.yml")


def load_remote_filter_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    with open(config_path) as f:
        return yaml.safe_load(os.path.expandvars(f.read())) or {}


def build_filter_metadata() -> dict[str, Any]:
    git_meta = get_git_metadata()
    prompt_hash = (
        get_prompt_hash(REMOTE_FILTER_PROMPT_PATH)
        if REMOTE_FILTER_PROMPT_PATH.exists()
        else "unknown"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_hash": prompt_hash,
        "prompt_file": REMOTE_FILTER_PROMPT_PATH.name,
        "commit": git_meta["commit"],
        "dirty": git_meta["dirty"],
        "filtered_at": git_meta["timestamp"],
    }


def _infer_run_date(path: Path) -> str | None:
    """Extract YYYY-MM-DD from a path part if present (e.g., data/prefiltered/2026-05-21/...)."""
    for part in path.parts:
        if len(part) == 10 and part.count("-") == 2:
            try:
                datetime.strptime(part, "%Y-%m-%d")
                return part
            except ValueError:
                continue
    return None


def run_remote_filter(
    *,
    input_path: str | Path = DEFAULT_INPUT_DIR,
    pass_path: str | Path = DEFAULT_PASS_PATH,
    trash_path: str | Path = DEFAULT_TRASH_PATH,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    user_location: str = "USA",
    user_timezone: str | None = None,
    cache_path: str | Path | None = DEFAULT_CACHE_PATH,
    run_type: str = "production",
    parent_run_id: str | None = None,
) -> dict[str, int]:
    """Run the remote-filter agent over routed candidate jobs and split pass/trash JSONL outputs.

    Within-batch duplicates (by `dedup_hash` / `source_job_id`) are collapsed to
    a single LLM call. Pass `cache_path=None` to disable the across-batch cache.
    Telemetry is written to ``data/runs/runs.jsonl`` via ``RunTracker``.
    """
    input_path = Path(input_path)
    pass_path = Path(pass_path)
    trash_path = Path(trash_path)
    config = load_remote_filter_config(config_path)
    llm_config = config.get("llm") or {}

    jobs = load_raw_jobs(input_path)
    if not jobs:
        raise FileNotFoundError(f"No jobs found in {input_path}")

    total_loaded = len(jobs)
    jobs, deduped = dedup_jobs(jobs)
    if deduped:
        log.info(
            "Within-batch dedup dropped %d of %d jobs (%.1f%%)",
            deduped,
            total_loaded,
            100 * deduped / total_loaded,
        )

    log.info("Running remote-filter on %d jobs...", len(jobs))

    filter_meta = build_filter_metadata()
    log.info(
        "Filter metadata: schema=%s prompt=%s commit=%s dirty=%s",
        SCHEMA_VERSION,
        filter_meta["prompt_hash"],
        filter_meta["commit"][:12],
        filter_meta["dirty"],
    )

    cache = AnalysisCache(cache_path) if cache_path is not None else None
    provider, model = resolve_provider_and_model(llm_config)
    prompt_hash = filter_meta["prompt_hash"]

    pass_path.parent.mkdir(parents=True, exist_ok=True)
    trash_path.parent.mkdir(parents=True, exist_ok=True)

    passed = failed = skipped = cache_hits = cache_misses = 0

    with RunTracker(
        component="remote_filter",
        run_type=run_type,
        run_date=_infer_run_date(input_path),
        parent_run_id=parent_run_id,
    ) as run:
        run.set_input(
            path=str(input_path),
            record_count=total_loaded,
            dedup_dropped=deduped,
            deduped_record_count=len(jobs),
        )
        run.set_config(
            agent_config_path=str(config_path),
            prompt_path=str(REMOTE_FILTER_PROMPT_PATH),
            prompt_hash=prompt_hash,
        )
        run.set_llm(
            provider=provider,
            model=model,
            endpoint=llm_config.get("base_url"),
            api_key_env=(
                llm_config.get("api_key_env", "OPENAI_API_KEY")
                if provider != "ollama"
                else None
            ),
            temperature=llm_config.get("temperature", 0.1),
        )

        try:
            with (
                pass_path.open("w", encoding="utf-8") as pass_f,
                trash_path.open("w", encoding="utf-8") as trash_f,
            ):
                for job in jobs:
                    description = job.get("description", "")
                    title = job.get("title", "")
                    company = job.get("company", "")
                    location = job.get("location") or None

                    if not description:
                        log.warning("Skipping %s @ %s — no description", title, company)
                        skipped += 1
                        continue

                    search_context = {
                        **(job.get("search_params") or {}),
                        **({"user_timezone": user_timezone} if user_timezone else {}),
                    }
                    dedup_key = job.get("dedup_hash") or job.get("source_job_id") or ""
                    context_fp = context_fingerprint(search_context)
                    analysis = None
                    from_cache = False
                    cache_keyable = cache is not None and bool(dedup_key)
                    if cache_keyable:
                        assert cache is not None
                        analysis = cache.get(
                            dedup_hash=dedup_key,
                            prompt_hash=prompt_hash,
                            provider=provider,
                            model=model,
                            context_fp=context_fp,
                        )
                        if analysis is not None:
                            from_cache = True
                            cache_hits += 1
                        else:
                            # Count the miss at lookup time so the hit-rate metric
                            # stays honest even when the LLM call below fails.
                            cache_misses += 1

                    if analysis is None:
                        call_started = time.time()
                        analysis = analyze_remote(
                            description,
                            title=title,
                            location=location,
                            search_context=search_context or None,
                            llm_config=llm_config,
                            usage_callback=run.add_token_usage,
                        )
                        run.record_call_latency(time.time() - call_started)
                        if analysis is None:
                            log.warning(
                                "Agent failed on %s @ %s — skipping", title, company
                            )
                            skipped += 1
                            run.increment_failures()
                            continue
                        if cache_keyable:
                            assert cache is not None
                            cache.put(
                                dedup_hash=dedup_key,
                                prompt_hash=prompt_hash,
                                provider=provider,
                                model=model,
                                context_fp=context_fp,
                                analysis=analysis,
                            )

                    ok, reason = passes_remote_filter(analysis, config, user_location)

                    enriched = {
                        **job,
                        "_remote_analysis": analysis.model_dump(),
                        "_filter_result": "pass" if ok else "trash",
                        "_filter_reason": reason,
                        "_filter_metadata": {**filter_meta, "from_cache": from_cache},
                    }

                    if ok:
                        pass_f.write(json.dumps(enriched) + "\n")
                        passed += 1
                        log.info(
                            "PASS  %s @ %s (%s)%s",
                            title,
                            company,
                            analysis.remote_classification,
                            " [cached]" if from_cache else "",
                        )
                    else:
                        trash_f.write(json.dumps(enriched) + "\n")
                        failed += 1
                        log.info(
                            "TRASH %s @ %s — %s%s",
                            title,
                            company,
                            reason,
                            " [cached]" if from_cache else "",
                        )
        finally:
            # Roll up counts and cost even if the loop raised, so partial-run
            # records still carry as much information as possible.
            run.add_output(label="pass", path=str(pass_path), record_count=passed)
            run.add_output(label="trash", path=str(trash_path), record_count=failed)
            if skipped:
                run.add_output(label="skipped", record_count=skipped)
            if cache is not None:
                run.set_cache(
                    path=str(cache_path), hits=cache_hits, misses=cache_misses
                )
            run.update_llm_stats(calls_made=cache_misses)
            if provider == "openai":
                breakdown = estimate_cost(model, batch=False, **run.token_totals)
                if breakdown is not None:
                    total = breakdown.pop("total")
                    run.set_cost(estimated_total=total, breakdown=breakdown)
                else:
                    run.add_notable(
                        f"No pricing entry for model '{model}' — actual cost will need backfill"
                    )

        cache_lookups = cache_hits + cache_misses
        cache_hit_pct = (100 * cache_hits / cache_lookups) if cache_lookups else 0.0
        log.info(
            "Done — %d pass | %d trash | %d skipped | %d deduped | cache %d/%d hits (%.1f%%) | run_id=%s",
            passed,
            failed,
            skipped,
            deduped,
            cache_hits,
            cache_lookups,
            cache_hit_pct,
            run.run_id,
        )

    return {
        "pass": passed,
        "trash": failed,
        "skipped": skipped,
        "total": len(jobs),
        "input_total": total_loaded,
        "deduped": deduped,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
    }
