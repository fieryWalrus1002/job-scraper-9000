"""Tests for shared CLI helpers in jobs_cli._common."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from jobs_cli._common import (
    DATA_DIR,
    _auto_path,
    _output,
    _parse_positive_int,
    _parse_run_date,
    _resolve_dest,
    _slug,
)
from job_scraper.models import JobPosting


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
    with patch("jobs_cli._common.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-11_10-30"
        p = _auto_path("linkedin", "LLM Ops")

    assert p == DATA_DIR / "2026-05-11_10-30_linkedin_llm-ops.jsonl"


def test_auto_path_slugifies_keywords():
    with patch("jobs_cli._common.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-11_10-30"
        p = _auto_path("jobspy", "Data Engineer (Senior)")

    assert p.name == "2026-05-11_10-30_jobspy_data-engineer-senior.jsonl"


def test_auto_path_with_run_date_uses_dated_partition():
    with patch("jobs_cli._common.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-16_09-00"
        p = _auto_path("linkedin", "LLM Ops", run_date="2026-05-16")

    assert p == DATA_DIR / "2026-05-16" / "2026-05-16_09-00_linkedin_llm-ops.jsonl"


# ---------------------------------------------------------------------------
# _parse_run_date / _parse_positive_int
# ---------------------------------------------------------------------------


def test_parse_run_date_accepts_valid_date():
    assert _parse_run_date("2026-05-19") == "2026-05-19"


def test_parse_run_date_rejects_invalid_format():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_run_date("19-05-2026")


def test_parse_run_date_rejects_path_traversal():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_run_date("../../etc/passwd")


def test_parse_positive_int_rejects_zero():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_positive_int("0")


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
    with patch("jobs_cli._common.DATA_DIR", tmp_path):
        with patch("jobs_cli._common.datetime") as mock_dt:
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
