#!/usr/bin/env python3
"""Score live jobs against the candidate profile and write a ranked shortlist."""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agent_eval.provenance import generate_run_id, hash_file
from agents.skills_fit.cache import DEFAULT_CACHE_PATH, AnalysisCache
from agents.skills_fit.models import SCHEMA_VERSION
from agents.skills_fit.utils import (
    SKILLS_FIT_PROMPT_PATH,
    analyze_skills_fit,
    load_candidate_profile,
)
from utils.dedup import dedup_jobs
from utils.git_info import get_git_metadata

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/agent/skills_fit.yml")


@dataclass(frozen=True)
class ResolvedPaths:
    remote_input: Path
    local_input: Path
    output: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", help="Partition date in YYYY-MM-DD form")
    parser.add_argument("--remote-input", help="Override remote input JSONL path")
    parser.add_argument("--local-input", help="Override local input JSONL path")
    parser.add_argument("--output", help="Override output JSONL path")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Agent config YAML (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--provider", help="Override llm.provider in-memory")
    parser.add_argument("--model", help="Override llm.model in-memory")
    parser.add_argument(
        "--temperature", type=float, help="Override llm.temperature in-memory"
    )
    parser.add_argument("--limit", type=int, help="Limit deduped records for testing")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    return args


def resolve_paths(
    *,
    run_date: str | None,
    remote_input: str | Path | None,
    local_input: str | Path | None,
    output: str | Path | None,
) -> ResolvedPaths:
    if remote_input is not None:
        resolved_remote = Path(remote_input)
    elif run_date:
        resolved_remote = Path("data/filtered") / run_date / "remote_filter_pass.jsonl"
    else:
        raise ValueError(
            "--run-date is required unless --remote-input, --local-input, and --output are all provided"
        )

    if local_input is not None:
        resolved_local = Path(local_input)
    elif run_date:
        resolved_local = Path("data/local") / run_date / "local_jobs.jsonl"
    else:
        raise ValueError(
            "--run-date is required unless --remote-input, --local-input, and --output are all provided"
        )

    if output is not None:
        resolved_output = Path(output)
    elif run_date:
        resolved_output = Path("data/scored") / run_date / "skills_fit_scored.jsonl"
    else:
        raise ValueError(
            "--run-date is required unless --remote-input, --local-input, and --output are all provided"
        )

    return ResolvedPaths(
        remote_input=resolved_remote,
        local_input=resolved_local,
        output=resolved_output,
    )


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(os.path.expandvars(f.read())) or {}


def apply_llm_overrides(
    config: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    resolved = json.loads(json.dumps(config))
    llm = resolved.setdefault("llm", {})
    if provider:
        llm["provider"] = provider
    if model:
        llm["model"] = model
    if temperature is not None:
        llm["temperature"] = temperature
    return resolved


def resolve_provider_and_model(llm_config: dict[str, Any] | None) -> tuple[str, str]:
    cfg = llm_config or {}
    provider = cfg.get("provider", os.environ.get("LLM_PROVIDER", "openai")).lower()
    default_model = "qwen2.5:14b" if provider == "ollama" else "gpt-4o-mini"
    model = cfg.get("model", os.environ.get("LLM_MODEL", default_model))
    return provider, model


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def is_processed_output_record(record: dict[str, Any]) -> bool:
    metadata = record.get("_skills_fit_metadata")
    if not isinstance(metadata, dict):
        return False
    if record.get("_skills_fit_score") is not None:
        return True
    return metadata.get("failure_reason") is not None


def load_existing_output_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records

    with path.open(encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(
                    "Skipping malformed existing output line %d in %s: %s",
                    line_number,
                    path,
                    exc,
                )
                continue
            if not isinstance(record, dict):
                log.warning(
                    "Skipping non-object existing output line %d in %s",
                    line_number,
                    path,
                )
                continue
            dedup_hash = record.get("dedup_hash")
            if not dedup_hash:
                log.warning(
                    "Skipping existing output line %d in %s with missing dedup_hash",
                    line_number,
                    path,
                )
                continue
            records[str(dedup_hash)] = record
    return records


def load_tagged_inputs(
    *, remote_input: Path, local_input: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not remote_input.exists():
        raise FileNotFoundError(f"Remote input file not found: {remote_input}")

    remote_records = [
        {
            **record,
            "__input_source": "remote_filter_pass",
            "__input_path": str(remote_input),
        }
        for record in read_jsonl(remote_input)
    ]

    local_records: list[dict[str, Any]] = []
    if local_input.exists():
        local_records = [
            {
                **record,
                "__input_source": "local_candidate",
                "__input_path": str(local_input),
            }
            for record in read_jsonl(local_input)
        ]
    else:
        log.info("Local input not found; continuing without it: %s", local_input)

    return remote_records, local_records


def validate_dedup_hashes(records: list[dict[str, Any]]) -> None:
    missing_examples: list[str] = []
    missing_count = 0
    for i, record in enumerate(records):
        if record.get("dedup_hash"):
            continue
        missing_count += 1
        if len(missing_examples) < 5:
            label = record.get("title") or record.get("source_url") or f"index={i}"
            missing_examples.append(str(label))
    if missing_count:
        examples = ", ".join(missing_examples)
        raise ValueError(
            "Input contract failure: every record must include dedup_hash "
            f"({missing_count} missing; examples: {examples})"
        )


def clean_job_record(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"__input_source", "__input_path"}
    }


def build_record_metadata(
    *,
    run_id: str,
    scored_at: str,
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
    input_source: str,
    input_path: str,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    metadata = {
        "run_id": run_id,
        "scored_at": scored_at,
        "config_file": str(config_file),
        "prompt_file": str(prompt_file),
        "prompt_hash": prompt_hash,
        "profile_file": str(profile_file),
        "profile_hash": profile_hash,
        "profile_version": profile_version,
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "skills_fit_schema_version": SCHEMA_VERSION,
        "commit": git_metadata["commit"],
        "dirty": git_metadata["dirty"],
        "input_source": input_source,
        "input_path": input_path,
    }
    if failure_reason is not None:
        metadata["failure_reason"] = failure_reason
    return metadata


def rank_key(record: dict[str, Any]) -> tuple[bool, int, str]:
    score = record.get("_skills_fit_score")
    return (score is None, -(score or 0), record["dedup_hash"])


def write_output(records: list[dict[str, Any]], output_path: Path) -> None:
    records.sort(key=rank_key)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def run_skills_fit(
    *,
    run_date: str | None = None,
    remote_input: str | Path | None = None,
    local_input: str | Path | None = None,
    output: str | Path | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    resolved_paths = resolve_paths(
        run_date=run_date,
        remote_input=remote_input,
        local_input=local_input,
        output=output,
    )

    config_file = Path(config_path)
    config = apply_llm_overrides(
        load_config(config_file),
        provider=provider,
        model=model,
        temperature=temperature,
    )
    llm_config = config.get("llm") or {}

    profile_file = Path(
        config.get("profile_file", "config/profile/candidate_profile.yml")
    )
    if not profile_file.exists():
        raise FileNotFoundError(f"Profile file not found: {profile_file}")
    profile = load_candidate_profile(profile_file)
    profile_hash = hash_file(profile_file)
    profile_version = profile.get("profile_version", "unknown")

    prompt_file = Path(SKILLS_FIT_PROMPT_PATH)
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    prompt_hash = hash_file(prompt_file)

    provider_name, model_name = resolve_provider_and_model(llm_config)
    resolved_temperature = llm_config.get("temperature")
    cache = AnalysisCache(DEFAULT_CACHE_PATH)
    cache_hits = 0
    cache_misses = 0
    git_metadata = get_git_metadata()
    run_id = generate_run_id("skillsfit")

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

    log.info(
        "Loaded %d remote + %d local = %d merged records (%d after dedupe)",
        len(remote_records),
        len(local_records),
        len(merged_records),
        len(deduped_records),
    )

    existing_output_records = load_existing_output_records(resolved_paths.output)
    resumed_existing = 0
    if existing_output_records:
        log.info(
            "Loaded %d existing scored rows from %s",
            len(existing_output_records),
            resolved_paths.output,
        )

    scored_successfully = 0
    skipped_missing_description = 0
    failed_agent = 0
    enriched_records: list[dict[str, Any]] = []

    try:
        for job in deduped_records:
            existing = existing_output_records.get(str(job["dedup_hash"]))
            if existing is not None and is_processed_output_record(existing):
                enriched_records.append(existing)
                resumed_existing += 1
                continue

            input_source = job["__input_source"]
            input_path = job["__input_path"]
            title = job.get("title") or None
            location = job.get("location") or None
            description = job.get("description") or ""
            scored_at = git_metadata["timestamp"]

            if not description:
                log.warning(
                    "Skipping %s — missing description", title or job["dedup_hash"]
                )
                skipped_missing_description += 1
                metadata = build_record_metadata(
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
                    input_source=input_source,
                    input_path=input_path,
                    failure_reason="missing_description",
                )
                enriched_records.append(
                    {
                        **clean_job_record(job),
                        "_skills_fit_score": None,
                        "_skills_fit_rationale": None,
                        "_skills_fit_hard_concerns": [],
                        "_skills_fit_top_matches": [],
                        "_skills_fit_analysis": None,
                        "_skills_fit_gaps": [],
                        "_skills_fit_confidence": None,
                        "_skills_fit_input_source": input_source,
                        "_skills_fit_metadata": metadata,
                    }
                )
                continue

            analysis = cache.get(
                dedup_hash=str(job["dedup_hash"]),
                prompt_hash=prompt_hash,
                provider=provider_name,
                model=model_name,
                profile_hash=profile_hash,
            )
            if analysis is not None:
                cache_hits += 1
            else:
                cache_misses += 1
                analysis = analyze_skills_fit(
                    description,
                    candidate_profile=profile,
                    title=title,
                    location=location,
                    llm_config=llm_config,
                    prompt_path=prompt_file,
                )
                if analysis is not None:
                    cache.put(
                        dedup_hash=str(job["dedup_hash"]),
                        prompt_hash=prompt_hash,
                        provider=provider_name,
                        model=model_name,
                        profile_hash=profile_hash,
                        analysis=analysis,
                    )
            if analysis is None:
                log.warning("Agent failed on %s", title or job["dedup_hash"])
                failed_agent += 1
                metadata = build_record_metadata(
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
                    input_source=input_source,
                    input_path=input_path,
                    failure_reason="agent_failed",
                )
                enriched_records.append(
                    {
                        **clean_job_record(job),
                        "_skills_fit_score": None,
                        "_skills_fit_rationale": None,
                        "_skills_fit_hard_concerns": [],
                        "_skills_fit_top_matches": [],
                        "_skills_fit_analysis": None,
                        "_skills_fit_gaps": [],
                        "_skills_fit_confidence": None,
                        "_skills_fit_input_source": input_source,
                        "_skills_fit_metadata": metadata,
                    }
                )
                continue

            metadata = build_record_metadata(
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
                input_source=input_source,
                input_path=input_path,
            )
            enriched_records.append(
                {
                    **clean_job_record(job),
                    "_skills_fit_score": analysis.fit_score,
                    "_skills_fit_rationale": analysis.score_rationale,
                    "_skills_fit_hard_concerns": analysis.hard_concerns,
                    "_skills_fit_top_matches": analysis.top_matches,
                    "_skills_fit_analysis": analysis.model_dump(),
                    "_skills_fit_gaps": analysis.gaps,
                    "_skills_fit_confidence": analysis.confidence,
                    "_skills_fit_input_source": input_source,
                    "_skills_fit_metadata": metadata,
                }
            )
            scored_successfully += 1
    except KeyboardInterrupt:
        if enriched_records:
            write_output(enriched_records, resolved_paths.output)
            log.warning(
                "Interrupted — wrote %d partial records to %s",
                len(enriched_records),
                resolved_paths.output,
            )
        else:
            log.warning("Interrupted before any records were written")
        raise

    write_output(enriched_records, resolved_paths.output)

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
    args = parse_args(argv)
    try:
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


if __name__ == "__main__":
    raise SystemExit(main())
