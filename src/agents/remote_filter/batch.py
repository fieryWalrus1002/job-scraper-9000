"""OpenAI Batch API path for the remote-filter agent.

Production twin of the serial runner (``runner.run_remote_filter``): instead of
one synchronous LLM call per job, it submits every cache-miss job as a single
Batch API request, blocks until the batch reaches a terminal state, then writes
the same pass/trash JSONL the live path produces. Cache hits never enter the
batch. OpenAI-only — the Batch API has no ollama equivalent, so we fail fast.

Request building and result parsing live here (not imported from the eval
``scripts/``) so production code never depends on a script; they mirror the
eval-batch plumbing closely on purpose.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from utils.batch_api import (
    BATCH_ENDPOINT,
    download_results,
    poll_until_done,
    upload_and_create_batch,
)
from utils.dedup import dedup_jobs
from utils.openai_pricing import estimate_cost
from utils.run_tracker import RunTracker

from .cache import DEFAULT_CACHE_PATH, AnalysisCache
from .models import RemoteAnalysis
from .runner import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_INPUT_DIR,
    DEFAULT_PASS_PATH,
    DEFAULT_TRASH_PATH,
    _infer_run_date,
    build_filter_metadata,
    load_remote_filter_config,
)
from .utils import (
    REMOTE_FILTER_PROMPT_PATH,
    _build_user_message,
    _get_client,
    build_search_context,
    context_fingerprint,
    load_raw_jobs,
    passes_remote_filter,
    resolve_provider_and_model,
)

log = logging.getLogger(__name__)

DEFAULT_BATCH_DIR = Path("data/batch")


def build_request(
    job: dict[str, Any],
    idx: int,
    *,
    model: str,
    temperature: float,
    prompt_text: str,
    user_timezone: str | None = None,
) -> dict[str, Any]:
    """Build one Batch API request line for a job.

    ``custom_id`` is ``job-<idx>``; the caller maps results back by that id, so
    ``idx`` must match the request's position in the submitted file.
    """
    search_context = build_search_context(job, user_timezone)
    user_message = _build_user_message(
        job.get("description", ""),
        search_context=search_context or None,
        location=job.get("location") or None,
        title=job.get("title") or None,
    )
    return {
        "custom_id": f"job-{idx}",
        "method": "POST",
        "url": BATCH_ENDPOINT,
        "body": {
            "model": model,
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "remote_analysis",
                    "schema": RemoteAnalysis.model_json_schema(),
                },
            },
            "messages": [
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": user_message},
            ],
        },
    }


def parse_analysis(item: dict[str, Any]) -> RemoteAnalysis | None:
    """Parse one Batch API output line into a ``RemoteAnalysis``.

    Returns ``None`` (and warns) for errored items, non-200 responses, missing
    content, or schema-invalid content — the caller skips those jobs rather than
    aborting the whole run.
    """
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


def _usage_from_item(item: dict[str, Any]) -> dict[str, int]:
    """Pull token counts from a Batch API output line's response body.

    Each completed batch line carries the same ``usage`` block a live call
    returns, so we can feed real token totals into telemetry/cost.
    """
    body = (item.get("response") or {}).get("body") or {}
    usage = body.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "input_tokens": usage.get("prompt_tokens", 0) or 0,
        "cached_input_tokens": details.get("cached_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or 0,
    }


def _write_request_file(requests: list[dict[str, Any]], run_id: str) -> Path:
    path = DEFAULT_BATCH_DIR / f"remote_filter_requests_{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for req in requests:
            f.write(json.dumps(req) + "\n")
    log.info("Wrote %d batch requests → %s", len(requests), path)
    return path


def _index_results(content: str) -> dict[str, dict[str, Any]]:
    """Index a downloaded batch output file by ``custom_id``."""
    results: dict[str, dict[str, Any]] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        custom_id = item.get("custom_id")
        if custom_id:
            results[custom_id] = item
    return results


def _log_batch_failure(client, batch, run_id: str) -> None:
    """Persist a failed batch's error file (if any) so the failure is auditable."""
    error_file_id = getattr(batch, "error_file_id", None)
    if not error_file_id:
        return
    path = DEFAULT_BATCH_DIR / f"remote_filter_errors_{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(client.files.content(error_file_id).text, encoding="utf-8")
    log.error("Batch error file written to %s", path)


def run_remote_filter_batch(
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
    poll_interval: int = 60,
) -> dict[str, int]:
    """Run remote-filter over routed candidates via the OpenAI Batch API.

    Submits all cache-miss jobs as one batch, polls until terminal, then writes
    the same enriched pass/trash JSONL as ``run_remote_filter``. OpenAI-only.
    """
    input_path = Path(input_path)
    pass_path = Path(pass_path)
    trash_path = Path(trash_path)
    config = load_remote_filter_config(config_path)
    llm_config = config.get("llm") or {}

    provider, model = resolve_provider_and_model(llm_config)
    if provider != "openai":
        raise ValueError(
            f"--batch requires provider=openai; the config resolves to "
            f"provider={provider!r}. The OpenAI Batch API has no ollama "
            f"equivalent — drop --batch to run the serial path."
        )

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

    filter_meta = build_filter_metadata()
    prompt_hash = filter_meta["prompt_hash"]
    prompt_text = REMOTE_FILTER_PROMPT_PATH.read_text()
    temperature = llm_config.get("temperature", 0.1)

    cache = AnalysisCache(cache_path) if cache_path is not None else None

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
            api_key_env=llm_config.get("api_key_env", "OPENAI_API_KEY"),
            temperature=temperature,
        )

        submitted = 0
        try:
            # --- Pass 1: cache lookup; queue misses for the batch ---
            requests: list[dict[str, Any]] = []
            plan: list[dict[str, Any]] = []
            for job in jobs:
                if not job.get("description"):
                    log.warning(
                        "Skipping %s @ %s — no description",
                        job.get("title", ""),
                        job.get("company", ""),
                    )
                    skipped += 1
                    continue

                search_context = build_search_context(job, user_timezone)
                dedup_key = job.get("dedup_hash") or job.get("source_job_id") or ""
                context_fp = context_fingerprint(search_context)

                analysis = None
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
                        cache_hits += 1
                    else:
                        cache_misses += 1

                entry = {
                    "job": job,
                    "analysis": analysis,
                    "from_cache": analysis is not None,
                    "dedup_key": dedup_key,
                    "context_fp": context_fp,
                    "custom_id": None,
                }
                if analysis is None:
                    idx = len(requests)
                    requests.append(
                        build_request(
                            job,
                            idx,
                            model=model,
                            temperature=temperature,
                            prompt_text=prompt_text,
                            user_timezone=user_timezone,
                        )
                    )
                    entry["custom_id"] = f"job-{idx}"
                plan.append(entry)

            submitted = len(requests)

            # --- Submit + poll + download (skip entirely if all cached) ---
            results: dict[str, dict[str, Any]] = {}
            if requests:
                request_file = _write_request_file(requests, run.run_id)
                client, _ = _get_client(llm_config)
                batch_id, _input_file_id = upload_and_create_batch(client, request_file)
                log.info(
                    "Submitted %d requests as batch %s — polling every %ds",
                    submitted,
                    batch_id,
                    poll_interval,
                )
                batch = poll_until_done(client, batch_id, poll_interval)
                if batch.status != "completed":
                    _log_batch_failure(client, batch, run.run_id)
                    raise RuntimeError(
                        f"Batch {batch.id} ended with status={batch.status}"
                    )
                results = _index_results(download_results(client, batch))
            else:
                log.info(
                    "All %d jobs served from cache — no batch submitted", len(plan)
                )

            # --- Pass 2: resolve analyses, gate, write pass/trash ---
            with (
                pass_path.open("w", encoding="utf-8") as pass_f,
                trash_path.open("w", encoding="utf-8") as trash_f,
            ):
                for entry in plan:
                    job = entry["job"]
                    title = job.get("title", "")
                    company = job.get("company", "")
                    analysis = entry["analysis"]

                    if analysis is None:
                        item = results.get(entry["custom_id"])
                        if item is None:
                            log.warning(
                                "No batch result for %s (%s @ %s) — skipping",
                                entry["custom_id"],
                                title,
                                company,
                            )
                            skipped += 1
                            run.increment_failures()
                            continue
                        run.add_token_usage(_usage_from_item(item))
                        analysis = parse_analysis(item)
                        if analysis is None:
                            log.warning(
                                "Agent failed on %s @ %s — skipping", title, company
                            )
                            skipped += 1
                            run.increment_failures()
                            continue
                        if cache is not None and entry["dedup_key"]:
                            cache.put(
                                dedup_hash=entry["dedup_key"],
                                prompt_hash=prompt_hash,
                                provider=provider,
                                model=model,
                                context_fp=entry["context_fp"],
                                analysis=analysis,
                            )

                    ok, reason = passes_remote_filter(analysis, config, user_location)
                    enriched = {
                        **job,
                        "_remote_analysis": analysis.model_dump(),
                        "_filter_result": "pass" if ok else "trash",
                        "_filter_reason": reason,
                        "_filter_metadata": {
                            **filter_meta,
                            "from_cache": entry["from_cache"],
                        },
                    }
                    if ok:
                        pass_f.write(json.dumps(enriched) + "\n")
                        passed += 1
                        log.info(
                            "PASS  %s @ %s (%s)%s",
                            title,
                            company,
                            analysis.remote_classification,
                            " [cached]" if entry["from_cache"] else "",
                        )
                    else:
                        trash_f.write(json.dumps(enriched) + "\n")
                        failed += 1
                        log.info(
                            "TRASH %s @ %s — %s%s",
                            title,
                            company,
                            reason,
                            " [cached]" if entry["from_cache"] else "",
                        )
        finally:
            run.add_output(label="pass", path=str(pass_path), record_count=passed)
            run.add_output(label="trash", path=str(trash_path), record_count=failed)
            if skipped:
                run.add_output(label="skipped", record_count=skipped)
            if cache is not None:
                run.set_cache(
                    path=str(cache_path), hits=cache_hits, misses=cache_misses
                )
            run.update_llm_stats(calls_made=submitted)
            breakdown = estimate_cost(model, batch=True, **run.token_totals)
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
            "Done (batch) — %d pass | %d trash | %d skipped | %d deduped | "
            "%d submitted | cache %d/%d hits (%.1f%%) | run_id=%s",
            passed,
            failed,
            skipped,
            deduped,
            submitted,
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
        "submitted": submitted,
    }
