import json
from pathlib import Path

import pytest

from prefilter.router import load_prefilter_config, route_job, run_prefilter


FIXTURE_PATH = Path("tests/fixtures/prefilter_cases.jsonl")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


@pytest.fixture()
def prefilter_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME_LOCATION", "Pullman, WA")
    cfg_path = tmp_path / "prefilter.yml"
    cfg_path.write_text(
        """country: USA
country_detection:
  enabled: true
  sources: [location, description]
  aliases:
    USA: [US, U.S., United States, United States of America, America, United States (US)]
  unknown_policy: continue
local_area:
  allowed_locations:
    - Pullman, WA
    - Seattle, WA
  home_location: Pullman, WA
routing:
  route_local_jobs: true
  route_remote_candidates: true
  reject_non_us: true
  prefer_search_params_as_weak_signal: true
filter_terms:
  banned_anywhere:
    - toxic-company
""",
        encoding="utf-8",
    )
    # Return both the parsed config object AND the exact path where it lives
    return load_prefilter_config(cfg_path), cfg_path


@pytest.mark.parametrize(
    "job, expected_route, expected_reason",
    [
        (
            json.loads(line),
            json.loads(line)["expected_route"],
            json.loads(line)["expected_reason"],
        )
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ],
)
def test_route_job_fixtures(job, expected_route, expected_reason, prefilter_setup):
    config_obj, _ = prefilter_setup
    decision = route_job(job, config_obj)
    assert decision.route == expected_route
    assert decision.reason == expected_reason
    assert decision.rule_trace
    assert decision.country_hits is not None


def test_run_prefilter_writes_combined_bucket_outputs(
    tmp_path, prefilter_setup, monkeypatch
):
    monkeypatch.setenv("HOME_LOCATION", "Pullman, WA")
    # 1. FIX: Unpack the tuple here to get the correct config path
    _, cfg_file_path = prefilter_setup

    jobs = [
        json.loads(line)
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    input_path = tmp_path / "raw"
    input_path.mkdir()
    _write_jsonl(input_path / "jobs.jsonl", jobs)

    remote_out = tmp_path / "prefiltered" / "remote.jsonl"
    local_out = tmp_path / "local" / "local.jsonl"
    trash_out = tmp_path / "trash" / "trash.jsonl"

    counts = run_prefilter(
        input_path=input_path,
        remote_out=remote_out,
        local_out=local_out,
        trash_out=trash_out,
        config_path=cfg_file_path,  # 2. FIX: Pass the verified path from the fixture
    )

    assert counts["total"] == len(jobs)
    assert remote_out.exists()
    assert local_out.exists()
    assert trash_out.exists()

    remote_lines = [
        json.loads(line)
        for line in remote_out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    local_lines = [
        json.loads(line)
        for line in local_out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    trash_lines = [
        json.loads(line)
        for line in trash_out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert sum(
        len(bucket) for bucket in (remote_lines, local_lines, trash_lines)
    ) == len(jobs)
    assert all(
        "_prefilter_result" in rec for rec in remote_lines + local_lines + trash_lines
    )
    assert all(
        "_prefilter_metadata" in rec for rec in remote_lines + local_lines + trash_lines
    )


def test_dry_run_does_not_write_outputs(tmp_path, prefilter_setup, monkeypatch):
    # This one you got perfectly!
    _, cfg_file_path = prefilter_setup

    jobs = [
        json.loads(line)
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    input_path = tmp_path / "raw"
    input_path.mkdir()
    _write_jsonl(input_path / "jobs.jsonl", jobs)

    remote_out = tmp_path / "prefiltered" / "remote.jsonl"
    local_out = tmp_path / "local" / "local.jsonl"
    trash_out = tmp_path / "trash" / "trash.jsonl"

    counts = run_prefilter(
        input_path=input_path,
        remote_out=remote_out,
        local_out=local_out,
        trash_out=trash_out,
        config_path=cfg_file_path,
        dry_run=True,
    )

    assert counts["total"] == len(jobs)
    assert not remote_out.exists()
    assert not local_out.exists()
    assert not trash_out.exists()
