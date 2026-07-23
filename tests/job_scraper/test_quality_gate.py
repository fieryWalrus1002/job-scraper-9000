from __future__ import annotations

import logging

import pytest

from job_scraper.config import ConfigError, load_quality_gate_config
from job_scraper.models import JobPosting
from job_scraper.quality_gate import (
    ScrapeQualityError,
    ScrapeQualityThresholds,
    check_scrape,
)


def _job(
    *,
    description: str = "x" * 120,
    posted_at: str | None = "2024-01-15",
    workplace: str | None = "remote",
) -> JobPosting:
    search_params = {"workplace": workplace} if workplace else {}
    return JobPosting(
        source="linkedin",
        source_job_id="job-1",
        source_url="https://example.test/jobs/1",
        title="Engineer",
        company="Acme",
        location="Remote",
        posted_at=posted_at,
        description=description,
        scraped_at="2024-01-16T00:00:00+00:00",
        search_params=search_params,
    )


def test_check_scrape_passes_and_logs_observed_metrics(caplog):
    thresholds = ScrapeQualityThresholds(check_workplace=True)

    with caplog.at_level(logging.INFO, logger="job_scraper.quality_gate"):
        check_scrape("linkedin", [_job(), _job()], thresholds)

    assert "linkedin quality min job count observed=2 threshold=1" in caplog.text
    assert "description completeness pct observed=100.0%" in caplog.text
    assert "posted_at pct observed=100.0%" in caplog.text
    assert "workplace provenance pct observed=100.0%" in caplog.text


def test_check_scrape_raises_on_zero_jobs_with_source_and_metric():
    with pytest.raises(ScrapeQualityError, match="linkedin.*min job count"):
        check_scrape("linkedin", [], ScrapeQualityThresholds(min_jobs=1))


def test_check_scrape_raises_on_low_description_completeness():
    jobs = [_job(description="short"), _job(description="x" * 120)]
    thresholds = ScrapeQualityThresholds(min_desc_chars=100, min_complete_pct=0.75)

    with pytest.raises(
        ScrapeQualityError, match="linkedin.*description completeness pct"
    ):
        check_scrape("linkedin", jobs, thresholds)


def test_check_scrape_raises_on_low_posted_at_rate():
    jobs = [_job(posted_at=None), _job(posted_at="2024-01-15")]
    thresholds = ScrapeQualityThresholds(min_posted_at_pct=0.75)

    with pytest.raises(ScrapeQualityError, match="linkedin.*posted_at pct"):
        check_scrape("linkedin", jobs, thresholds)


def test_check_scrape_raises_on_low_workplace_rate_when_enabled():
    jobs = [_job(workplace=None), _job(workplace="remote")]
    thresholds = ScrapeQualityThresholds(
        check_workplace=True,
        min_workplace_pct=0.75,
    )

    with pytest.raises(ScrapeQualityError, match="linkedin.*workplace provenance pct"):
        check_scrape("linkedin", jobs, thresholds)


def test_check_scrape_skips_workplace_when_disabled():
    check_scrape(
        "greenhouse:acme",
        [_job(workplace=None), _job(workplace=None)],
        ScrapeQualityThresholds(check_workplace=False),
    )


def test_load_quality_gate_config_merges_global_and_source_overrides(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          min_jobs: 2
          min_complete_pct: 0.4
          check_workplace: false
        sources:
          linkedin:
            check_workplace: true
            min_workplace_pct: 0.8
        """
    )

    loaded = load_quality_gate_config(cfg)

    linkedin = loaded.thresholds_for("linkedin")
    assert linkedin.min_jobs == 2
    assert linkedin.min_complete_pct == 0.4
    assert linkedin.check_workplace is True
    assert linkedin.min_workplace_pct == 0.8
    assert loaded.thresholds_for("greenhouse:acme").check_workplace is False


def test_load_quality_gate_config_rejects_unknown_keys(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text("global:\n  typo: 1\n")

    with pytest.raises(ConfigError, match="unknown quality gate key"):
        load_quality_gate_config(cfg)


# ---------------------------------------------------------------------------
# Fix 1 — missing file → ConfigError, not FileNotFoundError
# ---------------------------------------------------------------------------


def test_load_quality_gate_config_missing_file_raises_config_error(tmp_path):
    missing = tmp_path / "does_not_exist.yml"
    with pytest.raises(ConfigError, match="Quality gate config not found"):
        load_quality_gate_config(missing)


# ---------------------------------------------------------------------------
# Fix 2 — unknown top-level keys → ConfigError
# ---------------------------------------------------------------------------


def test_load_quality_gate_config_rejects_unknown_top_level_keys(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          min_jobs: 1
        sources:
          linkedin:
            check_workplace: true
        bad_key: true
        another_bad: 42
        """
    )
    with pytest.raises(ConfigError, match="unknown top-level key"):
        load_quality_gate_config(cfg)


# ---------------------------------------------------------------------------
# Fix 3 — null / wrong-type scalar → ConfigError
# ---------------------------------------------------------------------------


def test_load_quality_gate_config_null_scalar_raises_config_error(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          min_jobs: null
        """
    )
    with pytest.raises(ConfigError, match="min_jobs must be a number"):
        load_quality_gate_config(cfg)


def test_load_quality_gate_config_string_for_int_raises_config_error(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          min_jobs: "not_a_number"
        """
    )
    with pytest.raises(ConfigError, match="min_jobs must be a number"):
        load_quality_gate_config(cfg)


# ---------------------------------------------------------------------------
# Fix 4 — strict boolean coercion
# ---------------------------------------------------------------------------


def test_load_quality_gate_config_quoted_false_is_false(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          enabled: "false"
          check_workplace: "FALSE"
        """
    )
    loaded = load_quality_gate_config(cfg)
    assert loaded.global_defaults.enabled is False
    assert loaded.global_defaults.check_workplace is False


def test_load_quality_gate_config_quoted_true_is_true(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          enabled: "true"
          check_workplace: "True"
        """
    )
    loaded = load_quality_gate_config(cfg)
    assert loaded.global_defaults.enabled is True
    assert loaded.global_defaults.check_workplace is True


def test_load_quality_gate_config_bad_string_bool_raises(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          enabled: "yes"
        """
    )
    with pytest.raises(ConfigError, match="enabled must be true/false"):
        load_quality_gate_config(cfg)


def test_load_quality_gate_config_int_for_bool_raises(tmp_path):
    cfg = tmp_path / "quality_gate.yml"
    cfg.write_text(
        """
        global:
          enabled: 1
        """
    )
    with pytest.raises(ConfigError, match="enabled must be a boolean"):
        load_quality_gate_config(cfg)


# ---------------------------------------------------------------------------
# Part 2 — zero-jobs policy: single min_jobs failure, not three
# ---------------------------------------------------------------------------


def test_check_scrape_zero_jobs_yields_single_min_jobs_failure():
    thresholds = ScrapeQualityThresholds(
        min_jobs=1,
        min_complete_pct=0.5,
        min_posted_at_pct=0.25,
        check_workplace=True,
        min_workplace_pct=0.9,
    )
    with pytest.raises(ScrapeQualityError) as exc_info:
        check_scrape("linkedin", [], thresholds)

    # Exactly one failure message (min_jobs), not three
    failures = exc_info.value.args[0].split("; ")
    assert len(failures) == 1
    assert "min job count" in failures[0]


def test_check_scrape_zero_jobs_with_min_jobs_zero_passes():
    thresholds = ScrapeQualityThresholds(min_jobs=0)
    # Should not raise — zero jobs is acceptable when min_jobs=0
    check_scrape("narrow-source", [], thresholds)
