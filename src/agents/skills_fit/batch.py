"""OpenAI Batch API path for the skills-fit agent.

Production twin of ``runner.run_skills_fit``: queue cache-miss job/profile
scoring requests into one OpenAI Batch job, poll until terminal, then write the
same scored JSONL shape as the serial path. Cache hits and already-processed
output rows never enter the batch. OpenAI-only — fail fast for ollama/local
providers because the Batch API has no equivalent there.
"""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI
from openai.types import Batch
from pydantic import ValidationError

from agent_eval.provenance import generate_run_id, hash_file
from agents.skills_fit.cache import DEFAULT_CACHE_PATH, AnalysisCache
from agents.skills_fit.cli import (
    DEFAULT_CONFIG_PATH,
    apply_llm_overrides,
    resolve_paths,
)
from agents.skills_fit.io import (
    is_processed_output_record,
    load_existing_output_records,
    load_tagged_inputs,
    validate_dedup_hashes,
    write_output,
)
from agents.skills_fit.models import InputSource, JobMetadata, SkillsFitAnalysis
from agents.skills_fit.runner import (
    _build_scored_posting,
    build_record_metadata,
    infer_run_date,
    load_config,
    resolve_provider_and_model,
)
from agents.skills_fit.utils import (
    SKILLS_FIT_PROMPT_PATH,
    _build_user_message,
    _get_client,
    load_candidate_profile,
)
from utils.batch_api import (
    BATCH_ENDPOINT,
    download_results,
    poll_until_done,
    upload_and_create_batch,
)
from utils.dedup import dedup_jobs
from utils.git_info import get_git_metadata
from utils.openai_pricing import estimate_cost
from utils.run_tracker import RunTracker

log = logging.getLogger(__name__)

DEFAULT_BATCH_DIR = Path("data/batch")


def build_request(
    job: dict[str, Any],
    idx: int,
    *,
    model: str,
    temperature: float,
    prompt_text: str,
    candidate_profile: dict[str, Any],
) -> dict[str, Any]:
    """Build one Batch API request line for a skills-fit scoring job."""
    user_message = _build_user_message(
        job.get("description", ""),
        candidate_profile,
        title=job.get("title") or None,
        location=job.get("location") or None,
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
                    "name": "skills_fit_analysis",
                    "schema": SkillsFitAnalysis.model_json_schema(),
                },
            },
            "messages": [
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": user_message},
            ],
        },
    }


def parse_analysis(item: dict[str, Any]) -> SkillsFitAnalysis | None:
    """Parse one Batch API output line into a ``SkillsFitAnalysis``.

    Returns ``None`` (and warns) for errored items, non-200 responses, missing
    content, or schema-invalid content. The caller records an ``agent_failed``
    output row, matching the serial runner's failure behavior.
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
        return SkillsFitAnalysis.model_validate_json(content)
    except ValidationError as exc:
        log.warning(
            "Batch item %s failed schema validation: %s", item.get("custom_id"), exc
        )
        return None


def _usage_from_item(item: dict[str, Any]) -> dict[str, int]:
    """Pull token counts from a Batch API output line's response body."""
    body = (item.get("response") or {}).get("body") or {}
    usage = body.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "input_tokens": usage.get("prompt_tokens", 0) or 0,
        "cached_input_tokens": details.get("cached_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or 0,
    }


def _write_request_file(requests: list[dict[str, Any]], run_id: str) -> Path:
    path = DEFAULT_BATCH_DIR / f"skills_fit_requests_{run_id}.jsonl"
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
    path = DEFAULT_BATCH_DIR / f"skills_fit_errors_{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(client.files.content(error_file_id).text, encoding="utf-8")
    log.error("Batch error file written to %s", path)


@dataclass
class SkillsFitBatchSubmission:
    """State handle spanning submit → collect for one skills_fit batch run.

    Owns an **entered, not-yet-exited** ``RunTracker``: ``submit`` enters it,
    ``collect`` (success) or ``abort`` (failure) exits it. ``batch_id is None``
    means the local pass served everything and nothing was submitted — collect
    skips straight to writing.
    """

    run: RunTracker
    client: OpenAI | None
    batch_id: str | None
    poll_interval: int
    plan: list[dict[str, Any]]
    enriched_records: list[dict[str, Any]]
    cache: AnalysisCache
    build_metadata: Callable[..., JobMetadata]
    output_path: Path
    cache_path: Path
    run_id: str
    provider_name: str
    model_name: str
    prompt_hash: str
    profile_version: str
    # counters — resolved-so-far at submit time; collect mutates the last two
    cache_hits: int
    cache_misses: int
    resumed_existing: int
    skipped_missing_description: int
    submitted: int
    deduped: int
    scored_successfully: int
    failed_agent: int
    # tallies fixed at submit time (for the summary dict + tracker extras)
    remote_loaded: int
    local_loaded: int
    merged_before_dedupe: int
    merged_after_dedupe: int
    _telemetry_finalized: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def abort(self, exc: BaseException) -> dict[str, Any]:
        """Close the tracker with a failure after recording telemetry, so a
        failed/expired batch (or a collect that raised) still writes a complete,
        failure-marked run record instead of leaking an open tracker."""
        self._close_tracker(type(exc), exc, exc.__traceback__)
        return self._summary()

    def _close_tracker(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any | None,
    ) -> None:
        if self._closed:
            raise RuntimeError(f"RunTracker for {self.run_id} is already closed")
        self._finalize_telemetry()
        self.run.__exit__(exc_type, exc, tb)
        self._closed = True

    def _finalize_telemetry(self) -> None:
        """Body of the old ``finally`` block — records outputs/cache/cost on the
        tracker. Safe to call exactly once per submission (from collect success
        or from abort)."""
        if self._telemetry_finalized:
            return
        run = self.run
        run.add_output(
            label="scored_rows",
            path=str(self.output_path),
            record_count=len(self.enriched_records),
        )
        if self.scored_successfully:
            run.add_output(
                label="scored_successfully", record_count=self.scored_successfully
            )
        if self.resumed_existing:
            run.add_output(label="reused_existing", record_count=self.resumed_existing)
        if self.skipped_missing_description:
            run.add_output(
                label="missing_description",
                record_count=self.skipped_missing_description,
            )
        if self.failed_agent:
            run.add_output(label="agent_failed", record_count=self.failed_agent)

        run.set_cache(
            path=str(self.cache_path), hits=self.cache_hits, misses=self.cache_misses
        )
        run.update_llm_stats(calls_made=self.submitted, calls_failed=self.failed_agent)
        run.record.extras.update(
            {
                "merged_after_dedupe": self.merged_after_dedupe,
                "deduped": self.deduped,
                "resumed_existing": self.resumed_existing,
                "scored_successfully": self.scored_successfully,
                "skipped_missing_description": self.skipped_missing_description,
                "failed_agent": self.failed_agent,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "submitted": self.submitted,
            }
        )
        if self.resumed_existing:
            run.add_notable(f"Reused existing scored rows: {self.resumed_existing}")
        if self.skipped_missing_description:
            run.add_notable(
                f"Skipped missing description: {self.skipped_missing_description}"
            )
        if self.failed_agent:
            run.add_notable(f"Agent failures: {self.failed_agent}")
        breakdown = estimate_cost(self.model_name, batch=True, **run.token_totals)
        if breakdown is not None:
            total = breakdown.pop("total")
            run.set_cost(estimated_total=total, breakdown=breakdown)
        else:
            run.add_notable(
                f"No pricing entry for model '{self.model_name}' — actual cost will need backfill"
            )
        self._telemetry_finalized = True

    def _summary(self) -> dict[str, Any]:
        """The dict + logging previously after the ``with`` block."""
        if self.resumed_existing:
            log.info("Reused existing scored rows: %d", self.resumed_existing)
        log.info("Cache hits: %d", self.cache_hits)
        log.info("Cache misses: %d", self.cache_misses)
        log.info("Submitted to batch: %d", self.submitted)
        log.info("Scored successfully: %d", self.scored_successfully)
        log.info("Skipped missing description: %d", self.skipped_missing_description)
        log.info("Failed agent: %d", self.failed_agent)
        log.info("Wrote %d records to %s", len(self.enriched_records), self.output_path)
        return {
            "run_id": self.run_id,
            "remote_loaded": self.remote_loaded,
            "local_loaded": self.local_loaded,
            "merged_before_dedupe": self.merged_before_dedupe,
            "merged_after_dedupe": self.merged_after_dedupe,
            "deduped": self.deduped,
            "scored_successfully": self.scored_successfully,
            "skipped_missing_description": self.skipped_missing_description,
            "failed_agent": self.failed_agent,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "submitted": self.submitted,
            "output_path": str(self.output_path),
        }


def submit_skills_fit_batch(
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
    poll_interval: int = 60,
) -> SkillsFitBatchSubmission:
    """Run the local pass and submit cache misses without polling."""
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
    submitted = 0
    remote_records: list[dict[str, Any]] = []
    local_records: list[dict[str, Any]] = []
    merged_records: list[dict[str, Any]] = []
    deduped_records: list[dict[str, Any]] = []
    enriched_records: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    client: OpenAI | None = None
    batch_id: str | None = None

    run = RunTracker(
        component="skills_fit",
        run_type=run_type,
        run_date=tracker_run_date,
        run_id=run_id,
        parent_run_id=parent_run_id,
    )
    run.__enter__()
    try:
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
                "batch": True,
                "poll_interval": poll_interval,
            }
        )

        config = apply_llm_overrides(
            load_config(config_file),
            provider=provider,
            model=model,
            temperature=temperature,
        )
        llm_config = config.get("llm") or {}
        config_hash = hash_file(config_file)

        provider_name, model_name = resolve_provider_and_model(llm_config)
        if provider_name != "openai":
            raise ValueError(
                f"--batch requires provider=openai; the config resolves to "
                f"provider={provider_name!r}. The OpenAI Batch API has no ollama "
                f"equivalent — drop --batch to run the serial path."
            )
        resolved_temperature = llm_config.get("temperature")
        request_temperature = (
            resolved_temperature if resolved_temperature is not None else 0.1
        )

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
        prompt_text = prompt_file.read_text()

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
            api_key_env=llm_config.get("api_key_env", "OPENAI_API_KEY"),
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

        for job in deduped_records:
            existing = existing_output_records.get(str(job["dedup_hash"]))
            if existing is not None and is_processed_output_record(existing):
                enriched_records.append(existing)
                resumed_existing += 1
                continue

            input_source: InputSource = job["__input_source"]
            input_path = job["__input_path"]
            title = job.get("title") or None
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
                enriched_records.append(
                    _build_scored_posting(job, ai_fit=None, metadata=metadata)
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
                metadata = _build_metadata(
                    input_source=input_source,
                    input_path=input_path,
                )
                enriched_records.append(
                    _build_scored_posting(job, ai_fit=analysis, metadata=metadata)
                )
                scored_successfully += 1
                continue

            cache_misses += 1
            idx = len(requests)
            requests.append(
                build_request(
                    job,
                    idx,
                    model=model_name,
                    temperature=request_temperature,
                    prompt_text=prompt_text,
                    candidate_profile=profile,
                )
            )
            plan.append(
                {
                    "job": job,
                    "input_source": input_source,
                    "input_path": input_path,
                    "custom_id": f"job-{idx}",
                }
            )

        submitted = len(requests)

        if requests:
            request_file = _write_request_file(requests, run.run_id)
            client, _ = _get_client(llm_config)
            batch_id, _input_file_id = upload_and_create_batch(client, request_file)
            log.info(
                "Submitted %d requests as batch %s (will poll later)",
                submitted,
                batch_id,
            )
        else:
            log.info("All scorable jobs served locally — no batch submitted")
    except BaseException as exc:
        run.__exit__(type(exc), exc, exc.__traceback__)
        raise

    return SkillsFitBatchSubmission(
        run=run,
        client=client,
        batch_id=batch_id,
        poll_interval=poll_interval,
        plan=plan,
        enriched_records=enriched_records,
        cache=cache,
        build_metadata=_build_metadata,
        output_path=resolved_paths.output,
        cache_path=cache_path,
        run_id=run_id,
        provider_name=provider_name,
        model_name=model_name,
        prompt_hash=prompt_hash,
        profile_version=profile_version,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        resumed_existing=resumed_existing,
        skipped_missing_description=skipped_missing_description,
        submitted=submitted,
        deduped=deduped,
        scored_successfully=scored_successfully,
        failed_agent=failed_agent,
        remote_loaded=len(remote_records),
        local_loaded=len(local_records),
        merged_before_dedupe=len(merged_records),
        merged_after_dedupe=len(deduped_records),
    )


def collect_skills_fit_batch(
    submission: SkillsFitBatchSubmission, batch: Batch | None
) -> dict[str, Any]:
    """Resolve a submitted batch and write output; close the tracker on success.

    On any failure path this raises with the tracker still OPEN — the caller must
    call ``submission.abort(exc)``. ``batch`` is the terminal Batch the caller
    polled; it is ignored when ``submission.batch_id is None`` (nothing submitted).
    """
    run = submission.run
    results: dict[str, dict[str, Any]] = {}
    if submission.batch_id is not None:
        if batch is None:
            raise RuntimeError(
                f"collect requires the terminal batch for {submission.batch_id}, got None"
            )
        if submission.client is None:
            raise RuntimeError(f"submission {submission.run_id} has no OpenAI client")
        if batch.status != "completed":
            _log_batch_failure(submission.client, batch, submission.run_id)
            raise RuntimeError(f"Batch {batch.id} ended with status={batch.status}")
        results = _index_results(download_results(submission.client, batch))

    for entry in submission.plan:
        job = entry["job"]
        title = job.get("title") or None
        item = results.get(entry["custom_id"])
        analysis = None
        if item is None:
            log.warning(
                "No batch result for %s (%s) — recording agent_failed",
                entry["custom_id"],
                title or job["dedup_hash"],
            )
        else:
            run.add_token_usage(_usage_from_item(item))
            analysis = parse_analysis(item)

        if analysis is None:
            log.warning("Agent failed on %s", title or job["dedup_hash"])
            submission.failed_agent += 1
            run.increment_failures()
            metadata = submission.build_metadata(
                input_source=entry["input_source"],
                input_path=entry["input_path"],
                failure_reason="agent_failed",
            )
            submission.enriched_records.append(
                _build_scored_posting(job, ai_fit=None, metadata=metadata)
            )
            continue

        submission.cache.put(
            dedup_hash=str(job["dedup_hash"]),
            prompt_hash=submission.prompt_hash,
            provider=submission.provider_name,
            model=submission.model_name,
            profile_version=submission.profile_version,
            analysis=analysis,
        )
        metadata = submission.build_metadata(
            input_source=entry["input_source"], input_path=entry["input_path"]
        )
        submission.enriched_records.append(
            _build_scored_posting(job, ai_fit=analysis, metadata=metadata)
        )
        submission.scored_successfully += 1

    write_output(submission.enriched_records, submission.output_path)
    submission._close_tracker(None, None, None)
    return submission._summary()


def run_skills_fit_batch(**kwargs) -> dict[str, Any]:
    """Submit → poll → collect, composed. Preserves #462's single-user semantics
    and the standalone ``--batch`` CLI byte-for-byte."""
    poll_interval = kwargs.get("poll_interval", 60)
    submission = submit_skills_fit_batch(**kwargs)
    try:
        batch = None
        if submission.batch_id is not None:
            if submission.client is None:
                raise RuntimeError(
                    f"submission {submission.run_id} has no OpenAI client"
                )
            batch = poll_until_done(
                submission.client, submission.batch_id, poll_interval
            )
        return collect_skills_fit_batch(submission, batch)
    except Exception as exc:
        submission.abort(exc)
        raise
