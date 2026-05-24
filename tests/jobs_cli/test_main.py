"""Tests for the umbrella entrypoint in jobs_cli.main."""

from unittest.mock import patch

import pytest

from jobs_cli.main import main


def test_missing_subcommand_exits():
    with patch("sys.argv", ["job-scraper-9000"]):
        with pytest.raises(SystemExit):
            main()


def test_run_config_invalid_run_date_exits():
    with patch(
        "sys.argv",
        ["job-scraper-9000", "run-config", "config.yml", "--run-date", "not-a-date"],
    ):
        with pytest.raises(SystemExit):
            main()


def test_prefilter_invalid_run_date_exits():
    with patch("sys.argv", ["job-scraper-9000", "prefilter", "--run-date", "20260519"]):
        with pytest.raises(SystemExit):
            main()


def test_remote_filter_invalid_run_date_exits():
    with patch(
        "sys.argv", ["job-scraper-9000", "remote-filter", "--run-date", "2026/05/19"]
    ):
        with pytest.raises(SystemExit):
            main()


def test_skills_fit_invalid_run_date_exits():
    with patch(
        "sys.argv", ["job-scraper-9000", "skills-fit", "--run-date", "2026/05/19"]
    ):
        with pytest.raises(SystemExit):
            main()


def test_skills_fit_invalid_limit_exits():
    with patch("sys.argv", ["job-scraper-9000", "skills-fit", "--limit", "0"]):
        with pytest.raises(SystemExit):
            main()
