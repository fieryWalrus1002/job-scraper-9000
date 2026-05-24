import argparse
import logging
import sys

from jobs_cli._common import _parse_run_date

log = logging.getLogger(__name__)


def _cmd_prefilter(args) -> None:
    from prefilter.router import run_prefilter

    run_date = getattr(args, "run_date", None)
    if run_date:
        input_path = args.input or f"data/raw/{run_date}"
        remote_out = (
            args.remote_out or f"data/prefiltered/{run_date}/remote_filter_input.jsonl"
        )
        local_out = args.local_out or f"data/local/{run_date}/local_jobs.jsonl"
        trash_out = args.trash_out or f"data/trash/{run_date}/prefilter_trash.jsonl"
    else:
        input_path = args.input or "data/raw"
        remote_out = args.remote_out or "data/prefiltered/remote_filter_input.jsonl"
        local_out = args.local_out or "data/local/local_jobs.jsonl"
        trash_out = args.trash_out or "data/trash/prefilter_trash.jsonl"

    try:
        run_prefilter(
            input_path=input_path,
            remote_out=remote_out,
            local_out=local_out,
            trash_out=trash_out,
            config_path=args.config,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        log.error(str(exc))
        sys.exit(1)


def _add_prefilter(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "prefilter",
        help="Deterministically route raw jobs before the remote-filter agent",
    )
    p.add_argument(
        "--run-date",
        default=None,
        dest="run_date",
        metavar="YYYY-MM-DD",
        type=_parse_run_date,
        help="Route this day's partition; auto-resolves input/output paths under data/*/YYYY-MM-DD/",
    )
    p.add_argument(
        "--input",
        default=None,
        help="Raw JSONL file or directory to read (overrides --run-date)",
    )
    p.add_argument(
        "--config",
        default="config/agent/prefilter.yml",
        help="Prefilter config YAML",
    )
    p.add_argument(
        "--remote-out",
        default=None,
        help="JSONL path for jobs routed to the remote filter (overrides --run-date)",
    )
    p.add_argument(
        "--local-out",
        default=None,
        help="JSONL path for local jobs (overrides --run-date)",
    )
    p.add_argument(
        "--trash-out",
        default=None,
        help="JSONL path for rejected jobs (overrides --run-date)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Route jobs in memory and print summary without writing files",
    )
    p.set_defaults(func=_cmd_prefilter)


def register(sub: argparse._SubParsersAction) -> None:
    _add_prefilter(sub)
