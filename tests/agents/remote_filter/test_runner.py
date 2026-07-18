import json
import threading
import time
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
    - onsite
  travel:
    max_estimated_days_per_year: 15
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


def test_run_remote_filter_writes_all_classified_outputs(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)
    _write_jsonl(
        input_path,
        [
            _job(source_job_id="1", title="Remote Engineer", dedup_hash="h1"),
            _job(source_job_id="2", title="Hybrid Engineer", dedup_hash="h2"),
        ],
    )

    analyses = [_analysis("remote"), _analysis("hybrid")]

    with patch("agents.remote_filter.runner.analyze_remote", side_effect=analyses):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=tmp_path / "cache.jsonl",
            )

    assert counts["classified"] == 2
    assert counts["skipped"] == 0
    assert counts["total"] == 2
    assert counts["deduped"] == 0
    assert counts["cache_hits"] == 0
    assert counts["cache_misses"] == 2

    records = [json.loads(line) for line in classified_path.read_text().splitlines()]

    # Cache-miss records are written as they complete (``imap_unordered``), so
    # the output order is not deterministic — key by title rather than position.
    by_title = {r["title"]: r for r in records}
    assert set(by_title) == {"Remote Engineer", "Hybrid Engineer"}
    assert {r["_filter_result"] for r in records} == {"pass"}
    assert {r["_filter_reason"] for r in records} == {"classified"}
    assert (
        by_title["Remote Engineer"]["_remote_analysis"]["remote_classification"]
        == "remote"
    )
    assert (
        by_title["Hybrid Engineer"]["_remote_analysis"]["remote_classification"]
        == "hybrid"
    )
    assert all(
        r["_filter_metadata"] == {**FILTER_METADATA, "from_cache": False}
        for r in records
    )


def test_run_remote_filter_skips_missing_description_without_inference(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
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
                classified_path=classified_path,
                config_path=config_path,
                cache_path=None,
            )

    assert counts["classified"] == 0
    assert counts["skipped"] == 1
    assert counts["total"] == 1
    mock_analyze.assert_not_called()
    assert classified_path.read_text() == ""


def test_run_remote_filter_skips_failed_agent_result(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
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
                classified_path=classified_path,
                config_path=config_path,
                cache_path=None,
            )

    assert counts["classified"] == 0
    assert counts["skipped"] == 1
    assert counts["total"] == 1
    assert classified_path.read_text() == ""


def test_run_remote_filter_raises_when_no_jobs_found(tmp_path):
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)

    with pytest.raises(FileNotFoundError, match="No jobs found"):
        run_remote_filter(
            input_path=tmp_path / "empty-dir",
            classified_path=tmp_path / "classified.jsonl",
            config_path=config_path,
        )


def test_run_remote_filter_runs_concurrently(tmp_path):
    """Assert that LLM calls are executed in parallel, not sequentially."""
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"

    # Config with max_workers=4 to ensure parallelism.
    config_path.write_text(
        """\
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.1
  max_workers: 4

policy_thresholds:
  disallowed_classifications:
    - hybrid
    - onsite
  travel:
    max_estimated_days_per_year: 15
  relocation:
    allow_required_relocation: false
    allow_local_presence_required: false
  uncertainty:
    on_unclear_classification: reject
  timezone:
    rejected_timezone_keywords:
      - EST
""",
        encoding="utf-8",
    )

    # Write 6 jobs so the pool has enough to overlap.
    jobs = [
        _job(source_job_id=str(i), title=f"Engineer {i}", dedup_hash=f"h{i}")
        for i in range(6)
    ]
    _write_jsonl(input_path, jobs)

    # Track max concurrent calls.
    concurrent_count = 0
    max_concurrent = 0
    lock = threading.Lock()
    gate = threading.Event()
    # Block workers until the gate opens so they all start together.
    gate_blocked = threading.Event()

    def slow_analyze(*args, **kwargs):
        with lock:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            # Signal that at least one worker is in-flight.
            gate_blocked.set()
        # Wait for the gate so all workers pile up.
        gate.wait(timeout=5)
        time.sleep(0.05)  # Simulate network latency.
        with lock:
            concurrent_count -= 1
        return _analysis("remote")

    with patch("agents.remote_filter.runner.analyze_remote", side_effect=slow_analyze):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    assert counts["classified"] == 6
    assert counts["cache_misses"] == 6
    # With max_workers=4 and 6 jobs, we should see >1 concurrent call.
    assert max_concurrent > 1, f"Expected concurrent calls > 1, got {max_concurrent}"
