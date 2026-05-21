import json
from pathlib import Path

import pytest

from utils.run_tracker import RunTracker


def _read_records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_minimal_run_writes_record(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(
        component="test_component", run_type="dev", log_path=runs_path
    ) as run:
        run.set_input(path="/some/input", record_count=10, deduped_record_count=10)
        run.add_output(label="pass", record_count=7)

    records = _read_records(runs_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["component"] == "test_component"
    assert rec["run_type"] == "dev"
    assert rec["input"]["record_count"] == 10
    assert rec["outputs"][0]["label"] == "pass"
    assert rec["outputs"][0]["record_count"] == 7
    assert rec["timing"]["duration_seconds"] is not None
    assert rec["timing"]["duration_seconds"] >= 0


def test_run_ids_are_unique(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    ids = []
    for _ in range(3):
        with RunTracker(component="c", log_path=runs_path) as run:
            ids.append(run.run_id)
    assert len(set(ids)) == 3


def test_cache_hit_rate_derived(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(component="c", log_path=runs_path) as run:
        run.set_cache(path="/cache", hits=8, misses=2)
    rec = _read_records(runs_path)[0]
    assert rec["cache"]["hit_rate"] == 0.8


def test_cost_per_record_derived(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(component="c", log_path=runs_path) as run:
        run.set_input(path="x", record_count=100, deduped_record_count=100)
        run.set_cost(estimated_total=0.25)
    rec = _read_records(runs_path)[0]
    assert rec["cost"]["estimated_per_record"] == 0.0025


def test_failure_recorded_on_exception(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with pytest.raises(ValueError):
        with RunTracker(component="c", log_path=runs_path) as run:
            run.set_input(record_count=10)
            raise ValueError("boom")
    rec = _read_records(runs_path)[0]
    assert rec["events"]["failure_count"] == 1
    assert "ValueError" in rec["events"]["notable"][0]
    assert "boom" in rec["events"]["notable"][0]


def test_token_accumulation_rolls_into_llm(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(component="c", log_path=runs_path) as run:
        run.set_llm(provider="openai", model="gpt-4o-mini", temperature=0.1)
        for _ in range(3):
            run.add_token_usage(
                input_tokens=100, cached_input_tokens=20, output_tokens=50
            )
    rec = _read_records(runs_path)[0]
    assert rec["llm"]["input_tokens_total"] == 300
    assert rec["llm"]["input_tokens_cached"] == 60
    assert rec["llm"]["output_tokens_total"] == 150


def test_latency_median_derived(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(component="c", log_path=runs_path) as run:
        run.set_llm(provider="openai", model="gpt-4o-mini")
        for elapsed in [1.0, 2.0, 3.0]:
            run.record_call_latency(elapsed)
    rec = _read_records(runs_path)[0]
    assert rec["llm"]["median_latency_seconds"] == 2.0


def test_deterministic_component_writes_no_llm_block(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(
        component="prefilter", run_type="production", log_path=runs_path
    ) as run:
        run.set_input(path="data/raw/2026-05-21", record_count=1457)
        run.add_output(label="remote", record_count=1087)
        run.add_output(label="local", record_count=88)
        run.add_output(label="reject", record_count=282)
    rec = _read_records(runs_path)[0]
    assert rec["llm"] is None
    assert rec["cost"] is None
    assert len(rec["outputs"]) == 3
    assert {o["label"] for o in rec["outputs"]} == {"remote", "local", "reject"}


def test_parent_run_id_link(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.jsonl"
    with RunTracker(
        component="prefilter", log_path=runs_path
    ) as parent:
        parent_id = parent.run_id
    with RunTracker(
        component="remote_filter", log_path=runs_path, parent_run_id=parent_id
    ) as _:
        pass
    records = _read_records(runs_path)
    assert records[1]["links"]["parent_run_id"] == parent_id
