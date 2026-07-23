import argparse
import logging
import sys

from jobs_cli._common import (
    DATA_DIR,
    _add_save_output,
    _auto_path,
    _output,
    _parse_run_date,
    _resolve_dest,
    _slug,
    _summary,
)

from ._maps import TIME_MAP, WORKPLACE_MAP, JOBTYPE_MAP
from .pii import pii_redaction_total

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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
    # CLI has no DB connection, so results are printed only — not persisted to
    # raw.company_aliases. Run the planner pre-pass or wire conn= into discover.run()
    # if you need persistence.
    from job_scraper.discover import run as discover_run

    companies = args.companies
    log.info("Probing %d companies...", len(companies))
    discovered = discover_run(companies)

    found = {c: discovered[c] for c in companies if discovered.get(c)}
    not_found = [c for c in companies if not discovered.get(c)]

    print(f"\n{'Company':<30} {'Boards'}")
    print("-" * 50)
    for company in companies:
        boards = discovered.get(company, [])
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
        allowed_title_keywords=args.allowed_title_keywords,
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
# run-config subcommand
# ---------------------------------------------------------------------------


def _cmd_run_config(args) -> None:
    from job_scraper.config import ConfigError, load_config, load_quality_gate_config
    from job_scraper.quality_gate import ScrapeQualityError, check_scrape

    try:
        scrapers = load_config(args.config)
        quality_config = load_quality_gate_config()
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
            check_scrape(
                s.source_name,
                jobs,
                quality_config.thresholds_for(s.source_name),
            )
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
                dest = _auto_path(
                    _slug(s.source_name),
                    label,
                    run_date=getattr(args, "run_date", None),
                )
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                dest = None
            _output(jobs, dest)
            total += len(jobs)
            total_scrubbed += sum(pii_redaction_total(j.scrub_counts) for j in jobs)
        except ScrapeQualityError as exc:
            log.exception("%s failed quality gate — skipping: %s", s.source_name, exc)
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
# Umbrella registration
# ---------------------------------------------------------------------------


def register(sub: argparse._SubParsersAction) -> None:
    _add_linkedin(sub)
    _add_jobspy(sub)
    _add_greenhouse(sub)
    _add_lever(sub)
    _add_ashby(sub)
    _add_sel(sub)
    _add_discover(sub)
    _add_run_config(sub)
