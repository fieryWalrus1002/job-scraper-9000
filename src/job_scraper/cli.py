import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from ._maps import TIME_MAP, WORKPLACE_MAP, JOBTYPE_MAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path("data/raw")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_run_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid --run-date {value!r}: expected YYYY-MM-DD (e.g. 2026-05-19)"
        )
    return value


def _auto_path(source: str, keywords: str, run_date: str | None = None) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    if run_date:
        return DATA_DIR / run_date / f"{ts}_{source}_{_slug(keywords)}.jsonl"
    return DATA_DIR / f"{ts}_{source}_{_slug(keywords)}.jsonl"


def _resolve_dest(args, source: str, keywords: str) -> Path | None:
    if args.output:
        return Path(args.output)
    if getattr(args, "save", False):
        path = _auto_path(source, keywords)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def _output(jobs, dest: Path | None) -> None:
    lines = [json.dumps(asdict(j)) for j in jobs]
    if dest:
        with open(dest, "w") as f:
            f.write("\n".join(lines) + "\n")
        log.info("Wrote %d jobs → %s", len(jobs), dest)
    else:
        sys.stdout.write("\n".join(lines) + "\n")


def _summary(jobs) -> None:
    scrubbed = sum(
        j.scrub_counts.get("email", 0) + j.scrub_counts.get("phone", 0) for j in jobs
    )
    log.info("Total: %d jobs | PII items redacted: %d", len(jobs), scrubbed)


def _add_save_output(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Write JSONL to a specific file (default: stdout)",
    )
    group.add_argument(
        "--save",
        action="store_true",
        help=f"Write JSONL to {DATA_DIR}/YYYY-MM-DD_<source>_<keywords>.jsonl",
    )


# ---------------------------------------------------------------------------
# linkedin subcommand
# ---------------------------------------------------------------------------


def _cmd_linkedin(args) -> None:
    from job_scraper.scrapers.linkedin import LinkedInJobScraper
    from job_scraper.query import LinkedInSearchQuery

    query = LinkedInSearchQuery(
        keywords=args.keywords,
        time_posted=TIME_MAP[args.time],
        workplace=WORKPLACE_MAP[args.workplace],
        job_type=JOBTYPE_MAP[args.job_type],
        experience=args.experience,
        salary_floor=args.salary * 1_000 if args.salary else None,
        max_results=args.max_results,
        fetch_descriptions=not args.no_descriptions,
    )

    log.info(
        "LinkedIn: %r | time=%s | workplace=%s | salary_floor=%s | max=%d",
        args.keywords,
        args.time,
        args.workplace,
        f"${args.salary}k" if args.salary else "any",
        args.max_results,
    )

    jobs = LinkedInJobScraper(query).scrape()
    _summary(jobs)
    _output(jobs, _resolve_dest(args, "linkedin", args.keywords))


def _add_linkedin(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("linkedin", help="LinkedIn guest API — no login, no Selenium")
    p.add_argument("keywords", help='Search keywords, e.g. "LLM Ops"')
    p.add_argument(
        "--time",
        choices=list(TIME_MAP),
        default="day",
        help="How far back to look (default: day)",
    )
    p.add_argument("--workplace", choices=list(WORKPLACE_MAP), default="remote")
    p.add_argument(
        "--job-type", choices=list(JOBTYPE_MAP), default="fulltime", dest="job_type"
    )
    p.add_argument(
        "--experience",
        default="2,3,4,5",
        help="Comma-separated LinkedIn experience codes: 1=intern 2=entry 3=assoc 4=mid-senior 5=director 6=exec",
    )
    p.add_argument(
        "--salary",
        type=int,
        choices=[40, 60, 80, 100, 120],
        metavar="FLOOR_K",
        help="Minimum salary floor in thousands (40, 60, 80, 100, 120)",
    )
    p.add_argument("--max-results", type=int, default=25, dest="max_results")
    p.add_argument(
        "--no-descriptions",
        action="store_true",
        dest="no_descriptions",
        help="Skip fetching full descriptions (faster, good for testing)",
    )
    _add_save_output(p)
    p.set_defaults(func=_cmd_linkedin)


# ---------------------------------------------------------------------------
# jobspy subcommand
# ---------------------------------------------------------------------------


def _cmd_jobspy(args) -> None:
    from job_scraper.scrapers.jobspy import JobSpyScraper, JobSpyQuery

    sites = [s.strip() for s in args.sites.split(",")]
    query = JobSpyQuery(
        search_term=args.keywords,
        location=args.location,
        site_name=sites,
        is_remote=args.remote,
        hours_old=args.hours_old,
        results_wanted=args.max_results,
        enforce_annual_salary=args.enforce_annual_salary,
    )

    log.info(
        "JobSpy: %r | sites=%s | hours_old=%d | remote=%s | max=%d",
        args.keywords,
        sites,
        args.hours_old,
        args.remote,
        args.max_results,
    )

    jobs = JobSpyScraper(query).scrape()
    _summary(jobs)
    _output(jobs, _resolve_dest(args, "jobspy", args.keywords))


def _add_jobspy(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "jobspy",
        help="Multi-board via python-jobspy (LinkedIn / Indeed / ZipRecruiter / Glassdoor / Google)",
    )
    p.add_argument("keywords", help='Search keywords, e.g. "LLM Ops"')
    p.add_argument(
        "--sites",
        default="linkedin,indeed,zip_recruiter",
        help="Comma-separated site names (default: linkedin,indeed,zip_recruiter)",
    )
    p.add_argument("--location", default="USA")
    p.add_argument("--hours-old", type=int, default=24, dest="hours_old")
    p.add_argument(
        "--no-remote",
        action="store_false",
        dest="remote",
        help="Don't filter for remote-only roles",
    )
    p.add_argument(
        "--enforce-annual-salary",
        action="store_true",
        dest="enforce_annual_salary",
        help="Only include postings with an annual salary listed",
    )
    p.add_argument("--max-results", type=int, default=25, dest="max_results")
    _add_save_output(p)
    p.set_defaults(func=_cmd_jobspy, remote=True)


# ---------------------------------------------------------------------------
# greenhouse subcommand
# ---------------------------------------------------------------------------


def _cmd_greenhouse(args) -> None:
    from job_scraper.scrapers.greenhouse import GreenhouseScraper, GreenhouseQuery

    query = GreenhouseQuery(
        board_token=args.board,
        fetch_descriptions=not args.no_descriptions,
    )

    log.info(
        "Greenhouse: board=%s | descriptions=%s", args.board, not args.no_descriptions
    )

    jobs = GreenhouseScraper(query).scrape()
    _summary(jobs)
    _output(jobs, _resolve_dest(args, f"greenhouse-{args.board}", args.board))


def _add_greenhouse(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("greenhouse", help="Greenhouse ATS public JSON API")
    p.add_argument(
        "board", help="Board token — the slug in boards.greenhouse.io/<token>"
    )
    p.add_argument(
        "--no-descriptions",
        action="store_true",
        dest="no_descriptions",
        help="Skip fetching full descriptions",
    )
    _add_save_output(p)
    p.set_defaults(func=_cmd_greenhouse)


# ---------------------------------------------------------------------------
# lever subcommand
# ---------------------------------------------------------------------------


def _cmd_lever(args) -> None:
    from job_scraper.scrapers.lever import LeverScraper, LeverQuery

    query = LeverQuery(
        company=args.company,
        fetch_descriptions=not args.no_descriptions,
    )

    log.info(
        "Lever: company=%s | descriptions=%s", args.company, not args.no_descriptions
    )

    jobs = LeverScraper(query).scrape()
    _summary(jobs)
    _output(jobs, _resolve_dest(args, f"lever-{args.company}", args.company))


def _add_lever(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("lever", help="Lever ATS public JSON API")
    p.add_argument(
        "company", help="Company slug — e.g. 'netflix' for jobs.lever.co/netflix"
    )
    p.add_argument(
        "--no-descriptions",
        action="store_true",
        dest="no_descriptions",
        help="Skip fetching descriptions",
    )
    _add_save_output(p)
    p.set_defaults(func=_cmd_lever)


# ---------------------------------------------------------------------------
# ashby subcommand
# ---------------------------------------------------------------------------


def _cmd_ashby(args) -> None:
    from job_scraper.scrapers.ashby import AshbyScraper, AshbyQuery

    query = AshbyQuery(
        company=args.company,
        fetch_descriptions=not args.no_descriptions,
    )

    log.info(
        "Ashby: company=%s | descriptions=%s", args.company, not args.no_descriptions
    )

    jobs = AshbyScraper(query).scrape()
    _summary(jobs)
    _output(jobs, _resolve_dest(args, f"ashby-{args.company}", args.company))


def _add_ashby(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("ashby", help="Ashby ATS public JSON API")
    p.add_argument(
        "company", help="Company slug — e.g. 'mistral' for jobs.ashbyhq.com/mistral"
    )
    p.add_argument(
        "--no-descriptions",
        action="store_true",
        dest="no_descriptions",
        help="Skip fetching descriptions",
    )
    _add_save_output(p)
    p.set_defaults(func=_cmd_ashby)


# ---------------------------------------------------------------------------
# discover subcommand
# ---------------------------------------------------------------------------


def _cmd_discover(args) -> None:
    from job_scraper.discover import run as discover_run
    from job_scraper.company_boards import (
        load as load_boards,
        DEFAULT_PATH as BOARDS_PATH,
    )

    companies = args.companies
    log.info("Probing %d companies...", len(companies))
    discover_run(companies)

    db = load_boards(BOARDS_PATH)

    found = {c: db[c] for c in companies if db.get(c)}
    not_found = [c for c in companies if not db.get(c)]

    print(f"\n{'Company':<30} {'Boards'}")
    print("-" * 50)
    for company in companies:
        boards = db.get(company, [])
        print(f"  {company:<28} {', '.join(boards) if boards else '(not found)'}")

    print("\n# --- paste into config yml ---")
    print("companies:")
    for company in found:
        print(f"  - {company}")
    for company in not_found:
        print(f"  # - {company}  (not found)")


def _add_discover(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("discover", help="Find which ATS boards a list of companies use")
    p.add_argument(
        "companies",
        nargs="+",
        metavar="COMPANY",
        help="Company slugs to probe (e.g. anthropic mistral stripe)",
    )
    p.set_defaults(func=_cmd_discover)


# ---------------------------------------------------------------------------
# sel subcommand
# ---------------------------------------------------------------------------


def _cmd_sel(args) -> None:
    from job_scraper.scrapers.sel import SELJobScraper
    from job_scraper.query import SELSearchQuery

    query = SELSearchQuery(
        location_key=args.location,
        worker_sub_types=[args.job_type],
        fetch_descriptions=not args.no_descriptions,
    )
    log.info(
        "SEL: location=%s | job_type=%s | descriptions=%s",
        args.location,
        args.job_type,
        not args.no_descriptions,
    )
    jobs = SELJobScraper(query).scrape()
    _summary(jobs)
    _output(jobs, _resolve_dest(args, "sel", "sel"))


def _add_sel(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("sel", help="Schweitzer Engineering Laboratories (Workday)")
    p.add_argument(
        "--location", default="pullman_wa", help="Location key (default: pullman_wa)"
    )
    p.add_argument(
        "--job-type",
        default="regular",
        dest="job_type",
        choices=["regular", "temporary"],
        help="Worker sub-type filter (default: regular)",
    )
    p.add_argument(
        "--no-descriptions",
        action="store_true",
        dest="no_descriptions",
        help="Skip fetching full descriptions",
    )
    _add_save_output(p)
    p.set_defaults(func=_cmd_sel)


# ---------------------------------------------------------------------------
# prefilter subcommand
# ---------------------------------------------------------------------------


def _cmd_prefilter(args) -> None:
    from prefilter.router import run_prefilter

    run_date = getattr(args, "run_date", None)
    if run_date:
        input_path = args.input or f"data/raw/{run_date}"
        remote_out = args.remote_out or f"data/prefiltered/{run_date}/remote_filter_input.jsonl"
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


# ---------------------------------------------------------------------------
# remote-filter subcommand
# ---------------------------------------------------------------------------


def _cmd_remote_filter(args) -> None:
    from agents.remote_filter.runner import run_remote_filter

    run_date = getattr(args, "run_date", None)
    if run_date:
        input_path = args.input or f"data/prefiltered/{run_date}"
        pass_path = args.pass_output or f"data/filtered/{run_date}/remote_filter_pass.jsonl"
        trash_path = args.trash_output or f"data/trash/{run_date}/remote_filter_trash.jsonl"
    else:
        input_path = args.input or "data/prefiltered/remote_filter_input.jsonl"
        pass_path = args.pass_output or "data/filtered/remote_filter_pass.jsonl"
        trash_path = args.trash_output or "data/trash/remote_filter_trash.jsonl"

    from agents.remote_filter.cache import DEFAULT_CACHE_PATH

    cache_path = None if args.no_cache else (args.cache_path or DEFAULT_CACHE_PATH)

    try:
        run_remote_filter(
            input_path=input_path,
            pass_path=pass_path,
            trash_path=trash_path,
            config_path=args.config,
            user_location=args.user_location,
            user_timezone=args.user_timezone,
            cache_path=cache_path,
        )
    except FileNotFoundError as exc:
        log.error(str(exc))
        sys.exit(1)


def _add_remote_filter(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "remote-filter",
        help="Run the remote-filter agent over routed candidates and split pass/trash outputs",
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
        "--pass-output",
        default=None,
        help="JSONL path for jobs that pass the filter (overrides --run-date)",
    )
    p.add_argument(
        "--trash-output",
        default=None,
        help="JSONL path for rejected jobs (overrides --run-date)",
    )
    p.add_argument(
        "--config",
        default="config/agent/remote_agent.yml",
        help="Remote-filter config YAML",
    )
    p.add_argument(
        "--user-location",
        default=os.environ.get("USER_LOCATION", "USA"),
        help="Candidate location for geographic restriction checks",
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
    p.set_defaults(func=_cmd_remote_filter)


# ---------------------------------------------------------------------------
# run-config subcommand
# ---------------------------------------------------------------------------


def _cmd_run_config(args) -> None:
    from job_scraper.config import load_config, ConfigError

    try:
        scrapers = load_config(args.config)
    except ConfigError as exc:
        log.error("Config error: %s", exc)
        sys.exit(1)

    log.info("Loaded %d scrapers from %s", len(scrapers), args.config)

    if args.dry_run:
        for s in scrapers:
            info = s.describe()
            details = "  ".join(f"{k}={v}" for k, v in info.items() if k != "source")
            print(f"  [{info['source']}]  {details}")
        return

    from job_scraper.skip_list import (
        load as load_skip,
        record as record_skip,
        is_permanent,
    )

    skip = load_skip()

    total = 0
    total_scrubbed = 0
    for s in scrapers:
        if s.source_name in skip:
            entry = skip[s.source_name]
            failed_at = entry.get("failed_at") if isinstance(entry, dict) else None
            failed_at_display = (
                failed_at[:10] if isinstance(failed_at, str) else "unknown-date"
            )
            error = entry.get("error") if isinstance(entry, dict) else None
            error_display = error if error is not None else "unknown error"
            log.warning(
                "Skipping %s — known failure recorded %s: %s",
                s.source_name,
                failed_at_display,
                error_display,
            )
            continue
        try:
            jobs = s.scrape()
            log.info("%s → %d jobs", s.source_name, len(jobs))
            if args.save:
                info = s.describe()
                label = (
                    info.get("keywords")
                    or info.get("search_term")
                    or info.get("company")
                    or info.get("board_token")
                    or s.source_name
                )
                dest = _auto_path(_slug(s.source_name), label, run_date=getattr(args, "run_date", None))
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                dest = None
            _output(jobs, dest)
            total += len(jobs)
            total_scrubbed += sum(
                j.scrub_counts.get("email", 0) + j.scrub_counts.get("phone", 0)
                for j in jobs
            )
        except Exception as exc:
            log.error("%s failed — skipping: %s", s.source_name, exc)
            if is_permanent(exc):
                try:
                    record_skip(s.source_name, exc)
                except Exception as record_exc:
                    log.error(
                        "Failed to record permanent skip for %s: %s",
                        s.source_name,
                        record_exc,
                    )

    log.info("Total: %d jobs | PII items redacted: %d", total, total_scrubbed)


def _add_run_config(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run-config", help="Run all searches defined in a YAML config file"
    )
    p.add_argument("config", metavar="CONFIG", help="Path to YAML search config")
    p.add_argument(
        "--run-date",
        default=None,
        dest="run_date",
        metavar="YYYY-MM-DD",
        type=_parse_run_date,
        help="Write all outputs under data/raw/YYYY-MM-DD/ (creates a run partition)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print scrapers that would run without making any network calls",
    )
    p.add_argument(
        "--save",
        action="store_true",
        help=f"Write each scraper's results to {DATA_DIR}/YYYY-MM-DD_<source>_<keywords>.jsonl immediately on completion",
    )
    p.set_defaults(func=_cmd_run_config)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="job-scraper",
        description="Scrape job postings from LinkedIn, multi-board (JobSpy), or Greenhouse ATS.",
    )
    sub = parser.add_subparsers(dest="command", metavar="SCRAPER")
    sub.required = True

    _add_linkedin(sub)
    _add_jobspy(sub)
    _add_greenhouse(sub)
    _add_lever(sub)
    _add_ashby(sub)
    _add_sel(sub)
    _add_discover(sub)
    _add_prefilter(sub)
    _add_remote_filter(sub)
    _add_run_config(sub)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
