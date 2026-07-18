import argparse
import logging
import os
import sys

from jobs_cli._common import _parse_run_date

log = logging.getLogger(__name__)


def _cmd_remote_filter(args) -> None:
    from agents.remote_filter.runner import run_remote_filter

    run_date = getattr(args, "run_date", None)
    if run_date:
        input_path = args.input or f"data/prefiltered/{run_date}"
        classified_path = (
            args.classified_output
            or f"data/filtered/{run_date}/remote_filter_classified.jsonl"
        )
    else:
        input_path = args.input or "data/prefiltered/remote_filter_input.jsonl"
        classified_path = (
            args.classified_output or "data/filtered/remote_filter_classified.jsonl"
        )

    from agents.remote_filter.cache import DEFAULT_CACHE_PATH

    cache_path = None if args.no_cache else (args.cache_path or DEFAULT_CACHE_PATH)

    try:
        if getattr(args, "batch", False):
            from agents.remote_filter.batch import run_remote_filter_batch

            run_remote_filter_batch(
                input_path=input_path,
                classified_path=classified_path,
                config_path=args.config,
                user_timezone=args.user_timezone,
                cache_path=cache_path,
                poll_interval=getattr(args, "poll_interval", 60),
            )
        else:
            run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=args.config,
                user_timezone=args.user_timezone,
                cache_path=cache_path,
            )
    except FileNotFoundError as exc:
        log.error(str(exc))
        sys.exit(1)
    except ValueError as exc:
        # e.g. --batch with a non-openai provider
        log.error(str(exc))
        sys.exit(1)


def _add_remote_filter(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "remote-filter",
        help="Run the remote-filter agent over routed candidates into one classified output",
    )
    p.add_argument(
        "--run-date",
        default=None,
        dest="run_date",
        metavar="YYYY-MM-DD",
        type=_parse_run_date,
        help="Filter this day's partition; auto-resolves input/output paths under data/*/YYYY-MM-DD/",
    )
    p.add_argument(
        "--input",
        default=None,
        help="JSONL file or directory to read (overrides --run-date)",
    )
    p.add_argument(
        "--classified-output",
        default=None,
        dest="classified_output",
        help="JSONL path for classified jobs (overrides --run-date)",
    )
    p.add_argument(
        "--config",
        default="config/agent/remote_agent.yml",
        help="Remote-filter config YAML",
    )
    p.add_argument(
        "--user-timezone",
        default=os.environ.get("USER_TIMEZONE"),
        help="Candidate timezone context for the model",
    )
    p.add_argument(
        "--cache-path",
        default=None,
        dest="cache_path",
        help="JSONL path for the across-batch analysis cache (default: data/cache/remote_filter_analyses.jsonl)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        dest="no_cache",
        help="Disable the across-batch cache; always call the LLM",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        help="Submit all cache-miss jobs via the OpenAI Batch API (one blocking "
        "submit+poll), then write the same classified output. OpenAI provider only.",
    )
    p.add_argument(
        "--poll-interval",
        default=60,
        dest="poll_interval",
        type=int,
        metavar="SECONDS",
        help="Seconds between batch status polls when --batch is set (default: 60)",
    )
    p.set_defaults(func=_cmd_remote_filter)


def register(sub: argparse._SubParsersAction) -> None:
    _add_remote_filter(sub)
