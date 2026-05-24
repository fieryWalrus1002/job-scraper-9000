import argparse
import logging
import sys

from jobs_cli._common import _parse_positive_int, _parse_run_date

log = logging.getLogger(__name__)


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
