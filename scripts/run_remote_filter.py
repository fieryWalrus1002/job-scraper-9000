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

from agents.remote_filter.utils import analyze_remote, load_raw_jobs, passes_remote_filter

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

INPUT_DIR = Path("data/raw")
PASS_PATH = Path("data/filtered/remote_filter_pass.jsonl")
TRASH_PATH = Path("data/trash/remote_filter_trash.jsonl")
CONFIG_PATH = Path("config/agent/remote_agent.yml")
USER_LOCATION = os.environ.get("USER_LOCATION", "USA")


def main() -> None:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))

    llm_config = config.get("llm")
    jobs = load_raw_jobs(INPUT_DIR)
    if not jobs:
        log.error("No jobs found in %s", INPUT_DIR)
        sys.exit(1)

    log.info("Running remote-filter on %d jobs...", len(jobs))

    PASS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRASH_PATH.parent.mkdir(parents=True, exist_ok=True)

    passed = failed = skipped = 0

    with open(PASS_PATH, "w") as pass_f, open(TRASH_PATH, "w") as trash_f:
        for job in jobs:
            description = job.get("description", "")
            title = job.get("title", "")
            company = job.get("company", "")

            if not description:
                log.warning("Skipping %s @ %s — no description", title, company)
                skipped += 1
                continue

            analysis = analyze_remote(description, llm_config=llm_config)
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
