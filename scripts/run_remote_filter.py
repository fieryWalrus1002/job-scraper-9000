#!/usr/bin/env python3
"""Local test runner for the remote_filter agent."""
import json
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.remote_filter.models import SCHEMA_VERSION
from agents.remote_filter.utils import analyze_remote, load_raw_jobs, passes_remote_filter
from utils.git_info import get_git_metadata, get_prompt_hash

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

INPUT_DIR = Path("data/raw")
PASS_PATH = Path("data/filtered/remote_filter_pass.jsonl")
TRASH_PATH = Path("data/trash/remote_filter_trash.jsonl")
CONFIG_PATH = Path("config/agent/remote_agent.yml")
USER_LOCATION = os.environ.get("USER_LOCATION", "USA")
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", None)

_PROMPT_FILE = Path(__file__).parents[1] / "prompts" / "remote_agent" / "system_prompt_v1.txt"


def main() -> None:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))

    llm_config = config.get("llm")
    jobs = load_raw_jobs(INPUT_DIR)
    if not jobs:
        log.error("No jobs found in %s", INPUT_DIR)
        sys.exit(1)

    log.info("Running remote-filter on %d jobs...", len(jobs))

    git_meta = get_git_metadata()
    prompt_hash = get_prompt_hash(_PROMPT_FILE) if _PROMPT_FILE.exists() else "unknown"
    filter_meta = {
        "schema_version": SCHEMA_VERSION,
        "prompt_hash": prompt_hash,
        "prompt_file": _PROMPT_FILE.name,
        "commit": git_meta["commit"],
        "dirty": git_meta["dirty"],
        "filtered_at": git_meta["timestamp"],
    }
    log.info("Filter metadata: schema=%s prompt=%s commit=%s dirty=%s", SCHEMA_VERSION, prompt_hash, git_meta["commit"][:12], git_meta["dirty"])

    PASS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRASH_PATH.parent.mkdir(parents=True, exist_ok=True)

    passed = failed = skipped = 0

    with open(PASS_PATH, "w") as pass_f, open(TRASH_PATH, "w") as trash_f:
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
                **({"user_timezone": USER_TIMEZONE} if USER_TIMEZONE else {}),
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

            ok, reason = passes_remote_filter(analysis, config, USER_LOCATION)

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
                log.info("PASS  %s @ %s (%s)", title, company, analysis.remote_classification)
            else:
                trash_f.write(json.dumps(enriched) + "\n")
                failed += 1
                log.info("TRASH %s @ %s — %s", title, company, reason)

    log.info("Done — %d pass | %d trash | %d skipped", passed, failed, skipped)


if __name__ == "__main__":
    main()
