import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


from ._maps import TIME_MAP, WORKPLACE_MAP, JOBTYPE_MAP
from .company_boards import DEFAULT_PATH as BOARDS_DB_PATH, load as load_boards
from .query import LinkedInSearchQuery, SALARY_FLOOR, SELSearchQuery
from .scrapers.base import BaseScraper
from .scrapers.ashby import AshbyScraper, AshbyQuery
from .scrapers.greenhouse import GreenhouseScraper, GreenhouseQuery
from .scrapers.jobspy import JobSpyScraper, JobSpyQuery, JOBSPY_SITES
from .scrapers.lever import LeverScraper, LeverQuery
from .scrapers.linkedin import LinkedInJobScraper
from .scrapers.sel import SELJobScraper


log = logging.getLogger(__name__)

_VALID_SALARY_K = {k // 1_000 for k in SALARY_FLOOR}


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Internal config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class _SELSection:
    location: str = "pullman_wa"
    job_type: str = "regular"
    fetch_descriptions: bool = True


@dataclass
class _GlobalDefaults:
    default_max_results: int = 50
    hours_old: int = 24
    linkedin_time: str = "day"
    salary_floor_k: int | None = None


@dataclass
class _LinkedInSection:
    experience: str = "2,3,4,5"
    workplace: str = "remote"
    job_type: str = "fulltime"
    searches: list[dict] = field(default_factory=list)


@dataclass
class _JobSpySection:
    sites: str = "linkedin,indeed,zip_recruiter"
    no_remote: bool = False
    searches: list[dict] = field(default_factory=list)


@dataclass
class _GreenhouseSection:
    boards: list[str] = field(default_factory=list)


@dataclass
class _LeverSection:
    companies: list[str] = field(default_factory=list)


@dataclass
class _AshbySection:
    companies: list[str] = field(default_factory=list)


@dataclass
class _CompaniesSection:
    companies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _expand(value: str) -> str:
    """Replace ${VAR_NAME} references with environment variable values."""

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        val = os.environ.get(name)
        if val is None:
            raise ConfigError(f"Environment variable ${{{name}}} is not set")
        return val

    return re.sub(r"\$\{([^}]+)\}", _sub, value)


def load_config(path: str | Path) -> list[BaseScraper]:
    """Parse a YAML search config and return a flat list of configured scrapers."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a YAML mapping, got {type(raw).__name__}")
    return _build_scrapers(raw)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_global(raw: dict) -> _GlobalDefaults:
    g = raw.get("global") or {}
    defaults = _GlobalDefaults()

    if "default_max_results" in g:
        defaults.default_max_results = int(g["default_max_results"])

    if "hours_old" in g:
        defaults.hours_old = int(g["hours_old"])

    if "linkedin_time" in g:
        t = str(g["linkedin_time"])
        if t not in TIME_MAP:
            raise ConfigError(
                f"Invalid linkedin_time {t!r} — must be one of: {list(TIME_MAP)}"
            )
        defaults.linkedin_time = t

    if "salary_floor_k" in g:
        sfk = int(g["salary_floor_k"])
        if sfk not in _VALID_SALARY_K:
            raise ConfigError(
                f"Invalid salary_floor_k {sfk} — must be one of: {sorted(_VALID_SALARY_K)}"
            )
        defaults.salary_floor_k = sfk

    return defaults


def _parse_sel_section(raw: dict) -> _SELSection | None:
    if "sel" not in raw:
        return None
    sec = raw.get("sel") or {}
    return _SELSection(
        location=str(sec.get("location", "pullman_wa")),
        job_type=str(sec.get("job_type", "regular")),
        fetch_descriptions=bool(sec.get("fetch_descriptions", True)),
    )


def _parse_linkedin_section(raw: dict) -> _LinkedInSection | None:
    sec = raw.get("linkedin")
    if sec is None:
        return None

    workplace = str(sec.get("workplace", "remote"))
    if workplace not in WORKPLACE_MAP:
        raise ConfigError(
            f"Invalid linkedin.workplace {workplace!r} — must be one of: {list(WORKPLACE_MAP)}"
        )

    job_type = str(sec.get("job_type", "fulltime"))
    if job_type not in JOBTYPE_MAP:
        raise ConfigError(
            f"Invalid linkedin.job_type {job_type!r} — must be one of: {list(JOBTYPE_MAP)}"
        )

    return _LinkedInSection(
        experience=str(sec.get("experience", "2,3,4,5")),
        workplace=workplace,
        job_type=job_type,
        searches=list(sec.get("searches") or []),
    )


def _parse_jobspy_section(raw: dict) -> _JobSpySection | None:
    sec = raw.get("jobspy")
    if sec is None:
        return None

    sites_str = str(sec.get("sites", "linkedin,indeed,zip_recruiter"))
    for site in (s.strip() for s in sites_str.split(",")):
        if site not in JOBSPY_SITES:
            raise ConfigError(
                f"Unknown jobspy site {site!r} — valid sites: {JOBSPY_SITES}"
            )

    return _JobSpySection(
        sites=sites_str,
        no_remote=bool(sec.get("no_remote", False)),
        searches=list(sec.get("searches") or []),
    )


def _parse_greenhouse_section(raw: dict) -> _GreenhouseSection | None:
    sec = raw.get("greenhouse")
    if sec is None:
        return None
    return _GreenhouseSection(boards=[str(b) for b in (sec.get("boards") or [])])


def _parse_lever_section(raw: dict) -> _LeverSection | None:
    sec = raw.get("lever")
    if sec is None:
        return None
    return _LeverSection(companies=[str(c) for c in (sec.get("companies") or [])])


def _parse_ashby_section(raw: dict) -> _AshbySection | None:
    sec = raw.get("ashby")
    if sec is None:
        return None
    return _AshbySection(companies=[str(c) for c in (sec.get("companies") or [])])


def _parse_companies_section(raw: dict) -> _CompaniesSection | None:
    companies = raw.get("companies")
    if not companies:
        return None
    return _CompaniesSection(companies=[str(c) for c in companies])


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _build_scrapers(raw: dict) -> list[BaseScraper]:
    glob = _parse_global(raw)
    sl = _parse_sel_section(raw)
    li = _parse_linkedin_section(raw)
    js = _parse_jobspy_section(raw)
    gh = _parse_greenhouse_section(raw)
    lv = _parse_lever_section(raw)
    ab = _parse_ashby_section(raw)
    co = _parse_companies_section(raw)

    if (
        sl is None
        and li is None
        and js is None
        and gh is None
        and lv is None
        and ab is None
        and co is None
    ):
        raise ConfigError(
            "Config has no scraper sections (sel, linkedin, jobspy, greenhouse, lever, ashby, companies)"
        )

    scrapers: list[BaseScraper] = []

    if sl:
        # Map the YAML strings to the Query object expected by the Scraper
        query = SELSearchQuery(
            location_key=sl.location,
            worker_sub_types=[sl.job_type],
            fetch_descriptions=sl.fetch_descriptions,
        )
        scrapers.append(SELJobScraper(query))

    if li:
        for i, entry in enumerate(li.searches):
            if "keywords" not in entry:
                raise ConfigError(f"linkedin.searches[{i}] is missing 'keywords'")

            workplace = str(entry.get("workplace", li.workplace))
            if workplace not in WORKPLACE_MAP:
                raise ConfigError(
                    f"linkedin.searches[{i}] invalid workplace {workplace!r}"
                )

            job_type = str(entry.get("job_type", li.job_type))
            if job_type not in JOBTYPE_MAP:
                raise ConfigError(
                    f"linkedin.searches[{i}] invalid job_type {job_type!r}"
                )

            time_key = str(entry.get("time", glob.linkedin_time))
            if time_key not in TIME_MAP:
                raise ConfigError(f"linkedin.searches[{i}] invalid time {time_key!r}")

            sfk = entry.get("salary_floor_k", glob.salary_floor_k)
            if sfk is not None:
                sfk = int(sfk)
                if sfk not in _VALID_SALARY_K:
                    raise ConfigError(
                        f"linkedin.searches[{i}] invalid salary_floor_k {sfk}"
                    )

            query = LinkedInSearchQuery(
                keywords=_expand(str(entry["keywords"])),
                time_posted=TIME_MAP[time_key],
                workplace=WORKPLACE_MAP[workplace],
                job_type=JOBTYPE_MAP[job_type],
                experience=str(entry.get("experience", li.experience)),
                salary_floor=sfk * 1_000 if sfk else None,
                max_results=int(entry.get("max_results", glob.default_max_results)),
            )
            scrapers.append(LinkedInJobScraper(query))

    if js:
        for i, entry in enumerate(js.searches):
            if "search_term" not in entry:
                raise ConfigError(f"jobspy.searches[{i}] is missing 'search_term'")

            # Per-search sites replace (not union) the section default
            sites_str = str(entry.get("sites", js.sites))
            sites = [s.strip() for s in sites_str.split(",")]
            for site in sites:
                if site not in JOBSPY_SITES:
                    raise ConfigError(f"jobspy.searches[{i}] unknown site {site!r}")

            query = JobSpyQuery(
                search_term=_expand(str(entry["search_term"])),
                location=_expand(str(entry.get("location", "USA"))),
                site_name=sites,
                is_remote=not js.no_remote,
                hours_old=int(entry.get("hours_old", glob.hours_old)),
                results_wanted=int(entry.get("max_results", glob.default_max_results)),
            )
            scrapers.append(JobSpyScraper(query))

    if gh:
        for token in gh.boards:
            scrapers.append(GreenhouseScraper(GreenhouseQuery(board_token=token)))

    if lv:
        for company in lv.companies:
            scrapers.append(LeverScraper(LeverQuery(company=company)))

    if ab:
        for company in ab.companies:
            scrapers.append(AshbyScraper(AshbyQuery(company=company)))

    if co:
        db = load_boards(BOARDS_DB_PATH)
        unknown = []
        for company in co.companies:
            boards = db.get(company, [])
            if not boards:
                unknown.append(company)
                continue
            for board in boards:
                if board == "greenhouse":
                    scrapers.append(
                        GreenhouseScraper(GreenhouseQuery(board_token=company))
                    )
                elif board == "lever":
                    scrapers.append(LeverScraper(LeverQuery(company=company)))
                elif board == "ashby":
                    scrapers.append(AshbyScraper(AshbyQuery(company=company)))
                else:
                    log.warning(
                        "Company %r has unsupported board %r in company_boards.json",
                        company,
                        board,
                    )
                    if company not in unknown:
                        unknown.append(company)
        if unknown:
            log.warning(
                "%d companies have no boards recorded in company_boards.json — run 'discover' first: %s",
                len(unknown),
                unknown,
            )

    return scrapers
