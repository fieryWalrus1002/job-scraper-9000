"""Tests for remote_filter core logic: analyze_remote and passes_remote_filter."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.utils import (
    _build_user_message,
    analyze_remote,
    load_raw_jobs,
    passes_remote_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_analysis(**overrides) -> RemoteAnalysis:
    defaults = dict(
        reasoning_trace="Explicitly states remote.",
        remote_classification="remote",
        estimated_travel_days_per_year=None,
        location_restrictions=[],
        requires_relocation=False,
        requires_local_presence=False,
        timezone_requirements=[],
    )
    return RemoteAnalysis(**{**defaults, **overrides})


def _make_config(
    disallowed_classifications=None,
    max_days=15,
    allow_relocation=False,
    allow_local_presence=False,
    on_unclear="pass",
    rejected_timezone_keywords=None,
) -> dict:
    return {
        "policy_thresholds": {
            "disallowed_classifications": disallowed_classifications
            or ["hybrid", "onsite"],
            "travel": {
                "max_estimated_days_per_year": max_days,
            },
            "relocation": {
                "allow_required_relocation": allow_relocation,
                "allow_local_presence_required": allow_local_presence,
            },
            "uncertainty": {
                "on_unclear_classification": on_unclear,
            },
            "timezone": {
                "user_timezone": "PST",
                "rejected_timezone_keywords": rejected_timezone_keywords
                or ["EST", "ET", "Eastern"],
            },
        }
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# passes_remote_filter
# ---------------------------------------------------------------------------


def test_remote_passes():
    ok, reason = passes_remote_filter(_make_analysis(), _make_config())
    assert ok
    assert reason == "passed"


def test_hybrid_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="hybrid"), _make_config()
    )
    assert not ok
    assert "hybrid" in reason


def test_onsite_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="onsite"), _make_config()
    )
    assert not ok
    assert "onsite" in reason


def test_requires_relocation_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(requires_relocation=True), _make_config()
    )
    assert not ok
    assert reason == "requires_relocation"


def test_requires_local_presence_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(requires_local_presence=True), _make_config()
    )
    assert not ok
    assert reason == "requires_local_presence"


# Travel is gated solely on the numeric estimate as of SCHEMA_VERSION 4.0.0.
# A frequent-travel posting is now a remote role with a high day count,
# trashed by the day threshold rather than a classification bucket.
def test_frequent_travel_fails_via_day_threshold():
    ok, reason = passes_remote_filter(
        _make_analysis(
            remote_classification="remote",
            estimated_travel_days_per_year=40,
        ),
        _make_config(),
    )
    assert not ok
    assert "travel_days_exceeded" in reason


def test_monthly_travel_passes_under_threshold():
    ok, _ = passes_remote_filter(
        _make_analysis(
            remote_classification="remote",
            estimated_travel_days_per_year=12,
        ),
        _make_config(),
    )
    assert ok


def test_quarterly_travel_passes():
    ok, _ = passes_remote_filter(
        _make_analysis(
            remote_classification="remote",
            estimated_travel_days_per_year=4,
        ),
        _make_config(),
    )
    assert ok


def test_unclear_passes_when_allowed():
    ok, _ = passes_remote_filter(
        _make_analysis(remote_classification="unclear"),
        _make_config(on_unclear="pass"),
    )
    assert ok


def test_unclear_fails_when_rejected():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="unclear"),
        _make_config(on_unclear="reject"),
    )
    assert not ok
    assert reason == "agent_uncertain"


def test_us_only_passes_for_usa():
    ok, _ = passes_remote_filter(
        _make_analysis(location_restrictions=["US-only"]),
        _make_config(),
        user_location="USA",
    )
    assert ok


def test_us_only_fails_for_non_us():
    ok, reason = passes_remote_filter(
        _make_analysis(location_restrictions=["US-only"]),
        _make_config(),
        user_location="Canada",
    )
    assert not ok
    assert reason == "location_restrictions_mismatch"


def test_remote_with_location_restriction_passes_for_matching_user_location():
    ok, _ = passes_remote_filter(
        _make_analysis(
            remote_classification="remote",
            location_restrictions=["US-only"],
        ),
        _make_config(),
        user_location="USA",
    )
    assert ok


def test_remote_with_location_restriction_fails_for_non_matching_user_location():
    ok, reason = passes_remote_filter(
        _make_analysis(
            remote_classification="remote",
            location_restrictions=["US-only"],
        ),
        _make_config(),
        user_location="Canada",
    )
    assert not ok
    assert reason == "location_restrictions_mismatch"


def test_eastern_timezone_requirement_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(timezone_requirements=["EST"]),
        _make_config(),
    )
    assert not ok
    assert "timezone_mismatch" in reason


def test_eastern_timezone_full_phrase_fails():
    ok, reason = passes_remote_filter(
        _make_analysis(timezone_requirements=["Eastern time zone"]),
        _make_config(),
    )
    assert not ok
    assert "timezone_mismatch" in reason


def test_pacific_timezone_requirement_passes():
    ok, _ = passes_remote_filter(
        _make_analysis(timezone_requirements=["PST"]),
        _make_config(),
    )
    assert ok


def test_no_timezone_requirement_passes():
    ok, _ = passes_remote_filter(
        _make_analysis(timezone_requirements=[]),
        _make_config(),
    )
    assert ok


def test_relocation_check_takes_priority_over_classification():
    ok, reason = passes_remote_filter(
        _make_analysis(remote_classification="remote", requires_relocation=True),
        _make_config(),
    )
    assert not ok
    assert reason == "requires_relocation"


def test_travel_days_exceeded():
    ok, reason = passes_remote_filter(
        _make_analysis(estimated_travel_days_per_year=30),
        _make_config(max_days=15),
    )
    assert not ok
    assert "travel_days_exceeded" in reason


# ---------------------------------------------------------------------------
# analyze_remote
# ---------------------------------------------------------------------------


def test_analyze_remote_returns_analysis_on_success():
    mock_analysis = _make_analysis()
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = mock_analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.return_value = mock_response

    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        result = analyze_remote("We are a fully remote company.")

    assert result is not None
    assert result.remote_classification == "remote"


def test_analyze_remote_returns_none_after_all_retries_fail():
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = Exception("API error")

    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        result = analyze_remote("Some job description.", max_retries=0)

    assert result is None


def test_analyze_remote_injects_search_context():
    mock_analysis = _make_analysis()
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = mock_analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.return_value = mock_response

    context = {"keywords": "AI engineer", "workplace": "remote", "job_type": "fulltime"}
    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        analyze_remote("Job description here.", search_context=context)

    call_messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
    user_content = call_messages[1]["content"]
    assert "[Search context:" in user_content
    assert 'keywords="AI engineer"' in user_content
    assert "workplace_filter=remote" in user_content
    assert "Job description here." in user_content


def test_analyze_remote_no_context_sends_description_only():
    mock_analysis = _make_analysis()
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = mock_analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.return_value = mock_response

    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        analyze_remote("Plain description.", search_context=None)

    call_messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
    assert call_messages[1]["content"] == "Plain description."


def test_analyze_remote_retries_on_failure():
    mock_analysis = _make_analysis()
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = mock_analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = [
        Exception("transient error"),
        mock_response,
    ]

    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        result = analyze_remote("Some job description.", max_retries=1)

    assert result is not None
    assert mock_client.beta.chat.completions.parse.call_count == 2


# ---------------------------------------------------------------------------
# load_raw_jobs
# ---------------------------------------------------------------------------


def test_load_raw_jobs_from_file(tmp_path):
    f = tmp_path / "jobs.jsonl"
    _write_jsonl(f, [{"id": "1", "title": "Dev"}, {"id": "2", "title": "Eng"}])
    result = load_raw_jobs(f)
    assert len(result) == 2
    assert result[0]["title"] == "Dev"


def test_load_raw_jobs_from_directory(tmp_path):
    _write_jsonl(tmp_path / "a.jsonl", [{"id": "1"}])
    _write_jsonl(tmp_path / "b.jsonl", [{"id": "2"}])
    result = load_raw_jobs(tmp_path)
    assert len(result) == 2


def test_load_raw_jobs_skips_blank_lines(tmp_path):
    f = tmp_path / "jobs.jsonl"
    f.write_text(json.dumps({"id": "1"}) + "\n\n" + json.dumps({"id": "2"}) + "\n")
    result = load_raw_jobs(f)
    assert len(result) == 2


def test_load_raw_jobs_directory_sorted(tmp_path):
    _write_jsonl(tmp_path / "b.jsonl", [{"id": "b"}])
    _write_jsonl(tmp_path / "a.jsonl", [{"id": "a"}])
    result = load_raw_jobs(tmp_path)
    assert result[0]["id"] == "a"
    assert result[1]["id"] == "b"


# ---------------------------------------------------------------------------
# _build_user_message — title and location injection
# ---------------------------------------------------------------------------


def test_build_user_message_no_extras_returns_description_only():
    assert _build_user_message("Just a description.", None) == "Just a description."


def test_build_user_message_title_prepended():
    msg = _build_user_message("Job desc.", None, title="Personal Office Assistant")
    assert "[Job title: Personal Office Assistant]" in msg
    assert "Job desc." in msg


def test_build_user_message_location_prepended():
    msg = _build_user_message(
        "Job desc.", None, location="US-Remote (35 miles+ outside an office)"
    )
    assert "[Location field: US-Remote (35 miles+ outside an office)]" in msg
    assert "Job desc." in msg


def test_build_user_message_title_before_location():
    msg = _build_user_message("Desc.", None, title="Engineer", location="Remote")
    title_pos = msg.index("[Job title:")
    location_pos = msg.index("[Location field:")
    assert title_pos < location_pos


def test_build_user_message_all_fields_combined():
    ctx = {"keywords": "AI engineer", "workplace": "remote"}
    msg = _build_user_message("Desc.", ctx, title="AI Engineer", location="US-Remote")
    assert "[Job title: AI Engineer]" in msg
    assert "[Location field: US-Remote]" in msg
    assert "[Search context:" in msg
    assert "Desc." in msg


def test_build_user_message_none_title_and_location_with_context():
    ctx = {"keywords": "data engineer"}
    msg = _build_user_message("Desc.", ctx, title=None, location=None)
    assert "[Search context:" in msg
    assert "Job title" not in msg
    assert "Location field" not in msg


def test_build_user_message_explains_remote_search_provenance_for_ddc_case():
    ctx = {
        "search_contexts": [
            {
                "source": "workday",
                "workplace": "remote",
                "job_type": "fulltime",
                "source_detail_location": "Remote; Washington, DC",
            }
        ]
    }
    msg = _build_user_message(
        "Ambiguous body text with no remote wording.",
        ctx,
        title="Data Engineer",
        location="Remote; Washington, DC",
    )

    assert "returned by a remote-only search filter" in msg
    assert "weak but relevant evidence of remote eligibility" in msg
    assert "full-time search filter" in msg
    assert "Remote; Washington, DC" in msg


# ---------------------------------------------------------------------------
# analyze_remote — title and location threaded through
# ---------------------------------------------------------------------------


def _mock_client_returning(analysis: RemoteAnalysis):
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = analysis
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.return_value = mock_response
    return mock_client


def test_analyze_remote_includes_title_in_user_message():
    mock_client = _mock_client_returning(_make_analysis())
    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        analyze_remote("Job description.", title="Personal Office Assistant")
    user_content = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"][
        1
    ]["content"]
    assert "[Job title: Personal Office Assistant]" in user_content


def test_analyze_remote_includes_location_in_user_message():
    mock_client = _mock_client_returning(_make_analysis())
    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        analyze_remote(
            "Job description.", location="US-Remote (35 miles+ outside an office)"
        )
    user_content = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"][
        1
    ]["content"]
    assert "[Location field: US-Remote (35 miles+ outside an office)]" in user_content


def test_analyze_remote_no_title_no_location_sends_description_only():
    mock_client = _mock_client_returning(_make_analysis())
    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        analyze_remote(
            "Plain description.", title=None, location=None, search_context=None
        )
    user_content = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"][
        1
    ]["content"]
    assert user_content == "Plain description."


# ---------------------------------------------------------------------------
# remote-filter CLI — argument parsing and command handler
# ---------------------------------------------------------------------------


import argparse as _argparse  # noqa: E402


from jobs_cli.main import main  # noqa: E402


def _cli_fake_args(**kwargs) -> _argparse.Namespace:
    return _argparse.Namespace(**kwargs)


def _cli_parse_args(*argv):
    captured = {}

    def capture(args):
        captured["args"] = args

    with patch("sys.argv", ["job-scraper-9000", "remote-filter", *argv]):
        with patch("agents.remote_filter.cli._cmd_remote_filter", side_effect=capture):
            main()

    return captured["args"]


def test_remote_filter_defaults():
    import os

    with patch.dict(os.environ, {}, clear=True):
        with patch("jobs_cli.main.load_dotenv"):
            args = _cli_parse_args()
    assert args.input is None
    assert args.run_date is None
    assert args.pass_output is None
    assert args.trash_output is None
    assert args.config == "config/agent/remote_agent.yml"
    assert args.user_location == "USA"
    assert args.user_timezone is None


def test_remote_filter_custom_paths():
    args = _cli_parse_args(
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


def test_remote_filter_run_date_flag():
    args = _cli_parse_args("--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


def test_remote_filter_cmd_calls_runner():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input="raw.jsonl",
        pass_output="pass.jsonl",
        trash_output="trash.jsonl",
        config="remote.yml",
        user_location="USA",
        user_timezone="PST",
        cache_path=None,
        no_cache=False,
        run_date=None,
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


def test_remote_filter_cmd_no_run_date_uses_legacy_defaults():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
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
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
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
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
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
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
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


def test_remote_filter_cmd_batch_flag_routes_to_batch_runner():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input="raw.jsonl",
        pass_output="pass.jsonl",
        trash_output="trash.jsonl",
        config="remote.yml",
        user_location="USA",
        user_timezone=None,
        run_date=None,
        cache_path=None,
        no_cache=False,
        batch=True,
        poll_interval=30,
    )

    with (
        patch("agents.remote_filter.batch.run_remote_filter_batch") as mock_batch,
        patch("agents.remote_filter.runner.run_remote_filter") as mock_serial,
    ):
        _cmd_remote_filter(args)

    mock_serial.assert_not_called()
    mock_batch.assert_called_once_with(
        input_path="raw.jsonl",
        pass_path="pass.jsonl",
        trash_path="trash.jsonl",
        config_path="remote.yml",
        user_location="USA",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
        poll_interval=30,
    )
