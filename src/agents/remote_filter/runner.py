import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from agents.remote_filter.models import SCHEMA_VERSION
from agents.remote_filter.utils import (
    REMOTE_FILTER_PROMPT_PATH,
    analyze_remote,
    load_raw_jobs,
    passes_remote_filter,
)
from utils.git_info import get_git_metadata, get_prompt_hash

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


def run_remote_filter(
    *,
    input_path: str | Path = DEFAULT_INPUT_DIR,
    pass_path: str | Path = DEFAULT_PASS_PATH,
    trash_path: str | Path = DEFAULT_TRASH_PATH,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    user_location: str = "USA",
    user_timezone: str | None = None,
) -> dict[str, int]:
    """Run the remote-filter agent over routed candidate jobs and split pass/trash JSONL outputs."""
    input_path = Path(input_path)
    pass_path = Path(pass_path)
    trash_path = Path(trash_path)
    config = load_remote_filter_config(config_path)
    llm_config = config.get("llm")

    jobs = load_raw_jobs(input_path)
    if not jobs:
        raise FileNotFoundError(f"No jobs found in {input_path}")

    log.info("Running remote-filter on %d jobs...", len(jobs))

    filter_meta = build_filter_metadata()
    log.info(
        "Filter metadata: schema=%s prompt=%s commit=%s dirty=%s",
        SCHEMA_VERSION,
        filter_meta["prompt_hash"],
        filter_meta["commit"][:12],
        filter_meta["dirty"],
    )

    pass_path.parent.mkdir(parents=True, exist_ok=True)
    trash_path.parent.mkdir(parents=True, exist_ok=True)

    passed = failed = skipped = 0

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
            analysis = analyze_remote(
                description,
                title=title,
                location=location,
                search_context=search_context or None,
                llm_config=llm_config,
            )
            if analysis is None:
                log.warning("Agent failed on %s @ %s — skipping", title, company)
                skipped += 1
                continue

            ok, reason = passes_remote_filter(analysis, config, user_location)

            enriched = {
                **job,
                "_remote_analysis": analysis.model_dump(),
                "_filter_result": "pass" if ok else "trash",
                "_filter_reason": reason,
                "_filter_metadata": filter_meta,
            }

            if ok:
                pass_f.write(json.dumps(enriched) + "\n")
                passed += 1
                log.info(
                    "PASS  %s @ %s (%s)", title, company, analysis.remote_classification
                )
            else:
                trash_f.write(json.dumps(enriched) + "\n")
                failed += 1
                log.info("TRASH %s @ %s — %s", title, company, reason)

    log.info("Done — %d pass | %d trash | %d skipped", passed, failed, skipped)
    return {"pass": passed, "trash": failed, "skipped": skipped, "total": len(jobs)}
