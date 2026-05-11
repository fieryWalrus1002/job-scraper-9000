"""
Tests for config.py — YAML parsing, override precedence, scraper building,
and validation errors.
"""
import textwrap
from pathlib import Path

import pytest

from job_scraper.config import ConfigError, load_config
from job_scraper.scrapers.greenhouse import GreenhouseScraper
from job_scraper.scrapers.jobspy import JobSpyScraper
from job_scraper.scrapers.lever import LeverScraper
from job_scraper.scrapers.linkedin import LinkedInJobScraper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(textwrap.dedent(content))
    return p


FULL_CONFIG = """\
global:
  default_max_results: 30
  hours_old: 48
  linkedin_time: week
  salary_floor_k: 120

linkedin:
  experience: "4,5"
  workplace: remote
  job_type: fulltime
  searches:
    - keywords: "LLM Ops"
    - keywords: "MLOps engineer"
    - keywords: "data engineer"

jobspy:
  sites: linkedin,indeed
  no_remote: false
  searches:
    - search_term: "data engineer"
      location: "Pullman, WA"
    - search_term: "MLOps"

greenhouse:
  boards:
    - anthropic
    - openai
    - palantir
"""


# ---------------------------------------------------------------------------
# Parsing — structure
# ---------------------------------------------------------------------------

def test_full_config_returns_correct_scraper_count(tmp_path):
    scrapers = load_config(_write_config(tmp_path, FULL_CONFIG))
    # 3 linkedin + 2 jobspy + 3 greenhouse = 8
    assert len(scrapers) == 8


def test_full_config_scraper_types(tmp_path):
    scrapers = load_config(_write_config(tmp_path, FULL_CONFIG))
    li  = [s for s in scrapers if isinstance(s, LinkedInJobScraper)]
    js  = [s for s in scrapers if isinstance(s, JobSpyScraper)]
    gh  = [s for s in scrapers if isinstance(s, GreenhouseScraper)]
    assert len(li) == 3
    assert len(js) == 2
    assert len(gh) == 3


def test_missing_linkedin_section_skips_linkedin(tmp_path):
    cfg = _write_config(tmp_path, """\
        greenhouse:
          boards:
            - anthropic
    """)
    scrapers = load_config(cfg)
    assert not any(isinstance(s, LinkedInJobScraper) for s in scrapers)
    assert len(scrapers) == 1


def test_missing_jobspy_section_skips_jobspy(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert not any(isinstance(s, JobSpyScraper) for s in scrapers)


def test_missing_greenhouse_section_skips_greenhouse(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert not any(isinstance(s, GreenhouseScraper) for s in scrapers)


def test_no_scraper_sections_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          default_max_results: 10
    """)
    with pytest.raises(ConfigError, match="no scraper sections"):
        load_config(cfg)


def test_missing_global_section_uses_defaults(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    query = scrapers[0].query
    assert query.max_results == 50        # _GlobalDefaults.default_max_results
    assert query.time_posted == "r86400"  # TIME_MAP["day"]


# ---------------------------------------------------------------------------
# Override precedence
# ---------------------------------------------------------------------------

def test_global_salary_floor_flows_into_linkedin(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          salary_floor_k: 120
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.salary_floor == 120_000


def test_per_search_salary_floor_overrides_global(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          salary_floor_k: 120
        linkedin:
          searches:
            - keywords: "Python"
              salary_floor_k: 80
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.salary_floor == 80_000


def test_global_linkedin_time_flows_into_query(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          linkedin_time: month
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.time_posted == "r2592000"


def test_per_search_time_overrides_global(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          linkedin_time: week
        linkedin:
          searches:
            - keywords: "Python"
              time: day
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.time_posted == "r86400"


def test_section_experience_overrides_default(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          experience: "5,6"
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.experience == "5,6"


def test_per_search_experience_overrides_section(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          experience: "4,5"
          searches:
            - keywords: "Python"
              experience: "6"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.experience == "6"


def test_global_hours_old_flows_into_jobspy(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          hours_old: 72
        jobspy:
          searches:
            - search_term: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.hours_old == 72


def test_per_search_location_overrides_usa_default(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          searches:
            - search_term: "data engineer"
              location: "Pullman, WA"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.location == "Pullman, WA"


def test_jobspy_search_without_location_defaults_to_usa(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          searches:
            - search_term: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.location == "USA"


def test_per_search_sites_replace_section_sites(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          sites: linkedin,indeed,zip_recruiter
          searches:
            - search_term: "Python"
              sites: glassdoor
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.site_name == ["glassdoor"]


def test_no_salary_floor_results_in_none(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.salary_floor is None


# ---------------------------------------------------------------------------
# Builder output — field mapping
# ---------------------------------------------------------------------------

def test_linkedin_workplace_mapped_correctly(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          workplace: hybrid
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.workplace == "3"  # WORKPLACE_MAP["hybrid"]


def test_linkedin_job_type_mapped_correctly(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          job_type: contract
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.job_type == "C"


def test_greenhouse_board_token_set(tmp_path):
    cfg = _write_config(tmp_path, """\
        greenhouse:
          boards:
            - stripe
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.board_token == "stripe"


def test_jobspy_no_remote_sets_is_remote_false(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          no_remote: true
          searches:
            - search_term: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.is_remote is False


def test_max_results_from_global(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          default_max_results: 75
        linkedin:
          searches:
            - keywords: "Python"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.max_results == 75


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_linkedin_search_missing_keywords_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - workplace: remote
    """)
    with pytest.raises(ConfigError, match="missing 'keywords'"):
        load_config(cfg)


def test_jobspy_search_missing_search_term_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          searches:
            - location: "USA"
    """)
    with pytest.raises(ConfigError, match="missing 'search_term'"):
        load_config(cfg)


def test_invalid_linkedin_time_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          linkedin_time: yesterday
        linkedin:
          searches:
            - keywords: "Python"
    """)
    with pytest.raises(ConfigError, match="Invalid linkedin_time"):
        load_config(cfg)


def test_invalid_salary_floor_k_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          salary_floor_k: 99
        linkedin:
          searches:
            - keywords: "Python"
    """)
    with pytest.raises(ConfigError, match="Invalid salary_floor_k"):
        load_config(cfg)


def test_invalid_workplace_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          workplace: office
          searches:
            - keywords: "Python"
    """)
    with pytest.raises(ConfigError, match="Invalid linkedin.workplace"):
        load_config(cfg)


def test_invalid_job_type_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          job_type: gig
          searches:
            - keywords: "Python"
    """)
    with pytest.raises(ConfigError, match="Invalid linkedin.job_type"):
        load_config(cfg)


def test_unknown_jobspy_site_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          sites: linkedin,monster
          searches:
            - search_term: "Python"
    """)
    with pytest.raises(ConfigError, match="Unknown jobspy site"):
        load_config(cfg)


def test_per_search_invalid_time_override_raises(tmp_path):
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - keywords: "Python"
              time: forever
    """)
    with pytest.raises(ConfigError, match="invalid time"):
        load_config(cfg)


def test_non_mapping_yaml_raises(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        load_config(cfg)


# ---------------------------------------------------------------------------
# Environment variable expansion
# ---------------------------------------------------------------------------

def test_env_var_expanded_in_jobspy_location(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME_LOCATION", "Pullman, WA")
    cfg = _write_config(tmp_path, """\
        jobspy:
          searches:
            - search_term: "data engineer"
              location: "${HOME_LOCATION}"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.location == "Pullman, WA"


def test_env_var_expanded_in_linkedin_keywords(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_TERM", "LLM Ops")
    cfg = _write_config(tmp_path, """\
        linkedin:
          searches:
            - keywords: "${SEARCH_TERM}"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.keywords == "LLM Ops"


def test_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("HOME_LOCATION", raising=False)
    cfg = _write_config(tmp_path, """\
        jobspy:
          searches:
            - search_term: "data engineer"
              location: "${HOME_LOCATION}"
    """)
    with pytest.raises(ConfigError, match="HOME_LOCATION"):
        load_config(cfg)


def test_plain_string_unchanged(tmp_path):
    cfg = _write_config(tmp_path, """\
        jobspy:
          searches:
            - search_term: "data engineer"
              location: "Seattle, WA"
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].query.location == "Seattle, WA"


# ---------------------------------------------------------------------------
# Lever section
# ---------------------------------------------------------------------------

def test_lever_section_creates_lever_scrapers(tmp_path):
    cfg = _write_config(tmp_path, """\
        lever:
          companies:
            - netflix
            - stripe
    """)
    scrapers = load_config(cfg)
    assert len(scrapers) == 2
    assert all(isinstance(s, LeverScraper) for s in scrapers)


def test_lever_company_tokens_set(tmp_path):
    cfg = _write_config(tmp_path, """\
        lever:
          companies:
            - netflix
            - stripe
    """)
    scrapers = load_config(cfg)
    companies = {s.query.company for s in scrapers}
    assert companies == {"netflix", "stripe"}


def test_lever_source_name(tmp_path):
    cfg = _write_config(tmp_path, """\
        lever:
          companies:
            - netflix
    """)
    scrapers = load_config(cfg)
    assert scrapers[0].source_name == "lever:netflix"


def test_missing_lever_section_skips_lever(tmp_path):
    cfg = _write_config(tmp_path, """\
        greenhouse:
          boards:
            - anthropic
    """)
    scrapers = load_config(cfg)
    assert not any(isinstance(s, LeverScraper) for s in scrapers)


def test_lever_counts_in_full_config(tmp_path):
    cfg = _write_config(tmp_path, """\
        greenhouse:
          boards:
            - anthropic
        lever:
          companies:
            - netflix
            - stripe
    """)
    scrapers = load_config(cfg)
    lever = [s for s in scrapers if isinstance(s, LeverScraper)]
    assert len(lever) == 2


def test_no_scraper_sections_includes_lever_in_error(tmp_path):
    cfg = _write_config(tmp_path, """\
        global:
          default_max_results: 10
    """)
    with pytest.raises(ConfigError, match="lever"):
        load_config(cfg)
