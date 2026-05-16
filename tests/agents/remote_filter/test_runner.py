import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.runner import load_remote_filter_config, run_remote_filter


FILTER_METADATA = {
    "schema_version": "2.0.0",
    "prompt_hash": "h",
    "prompt_file": "system_prompt.txt",
    "commit": "abcdef123456",
    "dirty": False,
    "filtered_at": "2026-05-16T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _write_config(path: Path) -> None:
    path.write_text(
        """
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.1

policy_thresholds:
  disallowed_classifications:
    - hybrid
    - onsite_disguised
  travel:
    max_estimated_days_per_year: 15
    prohibited_categories:
      - remote_with_frequent_travel
  relocation:
    allow_required_relocation: false
    allow_local_presence_required: false
  uncertainty:
    on_unclear_classification: reject
  timezone:
    rejected_timezone_keywords:
      - EST
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _job(**overrides) -> dict:
    base = {
        "source": "test",
        "source_job_id": "1",
        "source_url": "https://example.test/job/1",
        "title": "Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "This is a remote job.",
        "search_params": {"workplace": "remote"},
        "dedup_hash": "abc123",
    }
    return {**base, **overrides}


def _analysis(classification: str, **overrides) -> RemoteAnalysis:
    data = {
        "reasoning_trace": f"classified as {classification}",
        "remote_classification": classification,
        "estimated_travel_days_per_year": None,
        "location_restrictions": [],
        "requires_relocation": False,
        "requires_local_presence": False,
        "timezone_requirements": [],
        "key_phrases": [classification],
    }
    return RemoteAnalysis(**{**data, **overrides})


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_remote_filter_config_expands_environment(tmp_path, monkeypatch):
    config_path = tmp_path / "remote_agent.yml"
    config_path.write_text(
        """
llm:
  provider: openai
  model: ${MODEL_NAME}
policy_thresholds: {}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_NAME", "gpt-test")

    config = load_remote_filter_config(config_path)

    assert config["llm"]["model"] == "gpt-test"


# ---------------------------------------------------------------------------
# run_remote_filter
# ---------------------------------------------------------------------------


def test_run_remote_filter_writes_pass_and_trash_outputs(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)
    _write_jsonl(
        input_path,
        [
            _job(source_job_id="1", title="Remote Engineer"),
            _job(source_job_id="2", title="Hybrid Engineer"),
        ],
    )

    analyses = [_analysis("fully_remote"), _analysis("hybrid")]

    with patch("agents.remote_filter.runner.analyze_remote", side_effect=analyses):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
                user_location="USA",
            )

    assert counts == {"pass": 1, "trash": 1, "skipped": 0, "total": 2}

    pass_records = [json.loads(line) for line in pass_path.read_text().splitlines()]
    trash_records = [json.loads(line) for line in trash_path.read_text().splitlines()]

    assert len(pass_records) == 1
    assert pass_records[0]["title"] == "Remote Engineer"
    assert pass_records[0]["_filter_result"] == "pass"
    assert pass_records[0]["_filter_reason"] == "passed"
    assert (
        pass_records[0]["_remote_analysis"]["remote_classification"] == "fully_remote"
    )
    assert pass_records[0]["_filter_metadata"] == FILTER_METADATA

    assert len(trash_records) == 1
    assert trash_records[0]["title"] == "Hybrid Engineer"
    assert trash_records[0]["_filter_result"] == "trash"
    assert trash_records[0]["_filter_reason"] == "classification:hybrid"


def test_run_remote_filter_skips_missing_description_without_inference(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(description="")])

    with patch("agents.remote_filter.runner.analyze_remote") as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
            )

    assert counts == {"pass": 0, "trash": 0, "skipped": 1, "total": 1}
    mock_analyze.assert_not_called()
    assert pass_path.read_text() == ""
    assert trash_path.read_text() == ""


def test_run_remote_filter_skips_failed_agent_result(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)
    _write_jsonl(input_path, [_job()])

    with patch("agents.remote_filter.runner.analyze_remote", return_value=None):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
            )

    assert counts == {"pass": 0, "trash": 0, "skipped": 1, "total": 1}
    assert pass_path.read_text() == ""
    assert trash_path.read_text() == ""


def test_run_remote_filter_raises_when_no_jobs_found(tmp_path):
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)

    with pytest.raises(FileNotFoundError, match="No jobs found"):
        run_remote_filter(
            input_path=tmp_path / "empty-dir",
            pass_path=tmp_path / "pass.jsonl",
            trash_path=tmp_path / "trash.jsonl",
            config_path=config_path,
        )
