"""
Tests for the scraper-owned CLI commands (linkedin, jobspy, greenhouse,
lever, ashby, sel, discover, run-config).

Shared helper tests (_slug, _auto_path, _output, etc.) live in
tests/jobs_cli/test_common.py. Top-level umbrella dispatch tests live
in tests/jobs_cli/test_main.py.
"""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from job_scraper.models import JobPosting
from jobs_cli.main import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(**overrides) -> JobPosting:
    defaults = dict(
        source="linkedin",
        source_job_id="1",
        source_url="http://x.com",
        title="Engineer",
        company="Acme",
        location="Remote",
        posted_at=None,
        description="",
        scraped_at="2024-01-01T00:00:00+00:00",
    )
    return JobPosting(**{**defaults, **overrides})


def _fake_args(**kwargs) -> argparse.Namespace:
    defaults = dict(output=None, save=False)
    return argparse.Namespace(**{**defaults, **kwargs})


def _parse_args(*argv):
    """Run main() with given argv, capture the Namespace via the scraper handler hook."""
    captured = {}

    def capture(args):
        captured["args"] = args

    with patch("sys.argv", ["job-scraper-9000", *argv]):
        with patch("job_scraper.cli._cmd_linkedin", side_effect=capture):
            with patch("job_scraper.cli._cmd_jobspy", side_effect=capture):
                with patch("job_scraper.cli._cmd_greenhouse", side_effect=capture):
                    with patch("job_scraper.cli._cmd_lever", side_effect=capture):
                        with patch("job_scraper.cli._cmd_ashby", side_effect=capture):
                            with patch("job_scraper.cli._cmd_sel", side_effect=capture):
                                with patch(
                                    "job_scraper.cli._cmd_discover", side_effect=capture
                                ):
                                    with patch(
                                        "job_scraper.cli._cmd_run_config",
                                        side_effect=capture,
                                    ):
                                        main()

    return captured["args"]


# ---------------------------------------------------------------------------
# linkedin — parsing
# ---------------------------------------------------------------------------


def test_linkedin_defaults():
    args = _parse_args("linkedin", "LLM Ops")
    assert args.keywords == "LLM Ops"
    assert args.time == "day"
    assert args.workplace == "remote"
    assert args.job_type == "fulltime"
    assert args.experience == "2,3,4,5"
    assert args.salary is None
    assert args.max_results == 25
    assert args.no_descriptions is False
    assert args.output is None
    assert args.save is False


def test_linkedin_salary_and_time():
    args = _parse_args("linkedin", "Python", "--salary", "120", "--time", "week")
    assert args.salary == 120
    assert args.time == "week"


def test_linkedin_no_descriptions_flag():
    args = _parse_args("linkedin", "Python", "--no-descriptions")
    assert args.no_descriptions is True


def test_linkedin_save_flag():
    args = _parse_args("linkedin", "Python", "--save")
    assert args.save is True
    assert args.output is None


def test_linkedin_output_flag():
    args = _parse_args("linkedin", "Python", "--output", "jobs.jsonl")
    assert args.output == "jobs.jsonl"
    assert args.save is False


def test_linkedin_save_and_output_mutually_exclusive():
    with patch(
        "sys.argv",
        ["job-scraper-9000", "linkedin", "Python", "--save", "-o", "x.jsonl"],
    ):
        with pytest.raises(SystemExit):
            main()


def test_jobspy_defaults():
    args = _parse_args("jobspy", "LLM Ops")
    assert args.keywords == "LLM Ops"
    assert args.sites == "linkedin,indeed,zip_recruiter"
    assert args.hours_old == 24
    assert args.remote is True
    assert args.max_results == 25


def test_jobspy_custom_sites():
    args = _parse_args("jobspy", "Python", "--sites", "linkedin,glassdoor")
    assert args.sites == "linkedin,glassdoor"


def test_jobspy_no_remote_flag():
    args = _parse_args("jobspy", "Python", "--no-remote")
    assert args.remote is False


def test_greenhouse_board_positional():
    args = _parse_args("greenhouse", "anthropic")
    assert args.board == "anthropic"
    assert args.no_descriptions is False


def test_greenhouse_no_descriptions():
    args = _parse_args("greenhouse", "anthropic", "--no-descriptions")
    assert args.no_descriptions is True


# ---------------------------------------------------------------------------
# Command handlers — mock the scraper, verify the query is built correctly
# ---------------------------------------------------------------------------


def _run_linkedin_cmd(**arg_overrides):
    from job_scraper.cli import _cmd_linkedin

    defaults = dict(
        keywords="LLM Ops",
        time="day",
        workplace="remote",
        job_type="fulltime",
        experience="2,3,4,5",
        salary=None,
        max_results=10,
        no_descriptions=False,
        output=None,
        save=False,
    )
    args = _fake_args(**{**defaults, **arg_overrides})

    mock_jobs = [_make_job()]
    with patch("job_scraper.scrapers.linkedin.LinkedInJobScraper") as MockScraper:
        MockScraper.return_value.scrape.return_value = mock_jobs
        with patch("job_scraper.cli._output"):
            _cmd_linkedin(args)
        return MockScraper.call_args[0][0]


def test_linkedin_cmd_maps_time_to_param():
    query = _run_linkedin_cmd(time="week")
    assert query.time_posted == "r604800"


def test_linkedin_cmd_maps_workplace_to_param():
    query = _run_linkedin_cmd(workplace="hybrid")
    assert query.workplace == "3"


def test_linkedin_cmd_maps_job_type_to_param():
    query = _run_linkedin_cmd(job_type="contract")
    assert query.job_type == "C"


def test_linkedin_cmd_salary_floor_converted_to_int():
    query = _run_linkedin_cmd(salary=120)
    assert query.salary_floor == 120_000


def test_linkedin_cmd_no_salary_is_none():
    query = _run_linkedin_cmd(salary=None)
    assert query.salary_floor is None


def test_linkedin_cmd_no_descriptions_sets_flag():
    query = _run_linkedin_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


def _run_jobspy_cmd(**arg_overrides):
    from job_scraper.cli import _cmd_jobspy

    defaults = dict(
        keywords="LLM Ops",
        sites="linkedin,indeed",
        location="USA",
        hours_old=24,
        remote=True,
        enforce_annual_salary=False,
        max_results=10,
        output=None,
        save=False,
    )
    args = _fake_args(**{**defaults, **arg_overrides})

    mock_jobs = [_make_job()]
    with patch("job_scraper.scrapers.jobspy.JobSpyScraper") as MockScraper:
        MockScraper.return_value.scrape.return_value = mock_jobs
        with patch("job_scraper.cli._output"):
            _cmd_jobspy(args)
        return MockScraper.call_args[0][0]


def test_jobspy_cmd_splits_sites():
    query = _run_jobspy_cmd(sites="linkedin,glassdoor,indeed")
    assert query.site_name == ["linkedin", "glassdoor", "indeed"]


def test_jobspy_cmd_passes_hours_old():
    query = _run_jobspy_cmd(hours_old=48)
    assert query.hours_old == 48


def test_jobspy_cmd_remote_flag():
    query = _run_jobspy_cmd(remote=False)
    assert query.is_remote is False


def _run_greenhouse_cmd(**arg_overrides):
    from job_scraper.cli import _cmd_greenhouse

    defaults = dict(board="anthropic", no_descriptions=False, output=None, save=False)
    args = _fake_args(**{**defaults, **arg_overrides})

    mock_jobs = [_make_job()]
    with patch("job_scraper.scrapers.greenhouse.GreenhouseScraper") as MockScraper:
        MockScraper.return_value.scrape.return_value = mock_jobs
        with patch("job_scraper.cli._output"):
            _cmd_greenhouse(args)
        return MockScraper.call_args[0][0]


def test_greenhouse_cmd_passes_board_token():
    query = _run_greenhouse_cmd(board="stripe")
    assert query.board_token == "stripe"


def test_greenhouse_cmd_no_descriptions_flag():
    query = _run_greenhouse_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


# ---------------------------------------------------------------------------
# lever
# ---------------------------------------------------------------------------


def test_lever_defaults():
    args = _parse_args("lever", "netflix")
    assert args.company == "netflix"
    assert args.no_descriptions is False
    assert args.save is False
    assert args.output is None


def test_lever_no_descriptions_flag():
    args = _parse_args("lever", "netflix", "--no-descriptions")
    assert args.no_descriptions is True


def test_lever_save_flag():
    args = _parse_args("lever", "netflix", "--save")
    assert args.save is True


def _run_lever_cmd(**arg_overrides):
    from job_scraper.cli import _cmd_lever

    defaults = dict(company="netflix", no_descriptions=False, output=None, save=False)
    args = _fake_args(**{**defaults, **arg_overrides})

    mock_jobs = [_make_job()]
    with patch("job_scraper.scrapers.lever.LeverScraper") as MockScraper:
        MockScraper.return_value.scrape.return_value = mock_jobs
        with patch("job_scraper.cli._output"):
            _cmd_lever(args)
        return MockScraper.call_args[0][0]


def test_lever_cmd_passes_company():
    query = _run_lever_cmd(company="stripe")
    assert query.company == "stripe"


def test_lever_cmd_no_descriptions_flag():
    query = _run_lever_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


# ---------------------------------------------------------------------------
# ashby
# ---------------------------------------------------------------------------


def test_ashby_defaults():
    args = _parse_args("ashby", "mistral")
    assert args.company == "mistral"
    assert args.no_descriptions is False
    assert args.save is False
    assert args.output is None


def test_ashby_no_descriptions_flag():
    args = _parse_args("ashby", "mistral", "--no-descriptions")
    assert args.no_descriptions is True


def test_ashby_save_flag():
    args = _parse_args("ashby", "mistral", "--save")
    assert args.save is True


def _run_ashby_cmd(**arg_overrides):
    from job_scraper.cli import _cmd_ashby

    defaults = dict(company="mistral", no_descriptions=False, output=None, save=False)
    args = _fake_args(**{**defaults, **arg_overrides})

    mock_jobs = [_make_job()]
    with patch("job_scraper.scrapers.ashby.AshbyScraper") as MockScraper:
        MockScraper.return_value.scrape.return_value = mock_jobs
        with patch("job_scraper.cli._output"):
            _cmd_ashby(args)
        return MockScraper.call_args[0][0]


def test_ashby_cmd_passes_company():
    query = _run_ashby_cmd(company="cohere")
    assert query.company == "cohere"


def test_ashby_cmd_no_descriptions_flag():
    query = _run_ashby_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


# ---------------------------------------------------------------------------
# run-config — parsing
# ---------------------------------------------------------------------------


def test_run_config_defaults():
    args = _parse_args("run-config", "config.yml")
    assert args.config == "config.yml"
    assert args.dry_run is False
    assert args.save is False


def test_run_config_dry_run_flag():
    args = _parse_args("run-config", "config.yml", "--dry-run")
    assert args.dry_run is True


def test_run_config_save_flag():
    args = _parse_args("run-config", "config.yml", "--save")
    assert args.save is True


def test_run_config_output_flag_rejected():
    with patch(
        "sys.argv", ["job-scraper-9000", "run-config", "config.yml", "-o", "out.jsonl"]
    ):
        with pytest.raises(SystemExit):
            main()


def test_run_config_run_date_default_is_none():
    args = _parse_args("run-config", "config.yml")
    assert args.run_date is None


def test_run_config_run_date_flag():
    args = _parse_args("run-config", "config.yml", "--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


# ---------------------------------------------------------------------------
# run-config — command handler
# ---------------------------------------------------------------------------


def _make_mock_scraper(source_name, describe_extra, jobs=None):
    s = MagicMock()
    s.source_name = source_name
    s.describe.return_value = {"source": source_name, **describe_extra}
    s.scrape.return_value = jobs if jobs is not None else [_make_job()]
    return s


def test_run_config_cmd_calls_output_per_scraper():
    from job_scraper.cli import _cmd_run_config

    scrapers = [
        _make_mock_scraper("linkedin", {"keywords": "Python"}),
        _make_mock_scraper("greenhouse:stripe", {"board_token": "stripe"}),
    ]
    args = _fake_args(config="config.yml", dry_run=False, save=False)

    with patch("job_scraper.config.load_config", return_value=scrapers):
        with patch("job_scraper.cli._output") as mock_output:
            _cmd_run_config(args)

    assert mock_output.call_count == 2


def test_run_config_cmd_save_uses_auto_path():
    from job_scraper.cli import _cmd_run_config

    scrapers = [
        _make_mock_scraper("linkedin", {"keywords": "Python"}),
        _make_mock_scraper("greenhouse:stripe", {"board_token": "stripe"}),
    ]
    args = _fake_args(config="config.yml", dry_run=False, save=True)

    with patch("job_scraper.config.load_config", return_value=scrapers):
        with patch("job_scraper.cli._output") as mock_output:
            with patch("pathlib.Path.mkdir"):
                _cmd_run_config(args)

    dests = [call.args[1] for call in mock_output.call_args_list]
    assert all(d is not None for d in dests)
    assert any("linkedin" in str(d) for d in dests)
    assert any("stripe" in str(d) for d in dests)


def test_run_config_cmd_isolates_scraper_failure():
    from job_scraper.cli import _cmd_run_config

    failing = _make_mock_scraper("linkedin", {"keywords": "Python"})
    failing.scrape.side_effect = Exception("rate limited")
    succeeding = _make_mock_scraper("greenhouse:stripe", {"board_token": "stripe"})

    args = _fake_args(config="config.yml", dry_run=False, save=False)

    with patch("job_scraper.config.load_config", return_value=[failing, succeeding]):
        with patch("job_scraper.cli._output") as mock_output:
            _cmd_run_config(args)

    assert mock_output.call_count == 1


def test_run_config_cmd_dry_run_skips_scrape(capsys):
    from job_scraper.cli import _cmd_run_config

    s = _make_mock_scraper("linkedin", {"keywords": "Python"})
    args = _fake_args(config="config.yml", dry_run=True, save=False)

    with patch("job_scraper.config.load_config", return_value=[s]):
        _cmd_run_config(args)

    s.scrape.assert_not_called()
    assert "linkedin" in capsys.readouterr().out


def test_run_config_save_with_run_date_writes_to_dated_partition():
    from job_scraper.cli import _cmd_run_config

    scrapers = [_make_mock_scraper("linkedin", {"keywords": "Python"})]
    args = _fake_args(
        config="config.yml", dry_run=False, save=True, run_date="2026-05-16"
    )

    with patch("job_scraper.config.load_config", return_value=scrapers):
        with patch("job_scraper.cli._output") as mock_output:
            with patch("pathlib.Path.mkdir"):
                _cmd_run_config(args)

    dest = mock_output.call_args_list[0].args[1]
    assert str(dest).startswith("data/raw/2026-05-16/")
    assert "linkedin" in str(dest)
