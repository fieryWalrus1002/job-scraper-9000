import functools
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any


import yaml
from dotenv import load_dotenv

from agent_eval.provenance import generate_run_id, hash_file
from agents.skills_fit.cache import DEFAULT_CACHE_PATH, AnalysisCache
from agents.skills_fit.models import (
    InputSource,
    JobMetadata,
    SkillsFitAnalysis,
    ScoredJobPosting,
)
from agents.skills_fit.utils import (
    SKILLS_FIT_PROMPT_PATH,
    analyze_skills_fit,
    load_candidate_profile,
)
from agents.skills_fit.cli import (
    DEFAULT_CONFIG_PATH,
    resolve_paths,
    apply_llm_overrides,
    configure_logging,
    parse_args,
)

from agents.skills_fit.io import (
    is_processed_output_record,
    load_existing_output_records,
    load_tagged_inputs,
    validate_dedup_hashes,
    write_output,
)

from utils.concurrent import imap_unordered
from utils.dedup import dedup_jobs
from utils.git_info import get_git_metadata
from utils.openai_pricing import estimate_cost
from utils.run_tracker import RunTracker

load_dotenv()

log = logging.getLogger(__name__)


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(os.path.expandvars(f.read())) or {}


def resolve_provider_and_model(llm_config: dict[str, Any] | None) -> tuple[str, str]:
    cfg = llm_config or {}
    provider = cfg.get("provider", os.environ.get("LLM_PROVIDER", "openai")).lower()
    default_model = "qwen2.5:14b" if provider == "ollama" else "gpt-4o-mini"
    model = cfg.get("model", os.environ.get("LLM_MODEL", default_model))
    return provider, model


def infer_run_date(*paths: Path) -> str | None:
    for path in paths:
        for part in path.parts:
            if len(part) == 10 and part.count("-") == 2:
                try:
                    datetime.strptime(part, "%Y-%m-%d")
                    return part
                except ValueError:
                    continue
    return None


_PIPELINE_KEYS = frozenset(
    {
        "scrub_counts",
        "search_params",
        "_prefilter_result",
        "_prefilter_reason",
        "_prefilter_metadata",
        "_remote_analysis",
        "_filter_result",
        "_filter_reason",
        "_filter_metadata",
    }
)


def _build_scored_posting(
    job: dict[str, Any],
    *,
    ai_fit: SkillsFitAnalysis | None,
    metadata: JobMetadata,
) -> dict[str, Any]:
    remote_analysis = job.get("_remote_analysis") or {}
    return ScoredJobPosting(
        dedup_hash=job["dedup_hash"],
        source=job.get("source"),
        source_job_id=job.get("source_job_id"),
        source_url=job.get("source_url"),
        title=job.get("title"),
        company=job.get("company"),
        location=job.get("location"),
        posted_at=job.get("posted_at"),
        description=job.get("description"),
        scraped_at=job.get("scraped_at"),
        salary_min_usd=job.get("salary_min_usd"),
        salary_max_usd=job.get("salary_max_usd"),
        salary_period=job.get("salary_period"),
        remote_classification=remote_analysis.get("remote_classification")
        or job.get("remote_classification"),
        pipeline_metadata={k: v for k, v in job.items() if k in _PIPELINE_KEYS},
        ai_fit=ai_fit,
        metadata=metadata,
    ).model_dump(mode="json", exclude_none=True)


def build_record_metadata(
    *,
    run_id: str,
    scored_at: datetime,
    config_file: Path,
    prompt_file: Path,
    prompt_hash: str,
    profile_file: Path,
    profile_hash: str,
    profile_version: str,
    provider: str,
    model: str,
    temperature: float | None,
    git_metadata: dict[str, Any],
    input_source: InputSource,
    input_path: str,
    failure_reason: str | None = None,
) -> JobMetadata:
    return JobMetadata(
        run_id=run_id,
        scored_at=scored_at,
        config_file=str(config_file),
        prompt_file=str(prompt_file),
        prompt_hash=prompt_hash,
        profile_file=str(profile_file),
        profile_hash=profile_hash,
        profile_version=profile_version,
        provider=provider,
        model=model,
        temperature=temperature,
        commit=git_metadata["commit"],
        dirty=git_metadata["dirty"],
        input_source=input_source,
        input_path=input_path,
        failure_reason=failure_reason,
    )


def run_skills_fit(
    *,
    run_date: str | None = None,
    remote_input: str | Path | None = None,
    local_input: str | Path | None = None,
    output: str | Path | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    profile_file: str | Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    limit: int | None = None,
    run_type: str = "production",
    parent_run_id: str | None = None,
) -> dict[str, Any]:
    resolved_paths = resolve_paths(
        run_date=run_date,
        remote_input=remote_input,
        local_input=local_input,
        output=output,
    )
    run_id = generate_run_id("skillsfit")

    config_file = Path(config_path)
    prompt_file = Path(SKILLS_FIT_PROMPT_PATH)
    cache_path = DEFAULT_CACHE_PATH
    tracker_run_date = run_date or infer_run_date(
        resolved_paths.remote_input,
        resolved_paths.local_input,
        resolved_paths.output,
    )

    cache_hits = 0
    cache_misses = 0
    resumed_existing = 0
    scored_successfully = 0
    skipped_missing_description = 0
    failed_agent = 0
    deduped = 0
    remote_records: list[dict[str, Any]] = []
    local_records: list[dict[str, Any]] = []
    merged_records: list[dict[str, Any]] = []
    deduped_records: list[dict[str, Any]] = []
    enriched_records: list[dict[str, Any]] = []

    with RunTracker(
        component="skills_fit",
        run_type=run_type,
        run_date=tracker_run_date,
        run_id=run_id,
        parent_run_id=parent_run_id,
    ) as run:
        run.record.extras.update(
            {
                "remote_input_path": str(resolved_paths.remote_input),
                "local_input_path": str(resolved_paths.local_input),
                "output_path": str(resolved_paths.output),
                "cache_path": str(cache_path),
                "path_overrides": {
                    "remote_input": remote_input is not None,
                    "local_input": local_input is not None,
                    "output": output is not None,
                },
            }
        )

        config = apply_llm_overrides(
            load_config(config_file),
            provider=provider,
            model=model,
            temperature=temperature,
        )
        llm_config = config.get("llm") or {}
        max_workers = int(llm_config.get("max_workers", 8))
        config_hash = hash_file(config_file)

        profile_file = Path(
            profile_file
            if profile_file is not None
            else config.get("profile_file", "config/profile/candidate_profile.yml")
        )
        if not profile_file.exists():
            raise FileNotFoundError(f"Profile file not found: {profile_file}")
        profile = load_candidate_profile(profile_file)
        profile_hash = hash_file(profile_file)
        profile_version = profile.get("profile_version", "unknown")

        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
        prompt_hash = hash_file(prompt_file)

        provider_name, model_name = resolve_provider_and_model(llm_config)
        resolved_temperature = llm_config.get("temperature")
        git_metadata = get_git_metadata()
        scored_at = datetime.fromisoformat(git_metadata["timestamp"])
        cache = AnalysisCache(cache_path)
        _build_metadata = functools.partial(
            build_record_metadata,
            run_id=run_id,
            scored_at=scored_at,
            config_file=config_file,
            prompt_file=prompt_file,
            prompt_hash=prompt_hash,
            profile_file=profile_file,
            profile_hash=profile_hash,
            profile_version=profile_version,
            provider=provider_name,
            model=model_name,
            temperature=resolved_temperature,
            git_metadata=git_metadata,
        )

        run.set_config(
            agent_config_path=str(config_file),
            agent_config_hash=config_hash,
            prompt_path=str(prompt_file),
            prompt_hash=prompt_hash,
            profile_version=profile_version,
            profile_hash=profile_hash,
        )
        run.set_llm(
            provider=provider_name,
            model=model_name,
            endpoint=llm_config.get("base_url"),
            api_key_env=(
                llm_config.get("api_key_env", "OPENAI_API_KEY")
                if provider_name != "ollama"
                else None
            ),
            temperature=resolved_temperature,
        )

        remote_records, local_records = load_tagged_inputs(
            remote_input=resolved_paths.remote_input,
            local_input=resolved_paths.local_input,
        )
        merged_records = remote_records + local_records
        validate_dedup_hashes(merged_records)
        deduped_records, deduped = dedup_jobs(merged_records)

        if limit is not None:
            deduped_records = deduped_records[:limit]
            log.info("Limiting run to first %d deduped records", len(deduped_records))
            run.add_notable(f"Limited run to {len(deduped_records)} deduped records")

        run.set_input(
            path=str(resolved_paths.remote_input),
            record_count=len(merged_records),
            dedup_dropped=deduped,
            deduped_record_count=len(deduped_records),
        )
        run.record.extras.update(
            {
                "remote_loaded": len(remote_records),
                "local_loaded": len(local_records),
                "merged_before_dedupe": len(merged_records),
                "local_input_exists": resolved_paths.local_input.exists(),
            }
        )

        log.info(
            "Loaded %d remote + %d local = %d merged records (%d after dedupe)",
            len(remote_records),
            len(local_records),
            len(merged_records),
            len(deduped_records),
        )

        existing_output_records = load_existing_output_records(resolved_paths.output)
        run.record.extras["existing_output_loaded"] = len(existing_output_records)
        if existing_output_records:
            log.info(
                "Loaded %d existing scored rows from %s",
                len(existing_output_records),
                resolved_paths.output,
            )

        # Results keyed by original input index for stable output ordering
        # regardless of concurrent completion order.
        results_by_index: dict[int, dict[str, Any]] = {}

        try:
            # --- Phase 1: Plan pass (main thread) ---
            # Handle resume-existing and missing-description inline; partition
            # remaining jobs into cache hits (no LLM call) and cache misses
            # (need concurrent LLM call).
            cache_hit_items: list[dict[str, Any]] = []
            cache_miss_items: list[dict[str, Any]] = []

            for orig_idx, job in enumerate(deduped_records):
                existing = existing_output_records.get(str(job["dedup_hash"]))
                if existing is not None and is_processed_output_record(existing):
                    results_by_index[orig_idx] = existing
                    resumed_existing += 1
                    continue

                input_source: InputSource = job["__input_source"]
                input_path = job["__input_path"]
                title = job.get("title") or None
                location = job.get("location") or None
                description = job.get("description") or ""

                if not description:
                    log.warning(
                        "Skipping %s — missing description",
                        title or job["dedup_hash"],
                    )
                    skipped_missing_description += 1
                    metadata = _build_metadata(
                        input_source=input_source,
                        input_path=input_path,
                        failure_reason="missing_description",
                    )
                    results_by_index[orig_idx] = _build_scored_posting(
                        job, ai_fit=None, metadata=metadata
                    )
                    continue

                analysis = cache.get(
                    dedup_hash=str(job["dedup_hash"]),
                    prompt_hash=prompt_hash,
                    provider=provider_name,
                    model=model_name,
                    profile_version=profile_version,
                )
                if analysis is not None:
                    cache_hits += 1
                    cache_hit_items.append(
                        {
                            "orig_idx": orig_idx,
                            "job": job,
                            "analysis": analysis,
                            "input_source": input_source,
                            "input_path": input_path,
                        }
                    )
                else:
                    cache_misses += 1
                    cache_miss_items.append(
                        {
                            "orig_idx": orig_idx,
                            "job": job,
                            "description": description,
                            "title": title,
                            "location": location,
                            "input_source": input_source,
                            "input_path": input_path,
                        }
                    )

            # --- Phase 2: Process cache hits (main thread, no LLM call) ---
            for hit in cache_hit_items:
                metadata = _build_metadata(
                    input_source=hit["input_source"],
                    input_path=hit["input_path"],
                )
                results_by_index[hit["orig_idx"]] = _build_scored_posting(
                    hit["job"], ai_fit=hit["analysis"], metadata=metadata
                )
                scored_successfully += 1

            # --- Phase 3: Concurrent LLM calls for cache misses ---
            def _work(miss: dict[str, Any]) -> tuple:
                usage: dict[str, int] = {}
                started = time.time()
                analysis = analyze_skills_fit(
                    miss["description"],
                    candidate_profile=profile,
                    title=miss["title"],
                    location=miss["location"],
                    llm_config=llm_config,
                    prompt_path=prompt_file,
                    usage_callback=lambda u: usage.update(u),
                )
                return (analysis, usage, time.time() - started)  # type: ignore[return-value]

            try:
                for miss, (analysis, usage, elapsed) in imap_unordered(
                    _work, cache_miss_items, max_workers=max_workers
                ):
                    # Sink — all shared-state mutations on main thread
                    run.add_token_usage(usage)
                    run.record_call_latency(elapsed)

                    if analysis is not None:
                        cache.put(
                            dedup_hash=str(miss["job"]["dedup_hash"]),
                            prompt_hash=prompt_hash,
                            provider=provider_name,
                            model=model_name,
                            profile_version=profile_version,
                            analysis=analysis,
                        )

                    if analysis is None:
                        log.warning(
                            "Agent failed on %s",
                            miss["title"] or miss["job"]["dedup_hash"],
                        )
                        failed_agent += 1
                        run.increment_failures()
                        metadata = _build_metadata(
                            input_source=miss["input_source"],
                            input_path=miss["input_path"],
                            failure_reason="agent_failed",
                        )
                        results_by_index[miss["orig_idx"]] = _build_scored_posting(
                            miss["job"], ai_fit=None, metadata=metadata
                        )
                    else:
                        metadata = _build_metadata(
                            input_source=miss["input_source"],
                            input_path=miss["input_path"],
                        )
                        results_by_index[miss["orig_idx"]] = _build_scored_posting(
                            miss["job"], ai_fit=analysis, metadata=metadata
                        )
                        scored_successfully += 1
            except KeyboardInterrupt:
                # Build partial results from whatever we've collected so far
                if results_by_index:
                    enriched_records = [
                        results_by_index[i] for i in sorted(results_by_index)
                    ]
                    write_output(enriched_records, resolved_paths.output)
                    message = (
                        f"Interrupted — wrote {len(enriched_records)} partial records to "
                        f"{resolved_paths.output}"
                    )
                else:
                    message = "Interrupted before any records were written"
                log.warning(message)
                run.add_notable(message)
                raise

            # Build final ordered list — sorted by original input index so output
            # order is deterministic regardless of concurrent completion order.
            enriched_records = [results_by_index[i] for i in sorted(results_by_index)]
            write_output(enriched_records, resolved_paths.output)
        finally:
            run.add_output(
                label="scored_rows",
                path=str(resolved_paths.output),
                record_count=len(enriched_records),
            )
            if scored_successfully:
                run.add_output(
                    label="scored_successfully", record_count=scored_successfully
                )
            if resumed_existing:
                run.add_output(label="reused_existing", record_count=resumed_existing)
            if skipped_missing_description:
                run.add_output(
                    label="missing_description",
                    record_count=skipped_missing_description,
                )
            if failed_agent:
                run.add_output(label="agent_failed", record_count=failed_agent)

            run.set_cache(path=str(cache_path), hits=cache_hits, misses=cache_misses)
            run.update_llm_stats(calls_made=cache_misses, calls_failed=failed_agent)
            run.record.extras.update(
                {
                    "merged_after_dedupe": len(deduped_records),
                    "deduped": deduped,
                    "resumed_existing": resumed_existing,
                    "scored_successfully": scored_successfully,
                    "skipped_missing_description": skipped_missing_description,
                    "failed_agent": failed_agent,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                }
            )
            if resumed_existing:
                run.add_notable(f"Reused existing scored rows: {resumed_existing}")
            if skipped_missing_description:
                run.add_notable(
                    f"Skipped missing description: {skipped_missing_description}"
                )
            if failed_agent:
                run.add_notable(f"Agent failures: {failed_agent}")
            if provider_name == "openai":
                token_totals = run.token_totals
                breakdown = estimate_cost(
                    model_name,
                    input_tokens=token_totals["input_tokens"],
                    cached_input_tokens=token_totals["cached_input_tokens"],
                    output_tokens=token_totals["output_tokens"],
                )
                if breakdown is not None:
                    total = breakdown.pop("total")
                    run.set_cost(estimated_total=total, breakdown=breakdown)
                else:
                    run.add_notable(
                        f"No pricing entry for model '{model_name}' — actual cost will need backfill"
                    )

    if resumed_existing:
        log.info("Reused existing scored rows: %d", resumed_existing)
    log.info("Cache hits: %d", cache_hits)
    log.info("Cache misses: %d", cache_misses)
    log.info("Scored successfully: %d", scored_successfully)
    log.info("Skipped missing description: %d", skipped_missing_description)
    log.info("Failed agent: %d", failed_agent)
    log.info("Wrote %d records to %s", len(enriched_records), resolved_paths.output)

    return {
        "run_id": run_id,
        "remote_loaded": len(remote_records),
        "local_loaded": len(local_records),
        "merged_before_dedupe": len(merged_records),
        "merged_after_dedupe": len(deduped_records),
        "deduped": deduped,
        "scored_successfully": scored_successfully,
        "skipped_missing_description": skipped_missing_description,
        "failed_agent": failed_agent,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "output_path": str(resolved_paths.output),
    }


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    try:
        if getattr(args, "batch", False):
            from agents.skills_fit.batch import run_skills_fit_batch

            run_skills_fit_batch(
                run_date=args.run_date,
                remote_input=args.remote_input,
                local_input=args.local_input,
                output=args.output,
                config_path=args.config,
                provider=args.provider,
                model=args.model,
                temperature=args.temperature,
                limit=args.limit,
                poll_interval=getattr(args, "poll_interval", 60),
            )
        else:
            run_skills_fit(
                run_date=args.run_date,
                remote_input=args.remote_input,
                local_input=args.local_input,
                output=args.output,
                config_path=args.config,
                provider=args.provider,
                model=args.model,
                temperature=args.temperature,
                limit=args.limit,
            )
    except (FileNotFoundError, ValueError) as exc:
        log.error(str(exc))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
