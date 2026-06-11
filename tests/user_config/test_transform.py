"""Golden + contract tests for the human-config → pipeline-YAML transform.

Goldens pin the exact output (review the golden diff when the transform
changes); contract tests feed the emitted search config to the *real*
``job_scraper.config.load_config`` and the emitted profile to the *real*
skills_fit loader, so format drift against either consumer fails loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import job_scraper.config as scraper_config
from agents.skills_fit.utils import _format_profile_block, load_candidate_profile
from user_config import (
    REMOTE_CLASSIFICATIONS,
    CandidateProfileInput,
    SearchConfigInput,
    candidate_profile_to_pipeline_yaml,
    derive_policies,
    dump_yaml,
    search_config_to_pipeline_yaml,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"

VERSION = "2026-06-11.abc123def456"


def _search(name: str) -> SearchConfigInput:
    return SearchConfigInput.model_validate(
        yaml.safe_load((FIXTURES / name).read_text())
    )


def _profile() -> CandidateProfileInput:
    return CandidateProfileInput.model_validate(
        yaml.safe_load((FIXTURES / "profile_filled.yml").read_text())
    )


# ---------------------------------------------------------------------------
# Goldens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "golden"),
    [
        ("search_engineer.yml", "search_engineer_expected.yml"),
        ("search_writer.yml", "search_writer_expected.yml"),
    ],
)
def test_search_transform_matches_golden(fixture: str, golden: str):
    out = search_config_to_pipeline_yaml(_search(fixture))
    expected = yaml.safe_load((GOLDEN / golden).read_text())
    assert out == expected


def test_profile_transform_matches_golden():
    out = candidate_profile_to_pipeline_yaml(_profile(), profile_version=VERSION)
    expected = yaml.safe_load((GOLDEN / "profile_expected.yml").read_text())
    # Block scalars round-trip with trailing newlines; compare stripped text.
    for key in ("summary", "level"):
        assert out[key].strip() == expected[key].strip()
        out.pop(key), expected.pop(key)
    assert out == expected


def test_transform_is_deterministic():
    cfg = _search("search_engineer.yml")
    assert search_config_to_pipeline_yaml(cfg) == search_config_to_pipeline_yaml(cfg)


# ---------------------------------------------------------------------------
# Contract: the real consumers accept the emitted YAML
# ---------------------------------------------------------------------------


def test_search_output_loads_through_real_parser(tmp_path, monkeypatch):
    # Empty boards DB: target_companies resolve to zero scrapers (with a loud
    # warning), keeping the expected count independent of company_boards.json.
    boards = tmp_path / "boards.json"
    boards.write_text(json.dumps({}))
    monkeypatch.setattr(scraper_config, "BOARDS_DB_PATH", boards)

    out = search_config_to_pipeline_yaml(_search("search_engineer.yml"))
    cfg_file = tmp_path / "search.yml"
    cfg_file.write_text(dump_yaml(out))

    scrapers = scraper_config.load_config(cfg_file)

    # 6 titles -> 6 linkedin + 6 national jobspy + 12 local jobspy (2 locations)
    assert len(scrapers) == 24


def test_profile_output_feeds_skills_fit_prompt(tmp_path):
    out = candidate_profile_to_pipeline_yaml(_profile(), profile_version=VERSION)
    profile_file = tmp_path / "candidate_profile.yml"
    profile_file.write_text(dump_yaml(out))

    loaded = load_candidate_profile(profile_file)
    assert loaded["profile_version"] == VERSION

    block = _format_profile_block(loaded)
    assert "Core skills: Failure analysis and root-cause investigation" in block
    # Flattened constraints render as strings, not a stringified dict.
    assert "HARD: Must be authorized to work in the US" in block
    assert "{'hard'" not in block


# ---------------------------------------------------------------------------
# Transform rules
# ---------------------------------------------------------------------------


def test_weekly_cadence_maps_to_linkedin_week():
    cfg = _search("search_engineer.yml")
    cfg = cfg.model_copy(deep=True)
    cfg.scrape_preferences.cadence = "weekly"
    assert search_config_to_pipeline_yaml(cfg)["global"]["linkedin_time"] == "week"


def test_no_general_boards_emits_no_linkedin_or_jobspy():
    cfg = _search("search_engineer.yml").model_copy(deep=True)
    cfg.scrape_preferences.include_general_job_boards = False
    out = search_config_to_pipeline_yaml(cfg)
    assert "linkedin" not in out and "jobspy" not in out
    assert "companies" in out  # company boards are gated independently


def test_hybrid_only_user_gets_hybrid_workplace_and_no_remote():
    data = yaml.safe_load((FIXTURES / "search_engineer.yml").read_text())
    wa = data["work_constraints"]["work_arrangements"]
    wa["remote"]["acceptable"] = False
    wa["hybrid"]["acceptable"] = True
    out = search_config_to_pipeline_yaml(SearchConfigInput.model_validate(data))
    assert out["linkedin"]["workplace"] == "hybrid"
    assert out["jobspy"]["no_remote"] is True
    # Remote-national searches are dropped; only local searches remain.
    assert all(s["location"] != "United States" for s in out["jobspy"]["searches"])


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_remote_only_user_policies():
    policies = derive_policies(_search("search_engineer.yml"))
    assert policies.remote.acceptable_classifications == [
        "fully_remote",
        "remote_with_quarterly_travel",
        "remote_with_monthly_travel",
        "remote_with_frequent_travel",
        "unclear",  # always acceptable — never a silent filter
    ]
    # roles.excluded_titles + keywords.excluded, deduped
    assert policies.prefilter.excluded_title_terms == [
        "Sales Engineer",
        "Field Service Technician",
        "sales",
        "field service",
    ]


def test_everything_acceptable_is_fully_permissive():
    cfg = SearchConfigInput.model_validate(
        {
            "user": {"display_name": "Min", "email": "min@example.com"},
            "search_profile": {"name": "minimal"},
            "roles": {"target_titles": {"preferred": ["Editor"]}},
        }
    )
    policies = derive_policies(cfg)
    assert policies.remote.acceptable_classifications == list(REMOTE_CLASSIFICATIONS)
    assert policies.prefilter.excluded_title_terms == []
