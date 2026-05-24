"""Tests for the prefilter CLI module."""

import argparse
from unittest.mock import patch

from jobs_cli.main import main


def _fake_args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _parse_args(*argv):
    """Run the umbrella with prefilter argv, capture the Namespace via the handler."""
    captured = {}

    def capture(args):
        captured["args"] = args

    with patch("sys.argv", ["job-scraper-9000", "prefilter", *argv]):
        with patch("prefilter.cli._cmd_prefilter", side_effect=capture):
            main()

    return captured["args"]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_prefilter_defaults():
    args = _parse_args()
    assert args.input is None
    assert args.run_date is None
    assert args.config == "config/agent/prefilter.yml"
    assert args.remote_out is None
    assert args.local_out is None
    assert args.trash_out is None
    assert args.dry_run is False


def test_prefilter_custom_paths():
    args = _parse_args(
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


def test_prefilter_run_date_flag():
    args = _parse_args("--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


def test_prefilter_cmd_calls_runner():
    from prefilter.cli import _cmd_prefilter

    args = _fake_args(
        input="raw.jsonl",
        config="prefilter.yml",
        remote_out="remote.jsonl",
        local_out="local.jsonl",
        trash_out="trash.jsonl",
        dry_run=True,
        run_date=None,
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


def test_prefilter_cmd_no_run_date_uses_legacy_defaults():
    from prefilter.cli import _cmd_prefilter

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
    from prefilter.cli import _cmd_prefilter

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
    from prefilter.cli import _cmd_prefilter

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
