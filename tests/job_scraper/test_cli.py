"""
Tests for the CLI layer.

Strategy:
- Utility functions (_slug, _auto_path, _resolve_dest, _output) tested directly.
- Argument parsing tested by patching sys.argv and catching the parsed args
  before any scraper is invoked.
- Command handlers (_cmd_linkedin, _cmd_jobspy, _cmd_greenhouse) tested by
  passing a fake Namespace and mocking the scraper classes — network is
  never touched.
"""

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_scraper.cli import (
    DATA_DIR,
    _auto_path,
    _output,
    _parse_run_date,
    _resolve_dest,
    _slug,
    main,
)
from job_scraper.models import JobPosting


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


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------


def test_slug_lowercases():
    assert _slug("LLM Ops") == "llm-ops"


def test_slug_collapses_special_chars():
    assert _slug("data  engineer!!") == "data-engineer"


def test_slug_strips_leading_trailing_dashes():
    assert _slug("  -python-  ") == "python"


def test_slug_preserves_numbers():
    assert _slug("Python 3.11") == "python-3-11"


# ---------------------------------------------------------------------------
# _auto_path
# ---------------------------------------------------------------------------


def test_auto_path_format():
    with patch("job_scraper.cli.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-11_10-30"
        p = _auto_path("linkedin", "LLM Ops")

    assert p == DATA_DIR / "2026-05-11_10-30_linkedin_llm-ops.jsonl"


def test_auto_path_slugifies_keywords():
    with patch("job_scraper.cli.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-11_10-30"
        p = _auto_path("jobspy", "Data Engineer (Senior)")

    assert p.name == "2026-05-11_10-30_jobspy_data-engineer-senior.jsonl"


def test_auto_path_with_run_date_uses_dated_partition():
    with patch("job_scraper.cli.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-16_09-00"
        p = _auto_path("linkedin", "LLM Ops", run_date="2026-05-16")

    assert p == DATA_DIR / "2026-05-16" / "2026-05-16_09-00_linkedin_llm-ops.jsonl"


# ---------------------------------------------------------------------------
# _parse_run_date
# ---------------------------------------------------------------------------


def test_parse_run_date_accepts_valid_date():
    assert _parse_run_date("2026-05-19") == "2026-05-19"


def test_parse_run_date_rejects_invalid_format():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_run_date("19-05-2026")


def test_parse_run_date_rejects_path_traversal():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_run_date("../../etc/passwd")


def test_run_config_invalid_run_date_exits():
    with patch("sys.argv", ["job-scraper", "run-config", "config.yml", "--run-date", "not-a-date"]):
        with pytest.raises(SystemExit):
            main()


def test_prefilter_invalid_run_date_exits():
    with patch("sys.argv", ["job-scraper", "prefilter", "--run-date", "20260519"]):
        with pytest.raises(SystemExit):
            main()


def test_remote_filter_invalid_run_date_exits():
    with patch("sys.argv", ["job-scraper", "remote-filter", "--run-date", "2026/05/19"]):
        with pytest.raises(SystemExit):
            main()


# ---------------------------------------------------------------------------
# _resolve_dest
# ---------------------------------------------------------------------------


def test_resolve_dest_no_flags_returns_none():
    args = _fake_args(output=None, save=False)
    assert _resolve_dest(args, "linkedin", "Python") is None


def test_resolve_dest_output_flag_returns_path():
    args = _fake_args(output="my_jobs.jsonl", save=False)
    assert _resolve_dest(args, "linkedin", "Python") == Path("my_jobs.jsonl")


def test_resolve_dest_save_flag_returns_auto_path(tmp_path):
    args = _fake_args(output=None, save=True)
    with patch("job_scraper.cli.DATA_DIR", tmp_path):
        with patch("job_scraper.cli.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-05-11_10-30"
            result = _resolve_dest(args, "linkedin", "Python")

    assert result == tmp_path / "2026-05-11_10-30_linkedin_python.jsonl"
    assert result.parent.exists()


# ---------------------------------------------------------------------------
# _output
# ---------------------------------------------------------------------------


def test_output_to_stdout_writes_jsonl(capsys):
    jobs = [_make_job(title="Dev A"), _make_job(title="Dev B")]
    _output(jobs, dest=None)
    captured = capsys.readouterr().out
    lines = [ln for ln in captured.strip().splitlines() if ln]
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "Dev A"
    assert json.loads(lines[1])["title"] == "Dev B"


def test_output_to_file_writes_jsonl(tmp_path):
    dest = tmp_path / "out.jsonl"
    jobs = [_make_job(title="Dev A"), _make_job(source_job_id="2", title="Dev B")]
    _output(jobs, dest=dest)
    lines = dest.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "Dev A"


def test_output_empty_list_to_stdout(capsys):
    _output([], dest=None)
    assert capsys.readouterr().out.strip() == ""


# ---------------------------------------------------------------------------
# Argument parsing — invoke main() with patched sys.argv, intercept the
# parsed Namespace before any scraper runs.
# ---------------------------------------------------------------------------


def _parse_args(*argv):
    """Call main() with given argv, capture the Namespace via the func hook."""
    captured = {}

    def capture(args):
        captured["args"] = args

    with patch("sys.argv", ["job-scraper", *argv]):
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
                                        "job_scraper.cli._cmd_prefilter",
                                        side_effect=capture,
                                    ):
                                        with patch(
                                            "job_scraper.cli._cmd_remote_filter",
                                            side_effect=capture,
                                        ):
                                            with patch(
                                                "job_scraper.cli._cmd_run_config",
                                                side_effect=capture,
                                            ):
                                                main()

    return captured["args"]


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
        "sys.argv", ["job-scraper", "linkedin", "Python", "--save", "-o", "x.jsonl"]
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


def test_missing_subcommand_exits():
    with patch("sys.argv", ["job-scraper"]):
        with pytest.raises(SystemExit):
            main()


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
    # Scrapers are deferred imports inside the command functions, so patch at source.
    with patch("job_scraper.scrapers.linkedin.LinkedInJobScraper") as MockScraper:
        MockScraper.return_value.scrape.return_value = mock_jobs
        with patch("job_scraper.cli._output"):
            _cmd_linkedin(args)
        return MockScraper.call_args[0][0]  # the LinkedInSearchQuery passed to __init__


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
        return MockScraper.call_args[0][0]  # the JobSpyQuery


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
        return MockScraper.call_args[0][0]  # the GreenhouseQuery


def test_greenhouse_cmd_passes_board_token():
    query = _run_greenhouse_cmd(board="stripe")
    assert query.board_token == "stripe"


def test_greenhouse_cmd_no_descriptions_flag():
    query = _run_greenhouse_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


# ---------------------------------------------------------------------------
# lever — argument parsing and command handler
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
        return MockScraper.call_args[0][0]  # the LeverQuery


def test_lever_cmd_passes_company():
    query = _run_lever_cmd(company="stripe")
    assert query.company == "stripe"


def test_lever_cmd_no_descriptions_flag():
    query = _run_lever_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


# ---------------------------------------------------------------------------
# ashby — argument parsing and command handler
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
        return MockScraper.call_args[0][0]  # the AshbyQuery


def test_ashby_cmd_passes_company():
    query = _run_ashby_cmd(company="cohere")
    assert query.company == "cohere"


def test_ashby_cmd_no_descriptions_flag():
    query = _run_ashby_cmd(no_descriptions=True)
    assert query.fetch_descriptions is False


# ---------------------------------------------------------------------------
# run-config — argument parsing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# prefilter — argument parsing and command handler
# ---------------------------------------------------------------------------


def test_prefilter_defaults():
    args = _parse_args("prefilter")
    assert args.input is None
    assert args.run_date is None
    assert args.config == "config/agent/prefilter.yml"
    assert args.remote_out is None
    assert args.local_out is None
    assert args.trash_out is None
    assert args.dry_run is False


def test_prefilter_custom_paths():
    args = _parse_args(
        "prefilter",
        "--input",
        "raw.jsonl",
        "--config",
        "prefilter.yml",
        "--remote-out",
        "remote.jsonl",
        "--local-out",
        "local.jsonl",
        "--trash-out",
        "trash.jsonl",
        "--dry-run",
    )
    assert args.input == "raw.jsonl"
    assert args.config == "prefilter.yml"
    assert args.remote_out == "remote.jsonl"
    assert args.local_out == "local.jsonl"
    assert args.trash_out == "trash.jsonl"
    assert args.dry_run is True


def test_prefilter_cmd_calls_runner():
    from job_scraper.cli import _cmd_prefilter

    args = _fake_args(
        input="raw.jsonl",
        config="prefilter.yml",
        remote_out="remote.jsonl",
        local_out="local.jsonl",
        trash_out="trash.jsonl",
        dry_run=True,
    )

    with patch("prefilter.router.run_prefilter") as mock_run:
        _cmd_prefilter(args)

    mock_run.assert_called_once_with(
        input_path="raw.jsonl",
        remote_out="remote.jsonl",
        local_out="local.jsonl",
        trash_out="trash.jsonl",
        config_path="prefilter.yml",
        dry_run=True,
    )


# ---------------------------------------------------------------------------
# remote-filter — argument parsing and command handler
# ---------------------------------------------------------------------------


def test_remote_filter_defaults():
    with patch.dict("os.environ", {}, clear=True):
        with patch("job_scraper.cli.load_dotenv"):
            args = _parse_args("remote-filter")
    assert args.input is None
    assert args.run_date is None
    assert args.pass_output is None
    assert args.trash_output is None
    assert args.config == "config/agent/remote_agent.yml"
    assert args.user_location == "USA"
    assert args.user_timezone is None


def test_remote_filter_custom_paths():
    args = _parse_args(
        "remote-filter",
        "--input",
        "raw.jsonl",
        "--pass-output",
        "pass.jsonl",
        "--trash-output",
        "trash.jsonl",
        "--config",
        "remote.yml",
        "--user-location",
        "Canada",
        "--user-timezone",
        "PST",
    )
    assert args.input == "raw.jsonl"
    assert args.pass_output == "pass.jsonl"
    assert args.trash_output == "trash.jsonl"
    assert args.config == "remote.yml"
    assert args.user_location == "Canada"
    assert args.user_timezone == "PST"


def test_remote_filter_cmd_calls_runner():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from job_scraper.cli import _cmd_remote_filter

    args = _fake_args(
        input="raw.jsonl",
        pass_output="pass.jsonl",
        trash_output="trash.jsonl",
        config="remote.yml",
        user_location="USA",
        user_timezone="PST",
        cache_path=None,
        no_cache=False,
    )

    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="raw.jsonl",
        pass_path="pass.jsonl",
        trash_path="trash.jsonl",
        config_path="remote.yml",
        user_location="USA",
        user_timezone="PST",
        cache_path=DEFAULT_CACHE_PATH,
    )


# ---------------------------------------------------------------------------
# run-config — argument parsing
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
        "sys.argv", ["job-scraper", "run-config", "config.yml", "-o", "out.jsonl"]
    ):
        with pytest.raises(SystemExit):
            main()


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


# ---------------------------------------------------------------------------
# run-config — --run-date flag
# ---------------------------------------------------------------------------


def test_run_config_run_date_default_is_none():
    args = _parse_args("run-config", "config.yml")
    assert args.run_date is None


def test_run_config_run_date_flag():
    args = _parse_args("run-config", "config.yml", "--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


def test_run_config_save_with_run_date_writes_to_dated_partition():
    from job_scraper.cli import _cmd_run_config

    scrapers = [_make_mock_scraper("linkedin", {"keywords": "Python"})]
    args = _fake_args(config="config.yml", dry_run=False, save=True, run_date="2026-05-16")

    with patch("job_scraper.config.load_config", return_value=scrapers):
        with patch("job_scraper.cli._output") as mock_output:
            with patch("pathlib.Path.mkdir"):
                _cmd_run_config(args)

    dest = mock_output.call_args_list[0].args[1]
    assert str(dest).startswith("data/raw/2026-05-16/")
    assert "linkedin" in str(dest)


# ---------------------------------------------------------------------------
# prefilter — --run-date flag and path resolution
# ---------------------------------------------------------------------------


def test_prefilter_run_date_flag():
    args = _parse_args("prefilter", "--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


def test_prefilter_cmd_no_run_date_uses_legacy_defaults():
    from job_scraper.cli import _cmd_prefilter

    args = _fake_args(
        input=None,
        config="prefilter.yml",
        remote_out=None,
        local_out=None,
        trash_out=None,
        dry_run=False,
        run_date=None,
    )
    with patch("prefilter.router.run_prefilter") as mock_run:
        _cmd_prefilter(args)

    mock_run.assert_called_once_with(
        input_path="data/raw",
        remote_out="data/prefiltered/remote_filter_input.jsonl",
        local_out="data/local/local_jobs.jsonl",
        trash_out="data/trash/prefilter_trash.jsonl",
        config_path="prefilter.yml",
        dry_run=False,
    )


def test_prefilter_cmd_run_date_resolves_partitioned_paths():
    from job_scraper.cli import _cmd_prefilter

    args = _fake_args(
        input=None,
        config="prefilter.yml",
        remote_out=None,
        local_out=None,
        trash_out=None,
        dry_run=False,
        run_date="2026-05-16",
    )
    with patch("prefilter.router.run_prefilter") as mock_run:
        _cmd_prefilter(args)

    mock_run.assert_called_once_with(
        input_path="data/raw/2026-05-16",
        remote_out="data/prefiltered/2026-05-16/remote_filter_input.jsonl",
        local_out="data/local/2026-05-16/local_jobs.jsonl",
        trash_out="data/trash/2026-05-16/prefilter_trash.jsonl",
        config_path="prefilter.yml",
        dry_run=False,
    )


def test_prefilter_cmd_explicit_paths_override_run_date():
    from job_scraper.cli import _cmd_prefilter

    args = _fake_args(
        input="custom/raw.jsonl",
        config="prefilter.yml",
        remote_out="custom/remote.jsonl",
        local_out="custom/local.jsonl",
        trash_out="custom/trash.jsonl",
        dry_run=False,
        run_date="2026-05-16",
    )
    with patch("prefilter.router.run_prefilter") as mock_run:
        _cmd_prefilter(args)

    mock_run.assert_called_once_with(
        input_path="custom/raw.jsonl",
        remote_out="custom/remote.jsonl",
        local_out="custom/local.jsonl",
        trash_out="custom/trash.jsonl",
        config_path="prefilter.yml",
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# remote-filter — --run-date flag and path resolution
# ---------------------------------------------------------------------------


def test_remote_filter_run_date_flag():
    args = _parse_args("remote-filter", "--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


def test_remote_filter_cmd_no_run_date_uses_legacy_defaults():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from job_scraper.cli import _cmd_remote_filter

    args = _fake_args(
        input=None,
        pass_output=None,
        trash_output=None,
        config="remote.yml",
        user_location="USA",
        user_timezone=None,
        run_date=None,
        cache_path=None,
        no_cache=False,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="data/prefiltered/remote_filter_input.jsonl",
        pass_path="data/filtered/remote_filter_pass.jsonl",
        trash_path="data/trash/remote_filter_trash.jsonl",
        config_path="remote.yml",
        user_location="USA",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
    )


def test_remote_filter_cmd_run_date_resolves_partitioned_paths():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from job_scraper.cli import _cmd_remote_filter

    args = _fake_args(
        input=None,
        pass_output=None,
        trash_output=None,
        config="remote.yml",
        user_location="USA",
        user_timezone=None,
        run_date="2026-05-16",
        cache_path=None,
        no_cache=False,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="data/prefiltered/2026-05-16",
        pass_path="data/filtered/2026-05-16/remote_filter_pass.jsonl",
        trash_path="data/trash/2026-05-16/remote_filter_trash.jsonl",
        config_path="remote.yml",
        user_location="USA",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
    )


def test_remote_filter_cmd_no_cache_flag_disables_cache():
    from job_scraper.cli import _cmd_remote_filter

    args = _fake_args(
        input="raw.jsonl",
        pass_output="pass.jsonl",
        trash_output="trash.jsonl",
        config="remote.yml",
        user_location="USA",
        user_timezone=None,
        run_date=None,
        cache_path=None,
        no_cache=True,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    assert mock_run.call_args.kwargs["cache_path"] is None


def test_remote_filter_cmd_explicit_paths_override_run_date():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from job_scraper.cli import _cmd_remote_filter

    args = _fake_args(
        input="custom/in.jsonl",
        pass_output="custom/pass.jsonl",
        trash_output="custom/trash.jsonl",
        config="remote.yml",
        user_location="USA",
        user_timezone=None,
        run_date="2026-05-16",
        cache_path=None,
        no_cache=False,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="custom/in.jsonl",
        pass_path="custom/pass.jsonl",
        trash_path="custom/trash.jsonl",
        config_path="remote.yml",
        user_location="USA",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
    )
