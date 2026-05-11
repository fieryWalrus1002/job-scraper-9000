import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ._maps import TIME_MAP, WORKPLACE_MAP, JOBTYPE_MAP
from .query import LinkedInSearchQuery, SALARY_FLOOR
from .scrapers.base import BaseScraper
from .scrapers.greenhouse import GreenhouseScraper, GreenhouseQuery
from .scrapers.jobspy import JobSpyScraper, JobSpyQuery, JOBSPY_SITES
from .scrapers.linkedin import LinkedInJobScraper

log = logging.getLogger(__name__)

_VALID_SALARY_K = {k // 1_000 for k in SALARY_FLOOR}


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Internal config dataclasses
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
            raise ConfigError(f"Invalid linkedin_time {t!r} — must be one of: {list(TIME_MAP)}")
        defaults.linkedin_time = t

    if "salary_floor_k" in g:
        sfk = int(g["salary_floor_k"])
        if sfk not in _VALID_SALARY_K:
            raise ConfigError(f"Invalid salary_floor_k {sfk} — must be one of: {sorted(_VALID_SALARY_K)}")
        defaults.salary_floor_k = sfk

    return defaults


def _parse_linkedin_section(raw: dict) -> _LinkedInSection | None:
    sec = raw.get("linkedin")
    if sec is None:
        return None

    workplace = str(sec.get("workplace", "remote"))
    if workplace not in WORKPLACE_MAP:
        raise ConfigError(f"Invalid linkedin.workplace {workplace!r} — must be one of: {list(WORKPLACE_MAP)}")

    job_type = str(sec.get("job_type", "fulltime"))
    if job_type not in JOBTYPE_MAP:
        raise ConfigError(f"Invalid linkedin.job_type {job_type!r} — must be one of: {list(JOBTYPE_MAP)}")

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
            raise ConfigError(f"Unknown jobspy site {site!r} — valid sites: {JOBSPY_SITES}")

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


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _build_scrapers(raw: dict) -> list[BaseScraper]:
    glob = _parse_global(raw)
    li = _parse_linkedin_section(raw)
    js = _parse_jobspy_section(raw)
    gh = _parse_greenhouse_section(raw)

    if li is None and js is None and gh is None:
        raise ConfigError("Config has no scraper sections (linkedin, jobspy, greenhouse)")

    scrapers: list[BaseScraper] = []

    if li:
        for i, entry in enumerate(li.searches):
            if "keywords" not in entry:
                raise ConfigError(f"linkedin.searches[{i}] is missing 'keywords'")

            workplace = str(entry.get("workplace", li.workplace))
            if workplace not in WORKPLACE_MAP:
                raise ConfigError(f"linkedin.searches[{i}] invalid workplace {workplace!r}")

            job_type = str(entry.get("job_type", li.job_type))
            if job_type not in JOBTYPE_MAP:
                raise ConfigError(f"linkedin.searches[{i}] invalid job_type {job_type!r}")

            time_key = str(entry.get("time", glob.linkedin_time))
            if time_key not in TIME_MAP:
                raise ConfigError(f"linkedin.searches[{i}] invalid time {time_key!r}")

            sfk = entry.get("salary_floor_k", glob.salary_floor_k)
            if sfk is not None:
                sfk = int(sfk)
                if sfk not in _VALID_SALARY_K:
                    raise ConfigError(f"linkedin.searches[{i}] invalid salary_floor_k {sfk}")

            query = LinkedInSearchQuery(
                keywords=str(entry["keywords"]),
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
                search_term=str(entry["search_term"]),
                location=str(entry.get("location", "USA")),
                site_name=sites,
                is_remote=not js.no_remote,
                hours_old=int(entry.get("hours_old", glob.hours_old)),
                results_wanted=int(entry.get("max_results", glob.default_max_results)),
            )
            scrapers.append(JobSpyScraper(query))

    if gh:
        for token in gh.boards:
            scrapers.append(GreenhouseScraper(GreenhouseQuery(board_token=token)))

    return scrapers
