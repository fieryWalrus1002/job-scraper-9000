"""
Tests for the remote_filter agent.

Coverage:
- passes_remote_filter: pure filter logic
- analyze_remote: LLM call with mocked OpenAI client
- _load_raw_jobs / _load_eval_records: file I/O helpers
- _highlight_phrases: ANSI highlight helper
- _cmd_export: converts eval suite to OpenAI fine-tuning JSONL
- _cmd_review: interactive review with mocked input()
"""
import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.remote_filter.cli import (
    _cmd_export,
    _cmd_review,
    _highlight_phrases,
    _load_eval_records,
    _load_raw_jobs,
)
from agents.remote_filter.models import RemoteAnalysis, UserPreferences
from agents.remote_filter.utils import passes_remote_filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analysis(**overrides) -> RemoteAnalysis:
    defaults = dict(
        remote_classification="fully_remote",
        estimated_travel_days_per_year=None,
        travel_description=None,
        location_restrictions=[],
        requires_relocation=False,
        requires_local_presence=False,
        confidence="high",
        reasoning="Explicitly states fully remote.",
    )
    return RemoteAnalysis(**{**defaults, **overrides})


def _make_prefs(**overrides) -> UserPreferences:
    defaults = dict(max_travel="quarterly", unclear_routing="pass", user_location="USA")
    return UserPreferences(**{**defaults, **overrides})


def _make_eval_record(**overrides) -> dict:
    defaults = dict(
        sample_id="job-001",
        title="Senior Engineer",
        company="Acme",
        description="This is a fully remote role. No travel required.",
        expected_classification="fully_remote",
        expected_should_pass_filter=True,
        expected_travel_days_range=None,
        key_phrases=[],
        notes="",
    )
    return {**defaults, **overrides}


def _make_filtered_job(**overrides) -> dict:
    defaults = dict(
        id="job-001",
        title="Senior Engineer",
        company="Acme",
        description="Fully remote, no travel.",
        job_url="https://example.com/job/1",
        _filter_result="trash",
        _filter_reason="classification:hybrid",
        _remote_analysis={
            "remote_classification": "hybrid",
            "confidence": "high",
            "travel_description": None,
            "estimated_travel_days_per_year": None,
            "location_restrictions": [],
            "requires_relocation": False,
            "requires_local_presence": False,
            "reasoning": "Hybrid role.",
            "key_phrases": [],
        },
    )
    return {**defaults, **overrides}


def _fake_args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _eval_records(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _run_review(tmp_path, jobs, input_sequence, bucket="trash", existing_eval=None):
    """Run _cmd_review with patched paths and mocked input, return eval path."""
    trash_path = tmp_path / "trash" / "remote_filter_trash.jsonl"
    pass_path = tmp_path / "filtered" / "remote_filter_pass.jsonl"
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    eval_path.parent.mkdir(parents=True, exist_ok=True)

    if existing_eval:
        _write_jsonl(eval_path, existing_eval)

    if bucket in ("trash", "all"):
        _write_jsonl(trash_path, jobs)
    if bucket == "pass":
        _write_jsonl(pass_path, jobs)

    inputs = iter(input_sequence)
    args = _fake_args(bucket=bucket)

    with patch("agents.remote_filter.cli.DATA_TRASH", tmp_path / "trash"):
        with patch("agents.remote_filter.cli.DATA_FILTERED", tmp_path / "filtered"):
            with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
                with patch("builtins.input", side_effect=lambda _: next(inputs)):
                    _cmd_review(args)

    return eval_path


# ---------------------------------------------------------------------------
# passes_remote_filter
# ---------------------------------------------------------------------------

def test_fully_remote_passes():
    ok, reason = passes_remote_filter(_make_analysis(), _make_prefs())
    assert ok
    assert reason == "passed"


def test_hybrid_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="hybrid"), _make_prefs()
    )
    assert not ok
    assert "hybrid" in reason


def test_onsite_disguised_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="onsite_disguised"), _make_prefs()
    )
    assert not ok
    assert "onsite_disguised" in reason


def test_requires_relocation_fails():
    ok, reason = passes_remote_filter(_make_analysis(requires_relocation=True), _make_prefs())
    assert not ok
    assert reason == "requires_relocation"


def test_requires_local_presence_fails():
    ok, reason = passes_remote_filter(_make_analysis(requires_local_presence=True), _make_prefs())
    assert not ok
    assert reason == "requires_local_presence"


def test_frequent_travel_always_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="remote_with_frequent_travel"), _make_prefs()
    )
    assert not ok
    assert reason == "travel_too_frequent"


def test_monthly_travel_fails_when_max_quarterly():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="remote_with_monthly_travel"),
        _make_prefs(max_travel="quarterly"),
    )
    assert not ok
    assert reason == "travel_more_than_quarterly"


def test_monthly_travel_passes_when_max_monthly():
    ok, _ = passes_remote_filter(
        _make_analysis(remote_classification="remote_with_monthly_travel"),
        _make_prefs(max_travel="monthly"),
    )
    assert ok


def test_quarterly_travel_passes_when_max_quarterly():
    ok, _ = passes_remote_filter(
        _make_analysis(remote_classification="remote_with_quarterly_travel"),
        _make_prefs(max_travel="quarterly"),
    )
    assert ok


def test_unclear_passes_by_default():
    ok, _ = passes_remote_filter(_make_analysis(remote_classification="unclear"), _make_prefs())
    assert ok


def test_unclear_fails_when_routing_reject():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="unclear"),
        _make_prefs(unclear_routing="reject"),
    )
    assert not ok
    assert reason == "agent_uncertain"


def test_us_only_restriction_passes_for_usa():
    ok, _ = passes_remote_filter(
        _make_analysis(location_restrictions=["US-only"]),
        _make_prefs(user_location="USA"),
    )
    assert ok


def test_us_only_restriction_fails_for_non_us():
    ok, reason = passes_remote_filter(
        _make_analysis(location_restrictions=["US-only"]),
        _make_prefs(user_location="Canada"),
    )
    assert not ok
    assert reason == "location_restrictions_mismatch"


def test_relocation_check_takes_priority_over_classification():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="fully_remote", requires_relocation=True),
        _make_prefs(),
    )
    assert not ok
    assert reason == "requires_relocation"


# ---------------------------------------------------------------------------
# analyze_remote
# ---------------------------------------------------------------------------

def test_analyze_remote_returns_analysis_on_success():
    from agents.remote_filter.utils import analyze_remote

    mock_analysis = _make_analysis()
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = mock_analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.return_value = mock_response

    with patch("agents.remote_filter.utils._get_client", return_value=(mock_client, "gpt-4o-mini")):
        result = analyze_remote("We are a fully remote company.")

    assert result is not None
    assert result.remote_classification == "fully_remote"


def test_analyze_remote_returns_none_after_all_retries_fail():
    from agents.remote_filter.utils import analyze_remote

    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = Exception("API error")

    with patch("agents.remote_filter.utils._get_client", return_value=(mock_client, "gpt-4o-mini")):
        result = analyze_remote("Some job description.", max_retries=0)

    assert result is None


def test_analyze_remote_retries_on_failure():
    from agents.remote_filter.utils import analyze_remote

    mock_analysis = _make_analysis()
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = mock_analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = [
        Exception("transient error"),
        mock_response,
    ]

    with patch("agents.remote_filter.utils._get_client", return_value=(mock_client, "gpt-4o-mini")):
        result = analyze_remote("Some job description.", max_retries=1)

    assert result is not None
    assert mock_client.beta.chat.completions.parse.call_count == 2


# ---------------------------------------------------------------------------
# _load_raw_jobs
# ---------------------------------------------------------------------------

def test_load_raw_jobs_from_file(tmp_path):
    jobs = [{"id": "1", "title": "Dev"}, {"id": "2", "title": "Eng"}]
    f = tmp_path / "jobs.jsonl"
    _write_jsonl(f, jobs)
    result = _load_raw_jobs(f)
    assert len(result) == 2
    assert result[0]["title"] == "Dev"


def test_load_raw_jobs_from_directory(tmp_path):
    _write_jsonl(tmp_path / "a.jsonl", [{"id": "1"}])
    _write_jsonl(tmp_path / "b.jsonl", [{"id": "2"}])
    result = _load_raw_jobs(tmp_path)
    assert len(result) == 2


def test_load_raw_jobs_skips_blank_lines(tmp_path):
    f = tmp_path / "jobs.jsonl"
    f.write_text(json.dumps({"id": "1"}) + "\n\n" + json.dumps({"id": "2"}) + "\n")
    result = _load_raw_jobs(f)
    assert len(result) == 2


def test_load_raw_jobs_directory_sorted(tmp_path):
    _write_jsonl(tmp_path / "b.jsonl", [{"id": "b"}])
    _write_jsonl(tmp_path / "a.jsonl", [{"id": "a"}])
    result = _load_raw_jobs(tmp_path)
    assert result[0]["id"] == "a"
    assert result[1]["id"] == "b"


# ---------------------------------------------------------------------------
# _load_eval_records
# ---------------------------------------------------------------------------

def test_load_eval_records_missing_file_returns_empty(tmp_path):
    result = _load_eval_records(tmp_path / "nonexistent.jsonl")
    assert result == set()


def test_load_eval_records_returns_sample_ids(tmp_path):
    f = tmp_path / "eval.jsonl"
    _write_jsonl(f, [{"sample_id": "job-001"}, {"sample_id": "job-002"}])
    result = _load_eval_records(f)
    assert result == {"job-001", "job-002"}


def test_load_eval_records_skips_blank_lines(tmp_path):
    f = tmp_path / "eval.jsonl"
    f.write_text(json.dumps({"sample_id": "job-001"}) + "\n\n")
    result = _load_eval_records(f)
    assert result == {"job-001"}


# ---------------------------------------------------------------------------
# _cmd_export
# ---------------------------------------------------------------------------

def test_export_writes_openai_format(tmp_path):
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, [_make_eval_record()])

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    assert out_path.exists()
    record = json.loads(out_path.read_text().strip())
    messages = record["messages"]
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"


def test_export_user_content_is_description(tmp_path):
    desc = "Join our fully distributed team. All remote, no travel."
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, [_make_eval_record(description=desc)])

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    record = json.loads(out_path.read_text().strip())
    assert record["messages"][1]["content"] == desc


def test_export_assistant_content_is_valid_json(tmp_path):
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, [_make_eval_record()])

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    record = json.loads(out_path.read_text().strip())
    assistant = json.loads(record["messages"][2]["content"])
    assert assistant["remote_classification"] == "fully_remote"
    assert assistant["confidence"] == "high"


def test_export_travel_range_uses_midpoint(tmp_path):
    rec = _make_eval_record(
        expected_travel_days_range=[4, 12],
        expected_classification="remote_with_quarterly_travel",
    )
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, [rec])

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    assistant = json.loads(json.loads(out_path.read_text().strip())["messages"][2]["content"])
    assert assistant["estimated_travel_days_per_year"] == 8  # (4 + 12) // 2


def test_export_skips_records_without_description(tmp_path):
    records = [
        _make_eval_record(sample_id="job-001", description="Real description here."),
        _make_eval_record(sample_id="job-002", description=""),
    ]
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, records)

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
    assert len(lines) == 1


def test_export_writes_one_example_per_record(tmp_path):
    records = [_make_eval_record(sample_id=f"job-{i}") for i in range(5)]
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, records)

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
    assert len(lines) == 5


def test_export_exits_when_no_eval_file(tmp_path):
    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        with pytest.raises(SystemExit):
            _cmd_export(_fake_args())


# ---------------------------------------------------------------------------
# _cmd_review
# ---------------------------------------------------------------------------

def test_review_keep_does_not_write_eval(tmp_path):
    eval_path = _run_review(tmp_path, [_make_filtered_job()], input_sequence=["k"])
    assert _eval_records(eval_path) == []


def test_review_skip_does_not_write_eval(tmp_path):
    eval_path = _run_review(tmp_path, [_make_filtered_job()], input_sequence=["s"])
    assert _eval_records(eval_path) == []


def test_review_quit_stops_early(tmp_path):
    jobs = [_make_filtered_job(id=f"job-{i}") for i in range(3)]
    eval_path = _run_review(tmp_path, jobs, input_sequence=["q"])
    assert _eval_records(eval_path) == []


def test_review_flip_writes_eval_record(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job(id="job-flip")],
        input_sequence=["f", "", "", ""],  # flip → cls (enter) → phrases (blank) → notes
    )
    assert eval_path.exists()
    record = json.loads(eval_path.read_text().strip())
    assert record["sample_id"] == "job-flip"


def test_review_flip_trash_sets_should_pass_true(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job(_filter_result="trash")],
        input_sequence=["f", "", "", ""],
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["expected_should_pass_filter"] is True


def test_review_flip_pass_sets_should_pass_false(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job(id="job-pass", _filter_result="pass")],
        input_sequence=["f", "", "", ""],
        bucket="pass",
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["expected_should_pass_filter"] is False


def test_review_flip_custom_classification(tmp_path):
    # _CLASSIFICATIONS[0] is "fully_remote"; user types "1"
    eval_path = _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["f", "1", "", ""],
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["expected_classification"] == "fully_remote"


def test_review_flip_enter_keeps_agent_classification(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["f", "", "", ""],  # agent said "hybrid"
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["expected_classification"] == "hybrid"


def test_review_flip_notes_saved(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["f", "", "", "wrong timezone check"],
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["notes"] == "wrong timezone check"


def test_review_flip_key_phrases_saved(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["f", "", "must be in office 3 days, hybrid schedule", ""],
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["key_phrases"] == ["must be in office 3 days", "hybrid schedule"]


def test_review_flip_blank_phrases_saves_empty_list(tmp_path):
    eval_path = _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["f", "", "", ""],
    )
    record = json.loads(eval_path.read_text().strip())
    assert record["key_phrases"] == []


def test_review_d_prints_description_then_continues(tmp_path, capsys):
    _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["d", "k"],
    )
    assert "Fully remote, no travel." in capsys.readouterr().out


def test_review_skips_duplicate_already_in_eval(tmp_path, capsys):
    existing = [{"sample_id": "already-labeled"}]
    eval_path = _run_review(
        tmp_path,
        [_make_filtered_job(id="already-labeled")],
        input_sequence=["f"],  # duplicate detected before asking for more input
        existing_eval=existing,
    )
    lines = [ln for ln in eval_path.read_text().strip().splitlines() if ln]
    assert len(lines) == 1  # only the pre-existing record
    assert "already in eval suite" in capsys.readouterr().out


def test_review_invalid_key_reprompts(tmp_path):
    # "x" is invalid → reprompt → "k" is valid
    _run_review(
        tmp_path, [_make_filtered_job()],
        input_sequence=["x", "k"],
    )


# ---------------------------------------------------------------------------
# _highlight_phrases
# ---------------------------------------------------------------------------

def test_highlight_phrases_wraps_match():
    result = _highlight_phrases("This is a fully remote role.", ["fully remote"])
    assert "fully remote" in result
    assert "\033[" in result  # ANSI escape present


def test_highlight_phrases_multiple_phrases():
    text = "Remote role. No travel required."
    result = _highlight_phrases(text, ["Remote role", "No travel"])
    assert result.count("\033[") >= 2


def test_highlight_phrases_no_match_returns_unchanged():
    text = "Some job description."
    result = _highlight_phrases(text, ["office required"])
    assert result == text


def test_highlight_phrases_empty_list_returns_unchanged():
    text = "Some job description."
    assert _highlight_phrases(text, []) == text


def test_highlight_phrases_skips_empty_string_phrase():
    text = "Some job description."
    assert _highlight_phrases(text, [""]) == text


# ---------------------------------------------------------------------------
# _cmd_export — key_phrases passthrough
# ---------------------------------------------------------------------------

def test_export_key_phrases_included_in_assistant_content(tmp_path):
    rec = _make_eval_record(key_phrases=["fully remote", "no travel required"])
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, [rec])

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    assistant = json.loads(json.loads(out_path.read_text().strip())["messages"][2]["content"])
    assert assistant["key_phrases"] == ["fully remote", "no travel required"]


def test_export_key_phrases_defaults_to_empty_list(tmp_path):
    rec = _make_eval_record()  # key_phrases=[]
    eval_path = tmp_path / "eval" / "remote_filter_eval.jsonl"
    _write_jsonl(eval_path, [rec])

    with patch("agents.remote_filter.cli.DATA_EVAL", tmp_path / "eval"):
        _cmd_export(_fake_args())

    out_path = tmp_path / "eval" / "remote_filter_finetune.jsonl"
    assistant = json.loads(json.loads(out_path.read_text().strip())["messages"][2]["content"])
    assert assistant["key_phrases"] == []
