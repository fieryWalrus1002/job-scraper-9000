"""Tests for the ``overnight --batch`` toggle.

The flag swaps the classification + scoring hooks onto their OpenAI Batch API
twins (``batch_classify_fn`` / ``batch_score_fn``); the default invocation
keeps the live-call fns. The batch runners themselves are faked here — their
plumbing has its own tests — so nothing touches the network.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pipeline.overnight as overnight
from pipeline.consolidation import batch_classify_fn, default_classify_fn
from pipeline.scoring import batch_score_fn, default_score_fn


# ---------------------------------------------------------------------------
# The batch twins forward the hook kwargs to the batch runners
# ---------------------------------------------------------------------------


def test_batch_classify_fn_forwards_hook_kwargs(monkeypatch):
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"pass": 1}

    monkeypatch.setattr("agents.remote_filter.batch.run_remote_filter_batch", fake)

    result = batch_classify_fn(
        input_path=Path("in.jsonl"),
        pass_path=Path("pass.jsonl"),
        trash_path=Path("trash.jsonl"),
        parent_run_id="run-1",
    )

    assert result == {"pass": 1}
    assert calls == [
        {
            "input_path": Path("in.jsonl"),
            "pass_path": Path("pass.jsonl"),
            "trash_path": Path("trash.jsonl"),
            "parent_run_id": "run-1",
        }
    ]


def test_batch_score_fn_maps_hook_kwargs_to_runner_names(monkeypatch):
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"scored_successfully": 2}

    monkeypatch.setattr("agents.skills_fit.batch.run_skills_fit_batch", fake)

    result = batch_score_fn(
        input_path=Path("gated.jsonl"),
        output_path=Path("scored.jsonl"),
        profile_file=Path("candidate_profile.yml"),
        run_date="2026-07-08",
        parent_run_id="run-1",
    )

    assert result == {"scored_successfully": 2}
    assert calls == [
        {
            "run_date": "2026-07-08",
            "remote_input": Path("gated.jsonl"),
            "output": Path("scored.jsonl"),
            "profile_file": Path("candidate_profile.yml"),
            "parent_run_id": "run-1",
        }
    ]


# ---------------------------------------------------------------------------
# CLI routing: --batch swaps both hooks; the default passes neither
# ---------------------------------------------------------------------------

_OK_SUMMARY = {"run_summary": {"text": "ok", "all_failed": False, "users_failed": 0}}


def _run_cli(monkeypatch, argv: list[str]) -> dict:
    """Parse ``argv`` with the real overnight parser and run its command with
    ``run_overnight`` faked out; returns the kwargs it was invoked with."""
    captured: dict = {}

    def fake_run_overnight(**kwargs):
        captured.update(kwargs)
        return _OK_SUMMARY

    monkeypatch.setattr(overnight, "run_overnight", fake_run_overnight)
    # Leave pytest's signal handlers alone.
    monkeypatch.setattr(overnight, "_install_interrupt_handlers", lambda: None)

    parser = argparse.ArgumentParser()
    overnight.register(parser.add_subparsers())
    args = parser.parse_args(argv)
    args.func(args)
    return captured


_BASE_ARGV = ["overnight", "--run-date", "2026-07-08", "--no-log-file"]


def test_cli_default_uses_live_call_fns(monkeypatch):
    captured = _run_cli(monkeypatch, _BASE_ARGV)
    assert captured.get("classify_fn", default_classify_fn) is default_classify_fn
    assert captured.get("score_fn", default_score_fn) is default_score_fn


def test_cli_batch_flag_swaps_in_batch_fns(monkeypatch):
    captured = _run_cli(monkeypatch, [*_BASE_ARGV, "--batch"])
    assert captured["classify_fn"] is batch_classify_fn
    assert captured["score_fn"] is batch_score_fn
