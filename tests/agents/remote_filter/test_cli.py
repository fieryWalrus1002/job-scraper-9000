"""Tests for remote_filter core logic."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.remote_filter.input_models import RemoteFilterInput
from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.utils import (
    _build_user_message,
    analyze_remote,
    load_raw_jobs,
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


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


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

    context = RemoteFilterInput(
        description="Job description here.",
        keywords="AI engineer",
        workplace="remote",
        job_type="fulltime",
    )
    with patch(
        "agents.remote_filter.utils._get_client",
        return_value=(mock_client, "gpt-4o-mini"),
    ):
        analyze_remote(context)

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
    assert (
        _build_user_message(RemoteFilterInput(description="Just a description."))
        == "Just a description."
    )


def test_build_user_message_title_prepended():
    msg = _build_user_message(
        RemoteFilterInput(description="Job desc.", title="Personal Office Assistant")
    )
    assert "[Job title: Personal Office Assistant]" in msg
    assert "Job desc." in msg


def test_build_user_message_location_prepended():
    msg = _build_user_message(
        RemoteFilterInput(
            description="Job desc.",
            location="US-Remote (35 miles+ outside an office)",
        )
    )
    assert "[Location field: US-Remote (35 miles+ outside an office)]" in msg
    assert "Job desc." in msg


def test_build_user_message_title_before_location():
    msg = _build_user_message(
        RemoteFilterInput(description="Desc.", title="Engineer", location="Remote")
    )
    title_pos = msg.index("[Job title:")
    location_pos = msg.index("[Location field:")
    assert title_pos < location_pos


def test_build_user_message_all_fields_combined():
    msg = _build_user_message(
        RemoteFilterInput(
            description="Desc.",
            title="AI Engineer",
            location="US-Remote",
            keywords="AI engineer",
            workplace="remote",
        )
    )
    assert "[Job title: AI Engineer]" in msg
    assert "[Location field: US-Remote]" in msg
    assert "[Search context:" in msg
    assert "Desc." in msg


def test_build_user_message_none_title_and_location_with_context():
    msg = _build_user_message(
        RemoteFilterInput(description="Desc.", keywords="data engineer")
    )
    assert "[Search context:" in msg
    assert "Job title" not in msg
    assert "Location field" not in msg


def test_build_user_message_explains_remote_search_provenance_for_ddc_case():
    rf_input = RemoteFilterInput(
        description="Ambiguous body text with no remote wording.",
        title="Data Engineer",
        location="Remote; Washington, DC",
        search_contexts=[
            {
                "source": "workday",
                "workplace": "remote",
                "job_type": "fulltime",
                "source_detail_location": "Remote; Washington, DC",
            }
        ],
    )
    msg = _build_user_message(rf_input)

    assert "returned by a remote-only search filter" in msg
    assert "weak but relevant evidence of remote eligibility" in msg
    assert "full-time search filter" in msg
    assert "Remote; Washington, DC" in msg


def test_build_user_message_golden_ddc_remote_provenance_case():
    rf_input = RemoteFilterInput(
        description="Ambiguous body text with no remote wording.",
        title="Data Engineer",
        location="Remote; Washington, DC",
        search_contexts=[
            {
                "source": "workday",
                "workplace": "remote",
                "job_type": "fulltime",
                "source_detail_location": "Remote; Washington, DC",
            }
        ],
    )

    assert _build_user_message(rf_input) == (
        "[Job title: Data Engineer]\n"
        "[Location field: Remote; Washington, DC]\n"
        "[Search provenance: workday: returned by a remote-only search filter or "
        "source detail metadata; treat this as weak but relevant evidence of "
        "remote eligibility unless contradicted by the posting; returned by a "
        "full-time search filter; source_detail_location=Remote; Washington, DC]"
        "\n\n---\n\n"
        "Ambiguous body text with no remote wording."
    )


def test_build_user_message_golden_title_location_keywords_case():
    rf_input = RemoteFilterInput(
        description="Desc.",
        title="AI Engineer",
        location="US-Remote",
        keywords="AI engineer",
    )

    assert _build_user_message(rf_input) == (
        "[Job title: AI Engineer]\n"
        "[Location field: US-Remote]\n"
        '[Search context: keywords="AI engineer"]'
        "\n\n---\n\n"
        "Desc."
    )


def test_build_user_message_golden_empty_context_case():
    assert _build_user_message(
        RemoteFilterInput(description="Just a description.")
    ) == ("Just a description.")


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
    assert args.classified_output is None
    assert args.config == "config/agent/remote_agent.yml"
    assert args.user_timezone is None


def test_remote_filter_custom_paths():
    args = _cli_parse_args(
        "--input",
        "raw.jsonl",
        "--classified-output",
        "classified.jsonl",
        "--config",
        "remote.yml",
        "--user-timezone",
        "PST",
    )
    assert args.input == "raw.jsonl"
    assert args.classified_output == "classified.jsonl"
    assert args.config == "remote.yml"
    assert args.user_timezone == "PST"


def test_remote_filter_run_date_flag():
    args = _cli_parse_args("--run-date", "2026-05-16")
    assert args.run_date == "2026-05-16"


def test_remote_filter_cmd_calls_runner():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input="raw.jsonl",
        classified_output="classified.jsonl",
        config="remote.yml",
        user_timezone="PST",
        cache_path=None,
        no_cache=False,
        run_date=None,
    )

    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="raw.jsonl",
        classified_path="classified.jsonl",
        config_path="remote.yml",
        user_timezone="PST",
        cache_path=DEFAULT_CACHE_PATH,
    )


def test_remote_filter_cmd_no_run_date_uses_legacy_defaults():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input=None,
        classified_output=None,
        config="remote.yml",
        user_timezone=None,
        run_date=None,
        cache_path=None,
        no_cache=False,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="data/prefiltered/remote_filter_input.jsonl",
        classified_path="data/filtered/remote_filter_classified.jsonl",
        config_path="remote.yml",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
    )


def test_remote_filter_cmd_run_date_resolves_partitioned_paths():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input=None,
        classified_output=None,
        config="remote.yml",
        user_timezone=None,
        run_date="2026-05-16",
        cache_path=None,
        no_cache=False,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="data/prefiltered/2026-05-16",
        classified_path="data/filtered/2026-05-16/remote_filter_classified.jsonl",
        config_path="remote.yml",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
    )


def test_remote_filter_cmd_no_cache_flag_disables_cache():
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input="raw.jsonl",
        classified_output="classified.jsonl",
        config="remote.yml",
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
        classified_output="custom/classified.jsonl",
        config="remote.yml",
        user_timezone=None,
        run_date="2026-05-16",
        cache_path=None,
        no_cache=False,
    )
    with patch("agents.remote_filter.runner.run_remote_filter") as mock_run:
        _cmd_remote_filter(args)

    mock_run.assert_called_once_with(
        input_path="custom/in.jsonl",
        classified_path="custom/classified.jsonl",
        config_path="remote.yml",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
    )


def test_remote_filter_cmd_batch_flag_routes_to_batch_runner():
    from agents.remote_filter.cache import DEFAULT_CACHE_PATH
    from agents.remote_filter.cli import _cmd_remote_filter

    args = _cli_fake_args(
        input="raw.jsonl",
        classified_output="classified.jsonl",
        config="remote.yml",
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
        classified_path="classified.jsonl",
        config_path="remote.yml",
        user_timezone=None,
        cache_path=DEFAULT_CACHE_PATH,
        poll_interval=30,
    )
