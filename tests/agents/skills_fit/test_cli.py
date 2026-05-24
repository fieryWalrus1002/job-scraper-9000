"""Tests for the skills-fit CLI module."""

import argparse
from unittest.mock import patch

import pytest

from jobs_cli.main import main


def _fake_args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _parse_args(*argv):
    captured = {}

    def capture(args):
        captured["args"] = args

    with patch("sys.argv", ["job-scraper-9000", "skills-fit", *argv]):
        with patch("agents.skills_fit.cli._cmd_skills_fit", side_effect=capture):
            main()

    return captured["args"]


def test_skills_fit_defaults():
    args = _parse_args()
    assert args.run_date is None
    assert args.config == "config/agent/skills_fit.yml"
    assert args.limit is None


def test_skills_fit_custom_args():
    args = _parse_args(
        "--run-date",
        "2026-05-23",
        "--config",
        "skills_fit.yml",
        "--limit",
        "5",
    )
    assert args.run_date == "2026-05-23"
    assert args.config == "skills_fit.yml"
    assert args.limit == 5


def test_skills_fit_cmd_calls_runner():
    from agents.skills_fit.cli import _cmd_skills_fit

    args = _fake_args(
        run_date="2026-05-23",
        config="skills_fit.yml",
        limit=5,
    )

    with patch("agents.skills_fit.runner.run_skills_fit") as mock_run:
        _cmd_skills_fit(args)

    mock_run.assert_called_once_with(
        run_date="2026-05-23",
        config_path="skills_fit.yml",
        limit=5,
    )


def test_skills_fit_cmd_returns_shell_friendly_exit_codes():
    from agents.skills_fit.cli import _cmd_skills_fit

    args = _fake_args(run_date="2026-05-23", config="skills_fit.yml", limit=None)

    with patch(
        "agents.skills_fit.runner.run_skills_fit",
        side_effect=ValueError("boom"),
    ):
        with pytest.raises(SystemExit) as exc:
            _cmd_skills_fit(args)
    assert exc.value.code == 1

    with patch(
        "agents.skills_fit.runner.run_skills_fit",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(SystemExit) as exc:
            _cmd_skills_fit(args)
    assert exc.value.code == 130
