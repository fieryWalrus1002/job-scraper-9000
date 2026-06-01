import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agents.skills_fit.models import SCHEMA_VERSION, JobMetadata


def make_metadata(**overrides) -> JobMetadata:
    base = dict(
        run_id="run-abc",
        scored_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        config_file="config/agent/skills_fit.yml",
        prompt_file="prompts/skills_fit/system_prompt.txt",
        prompt_hash="sha256:aaa",
        profile_file="config/profile/candidate_profile.yml",
        profile_hash="sha256:bbb",
        profile_version="v1.0",
        provider="openai",
        model="gpt-4o-mini",
        commit="abc123",
        dirty=False,
        input_source="remote_filter_pass",
        input_path="data/filtered/2026-06-01/remote_filter_pass.jsonl",
    )
    base.update(overrides)
    return JobMetadata(**base)


def test_scored_at_serializes_as_string_not_datetime():
    dumped = make_metadata().model_dump(mode="json")
    assert isinstance(dumped["scored_at"], str)


def test_dump_is_json_serializable():
    dumped = make_metadata(temperature=0.3).model_dump(mode="json", exclude_none=True)
    json.dumps(dumped)  # must not raise


def test_failure_reason_absent_on_success_record():
    dumped = make_metadata().model_dump(mode="json", exclude_none=True)
    assert "failure_reason" not in dumped


def test_failure_reason_present_on_failure_record():
    dumped = make_metadata(failure_reason="agent_failed").model_dump(
        mode="json", exclude_none=True
    )
    assert dumped["failure_reason"] == "agent_failed"


def test_temperature_absent_when_none():
    dumped = make_metadata(temperature=None).model_dump(mode="json", exclude_none=True)
    assert "temperature" not in dumped


def test_temperature_present_when_set():
    dumped = make_metadata(temperature=0.3).model_dump(mode="json", exclude_none=True)
    assert dumped["temperature"] == 0.3


def test_schema_version_defaults_without_being_passed():
    assert make_metadata().skills_fit_schema_version == SCHEMA_VERSION


def test_invalid_input_source_raises_validation_error():
    with pytest.raises(ValidationError):
        make_metadata(input_source="wrong_value")
