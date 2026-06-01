import argparse
import logging
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any
import json


from jobs_cli._common import _parse_positive_int, _parse_run_date

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/agent/skills_fit.yml")


@dataclass(frozen=True)
class ResolvedPaths:
    remote_input: Path
    local_input: Path
    output: Path


def _cmd_skills_fit(args) -> None:
    from agents.skills_fit.runner import run_skills_fit

    try:
        run_skills_fit(
            run_date=args.run_date,
            config_path=args.config,
            limit=args.limit,
        )
    except (FileNotFoundError, ValueError) as exc:
        log.error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


def _add_skills_fit(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "skills-fit",
        help="Score remote-filter PASS jobs against the candidate profile",
    )
    p.add_argument(
        "--run-date",
        default=None,
        dest="run_date",
        metavar="YYYY-MM-DD",
        type=_parse_run_date,
        help="Score this day's partition using the configured input/output conventions",
    )
    p.add_argument(
        "--config",
        default="config/agent/skills_fit.yml",
        help="Skills-fit config YAML",
    )
    p.add_argument(
        "--limit",
        type=_parse_positive_int,
        help="Limit deduped records for testing",
    )
    p.set_defaults(func=_cmd_skills_fit)


def register(sub: argparse._SubParsersAction) -> None:
    _add_skills_fit(sub)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score live jobs against the candidate profile and write a ranked shortlist."
    )
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


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


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
