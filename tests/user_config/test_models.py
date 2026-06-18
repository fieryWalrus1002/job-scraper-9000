"""Validation behavior of the human-facing config models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from user_config import CandidateProfileInput, SearchConfigInput

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text())


def test_engineer_template_validates():
    cfg = SearchConfigInput.model_validate(_load("search_engineer.yml"))
    assert cfg.roles.target_titles.preferred[0] == "Mechanical Engineer"
    assert cfg.scrape_preferences.freshness_hours == 48


def test_writer_template_validates():
    cfg = SearchConfigInput.model_validate(_load("search_writer.yml"))
    assert cfg.organizations.similar_to == ["Scientific American", "NPR"]
    assert cfg.industries_and_domains.excluded == ["crypto", "adtech"]


def test_filled_profile_validates():
    profile = CandidateProfileInput.model_validate(_load("profile_filled.yml"))
    assert profile.constraints.hard
    assert profile.evidence is not None
    # Template's hand-bumped version is parsed but carries no authority.
    assert profile.profile_version == "2026-06-01_candidate_profile_v0.1"


def test_typo_key_is_rejected():
    """extra='forbid': a misspelled key must fail loudly, not silently no-op."""
    data = _load("search_engineer.yml")
    data["scrape_preferences"]["freshness_hourz"] = 24
    with pytest.raises(ValidationError, match="freshness_hourz"):
        SearchConfigInput.model_validate(data)


def test_empty_preferred_titles_rejected():
    data = _load("search_engineer.yml")
    data["roles"]["target_titles"]["preferred"] = []
    with pytest.raises(ValidationError):
        SearchConfigInput.model_validate(data)


def test_no_acceptable_arrangement_rejected():
    data = _load("search_engineer.yml")
    wa = data["work_constraints"]["work_arrangements"]
    for key in ("remote", "hybrid", "onsite"):
        wa.setdefault(key, {})["acceptable"] = False
    with pytest.raises(ValidationError, match="no acceptable work arrangement"):
        SearchConfigInput.model_validate(data)


def test_email_is_normalized_and_checked():
    data = _load("search_engineer.yml")
    data["user"]["email"] = "  Friend@Example.COM "
    cfg = SearchConfigInput.model_validate(data)
    assert cfg.user.email == "friend@example.com"

    data["user"]["email"] = "not-an-email"
    with pytest.raises(ValidationError, match="plausible email"):
        SearchConfigInput.model_validate(data)


def test_omitted_sections_get_permissive_defaults():
    """A minimal config (user + profile meta + one title) is valid."""
    cfg = SearchConfigInput.model_validate(
        {
            "user": {"display_name": "Min", "email": "min@example.com"},
            "search_profile": {"name": "minimal"},
            "roles": {"target_titles": {"preferred": ["Editor"]}},
        }
    )
    wa = cfg.work_constraints.work_arrangements
    assert wa.remote.acceptable and wa.hybrid.acceptable and wa.onsite.acceptable
    assert cfg.scrape_preferences.include_local_searches is True


def test_scrape_preference_linkedin_defaults():
    """Salary floor defaults to no-floor; experience to the scraper default."""
    cfg = SearchConfigInput.model_validate(_load("search_engineer.yml"))
    assert cfg.scrape_preferences.salary_floor_k is None
    assert cfg.scrape_preferences.linkedin_experience_codes == ["2", "3", "4", "5"]


def test_valid_salary_floor_and_experience_codes_accepted():
    data = _load("search_engineer.yml")
    data["scrape_preferences"]["salary_floor_k"] = 120
    data["scrape_preferences"]["linkedin_experience_codes"] = ["3", "4"]
    cfg = SearchConfigInput.model_validate(data)
    assert cfg.scrape_preferences.salary_floor_k == 120
    assert cfg.scrape_preferences.linkedin_experience_codes == ["3", "4"]


def test_unsupported_salary_floor_rejected():
    """A floor the scraper has no f_SB2 bucket for fails at the API edge."""
    data = _load("search_engineer.yml")
    data["scrape_preferences"]["salary_floor_k"] = 70
    with pytest.raises(ValidationError, match="salary_floor_k"):
        SearchConfigInput.model_validate(data)


def test_invalid_experience_code_rejected():
    data = _load("search_engineer.yml")
    data["scrape_preferences"]["linkedin_experience_codes"] = ["7"]
    with pytest.raises(ValidationError, match="linkedin_experience_codes"):
        SearchConfigInput.model_validate(data)
