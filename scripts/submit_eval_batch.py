#!/usr/bin/env python3
"""Submit a remote-filter eval run to the OpenAI Batch API.

This is the submission half of SC-7. It builds a Batch API request file from the
human-verified gold dataset, submits it to OpenAI, and writes a sidecar JSON file
that poll_eval_batch.py later uses to download results and write a normal eval
run record.

Usage:
    uv run python scripts/submit_eval_batch.py
    uv run python scripts/submit_eval_batch.py --model gpt-4o --temperature 0.0 --run-id gpt4o_batch
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agent_eval.provenance import generate_run_id, hash_file, hash_string
from agents.remote_filter.models import RemoteAnalysis, SCHEMA_VERSION
from agents.remote_filter.utils import REMOTE_FILTER_PROMPT_PATH, _build_user_message
from scripts.run_remote_filter_eval import CONFIG_PATH, GOLD_FILE, load_gold

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DEFAULT_BATCH_DIR = "data/eval/batch"
DEFAULT_SIDECAR_DIR = "data/eval"
BATCH_ENDPOINT = "/v1/chat/completions"
COMPLETION_WINDOW = "24h"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--gold", default=GOLD_FILE, help=f"Gold JSONL (default: {GOLD_FILE})"
    )
    p.add_argument(
        "--config",
        default=CONFIG_PATH,
        help=f"Agent config YAML (default: {CONFIG_PATH})",
    )
    p.add_argument("--model", help="Override llm.model in-memory")
    p.add_argument(
        "--temperature", type=float, help="Override llm.temperature in-memory"
    )
    p.add_argument("--provider", help="Override llm.provider in-memory")
    p.add_argument("--run-id", dest="run_id", help="Human-readable run-id prefix")
    p.add_argument(
        "--batch-dir",
        default=DEFAULT_BATCH_DIR,
        help=f"Directory for request JSONL files (default: {DEFAULT_BATCH_DIR})",
    )
    p.add_argument(
        "--sidecar-dir",
        default=DEFAULT_SIDECAR_DIR,
        help=f"Directory for eval_batch_<run_id>.json sidecars (default: {DEFAULT_SIDECAR_DIR})",
    )
    return p.parse_args()


def load_config(path: str) -> dict[str, Any]:
    with open(path) as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))
    return config or {}


def apply_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    resolved = dict(config)
    llm = dict(resolved.get("llm") or {})
    if args.model:
        llm["model"] = args.model
    if args.temperature is not None:
        llm["temperature"] = args.temperature
    if args.provider:
        llm["provider"] = args.provider
    resolved["llm"] = llm
    return resolved


def _provider(config: dict[str, Any]) -> str:
    return str(config.get("llm", {}).get("provider", "openai")).lower()


def _model(config: dict[str, Any]) -> str:
    return str(
        config.get("llm", {}).get("model", os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    )


def _temperature(config: dict[str, Any]) -> float:
    return float(config.get("llm", {}).get("temperature", 0.1))


def config_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    """Return the non-secret config subset needed to reproduce scoring."""
    return {
        "llm": {
            "provider": _provider(config),
            "model": _model(config),
            "temperature": _temperature(config),
        },
        "policy_thresholds": config.get("policy_thresholds"),
    }


def _search_context(
    job: dict[str, Any], user_timezone: str | None
) -> dict[str, Any] | None:
    context = {
        **(job.get("search_params") or {}),
        **({"user_timezone": user_timezone} if user_timezone else {}),
    }
    return context or None


def build_request(
    job: dict[str, Any], idx: int, config: dict[str, Any], prompt_text: str
) -> dict[str, Any]:
    user_timezone = os.environ.get("USER_TIMEZONE")
    user_message = _build_user_message(
        job.get("description", ""),
        search_context=_search_context(job, user_timezone),
        location=job.get("location") or None,
        title=job.get("title") or None,
    )
    return {
        "custom_id": f"job-{idx}",
        "method": "POST",
        "url": BATCH_ENDPOINT,
        "body": {
            "model": _model(config),
            "temperature": _temperature(config),
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


def write_requests(
    records: list[dict[str, Any]], config: dict[str, Any], request_file: Path
) -> None:
    prompt_text = REMOTE_FILTER_PROMPT_PATH.read_text()
    request_file.parent.mkdir(parents=True, exist_ok=True)
    with request_file.open("w", encoding="utf-8") as f:
        for idx, job in enumerate(records):
            f.write(json.dumps(build_request(job, idx, config, prompt_text)) + "\n")
    log.info("Wrote %d batch requests → %s", len(records), request_file)


def submit_batch(client: OpenAI, request_file: Path) -> tuple[str, str]:
    log.info("Uploading %s", request_file)
    with request_file.open("rb") as f:
        file_obj = client.files.create(file=f, purpose="batch")
    log.info("Uploaded request file: %s", file_obj.id)

    batch = client.batches.create(
        input_file_id=file_obj.id,
        endpoint=BATCH_ENDPOINT,
        completion_window=COMPLETION_WINDOW,
    )
    log.info("Created batch: %s status=%s", batch.id, batch.status)
    return batch.id, file_obj.id


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def build_sidecar(
    *,
    batch_id: str,
    input_file_id: str,
    run_id: str,
    gold_file: Path,
    config: dict[str, Any],
    config_file: str,
    request_file: Path,
) -> dict[str, Any]:
    prompt_text = REMOTE_FILTER_PROMPT_PATH.read_text()
    return {
        "schema_version": "1.0.0",
        "agent_schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "input_file_id": input_file_id,
        "run_id": run_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "gold_file": str(gold_file),
        "gold_hash": hash_file(gold_file),
        "config": config_snapshot(config),
        "config_file": str(config_file),
        "prompt_hash": hash_string(prompt_text),
        "prompt_file": _display_path(REMOTE_FILTER_PROMPT_PATH),
        "request_file": str(request_file),
        "endpoint": BATCH_ENDPOINT,
        "completion_window": COMPLETION_WINDOW,
        "user_location": os.environ.get("USER_LOCATION", "USA"),
        "user_timezone": os.environ.get("USER_TIMEZONE"),
    }


def main() -> None:
    args = parse_args()
    gold_file = Path(args.gold)
    if not gold_file.exists():
        log.error("Gold file not found: %s", gold_file)
        sys.exit(1)

    config = apply_overrides(load_config(args.config), args)
    if _provider(config) == "ollama":
        log.error("OpenAI Batch API only supports provider=openai; got provider=ollama")
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.error("OPENAI_API_KEY not set")
        sys.exit(1)

    records = load_gold(str(gold_file))
    if not records:
        log.error("No gold records found in %s", gold_file)
        sys.exit(1)

    run_id = generate_run_id(args.run_id)
    request_file = Path(args.batch_dir) / f"eval_requests_{run_id}.jsonl"
    sidecar_file = Path(args.sidecar_dir) / f"eval_batch_{run_id}.json"

    write_requests(records, config, request_file)

    client = OpenAI(api_key=api_key)
    batch_id, input_file_id = submit_batch(client, request_file)

    sidecar = build_sidecar(
        batch_id=batch_id,
        input_file_id=input_file_id,
        run_id=run_id,
        gold_file=gold_file,
        config=config,
        config_file=args.config,
        request_file=request_file,
    )
    sidecar_file.parent.mkdir(parents=True, exist_ok=True)
    sidecar_file.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    log.info("Sidecar written → %s", sidecar_file)

    print(f"\nBatch ID: {batch_id}")
    print(f"Sidecar : {sidecar_file}")
    print(
        f"Poll    : uv run python scripts/poll_eval_batch.py --sidecar {sidecar_file}"
    )


if __name__ == "__main__":
    main()
