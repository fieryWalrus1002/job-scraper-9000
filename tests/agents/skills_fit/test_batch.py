import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.skills_fit import batch, runner
from agents.skills_fit.cache import AnalysisCache
from agents.skills_fit.models import SkillsFitAnalysis


GIT_METADATA = {
    "commit": "abc123",
    "dirty": False,
    "timestamp": "2026-06-12T00:00:00+00:00",
}


def _write_config(path: Path, profile_path: Path, *, provider: str = "openai") -> None:
    path.write_text(
        f"""
llm:
  provider: {provider}
  model: gpt-4o-mini
  temperature: 0.1
profile_file: {profile_path}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_profile(path: Path) -> None:
    path.write_text(
        """
profile_version: test-v1
summary: Python backend engineer
core_skills:
  - Python
  - APIs
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _job(**overrides) -> dict:
    base = {
        "source": "test",
        "source_job_id": "1",
        "source_url": "https://example.test/job/1",
        "title": "Python Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "Build Python APIs.",
        "dedup_hash": "hashA",
        "_remote_analysis": {"remote_classification": "fully_remote"},
        "_filter_result": "pass",
    }
    return {**base, **overrides}


def _analysis(score: int = 5, **overrides) -> SkillsFitAnalysis:
    data = {
        "fit_score": score,
        "confidence": "high",
        "score_rationale": "Strong Python/API match.",
        "top_matches": ["Python", "APIs"],
        "gaps": [],
        "hard_concerns": [],
        "core_job_duties": ["Build Python APIs"],
    }
    return SkillsFitAnalysis(**{**data, **overrides})


def _result_line(custom_id: str, score: int = 5, **analysis_overrides) -> str:
    content = _analysis(score, **analysis_overrides).model_dump_json()
    return json.dumps(
        {
            "custom_id": custom_id,
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": content}}],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "prompt_tokens_details": {"cached_tokens": 10},
                    },
                },
            },
        }
    )


def _completed_batch():
    batch_obj = MagicMock()
    batch_obj.id = "batch-test"
    batch_obj.status = "completed"
    return batch_obj


# ---------------------------------------------------------------------------
# build_request / parse_analysis (pure)
# ---------------------------------------------------------------------------


def test_build_request_uses_structured_skills_fit_schema():
    request = batch.build_request(
        {
            "title": "Python Engineer",
            "location": "Remote",
            "description": "Build Python APIs.",
        },
        3,
        model="gpt-4o-mini",
        temperature=0.1,
        prompt_text="system prompt",
        candidate_profile={"core_skills": ["Python"]},
    )

    assert request["custom_id"] == "job-3"
    assert request["url"] == "/v1/chat/completions"
    body = request["body"]
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.1
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "skills_fit_analysis"
    assert "Python Engineer" in body["messages"][1]["content"]
    assert "CANDIDATE PROFILE" in body["messages"][1]["content"]


def test_parse_analysis_happy_path():
    item = json.loads(_result_line("job-0", 5))
    analysis = batch.parse_analysis(item)
    assert analysis is not None
    assert analysis.fit_score == 5


def test_parse_analysis_returns_none_on_error_or_bad_status():
    assert batch.parse_analysis({"custom_id": "job-0", "error": "boom"}) is None
    assert (
        batch.parse_analysis(
            {"custom_id": "job-0", "response": {"status_code": 500, "body": {}}}
        )
        is None
    )
    assert (
        batch.parse_analysis(
            {"custom_id": "job-0", "response": {"status_code": 200, "body": {}}}
        )
        is None
    )


def test_parse_analysis_returns_none_on_schema_invalid_content():
    item = {
        "custom_id": "job-0",
        "response": {
            "status_code": 200,
            "body": {"choices": [{"message": {"content": '{"not":"valid"}'}}]},
        },
    }
    assert batch.parse_analysis(item) is None


# ---------------------------------------------------------------------------
# run_skills_fit_batch orchestration
# ---------------------------------------------------------------------------


def test_run_batch_scores_cache_misses_and_writes_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "skills_fit.yml"
    profile_path = tmp_path / "profile.yml"
    input_path = tmp_path / "remote.jsonl"
    output_path = tmp_path / "scored.jsonl"
    _write_profile(profile_path)
    _write_config(config_path, profile_path)
    _write_jsonl(input_path, [_job()])

    with (
        patch.object(batch, "get_git_metadata", return_value=GIT_METADATA),
        patch.object(batch, "_get_client", return_value=(MagicMock(), "gpt-4o-mini")),
        patch.object(
            batch, "upload_and_create_batch", return_value=("batch-test", "file-1")
        ) as mock_upload,
        patch.object(batch, "poll_until_done", return_value=_completed_batch()),
        patch.object(batch, "download_results", return_value=_result_line("job-0")),
    ):
        counts = batch.run_skills_fit_batch(
            remote_input=input_path,
            local_input=tmp_path / "missing_local.jsonl",
            output=output_path,
            config_path=config_path,
        )

    mock_upload.assert_called_once()
    assert counts["scored_successfully"] == 1
    assert counts["submitted"] == 1
    assert counts["cache_misses"] == 1

    rows = _read_jsonl(output_path)
    assert len(rows) == 1
    assert rows[0]["ai_fit"]["fit_score"] == 5
    assert rows[0]["metadata"]["provider"] == "openai"
    assert len(_read_jsonl(tmp_path / "data/cache/skills_fit_analyses.jsonl")) == 1


def test_run_batch_serves_cache_hits_without_submitting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "skills_fit.yml"
    profile_path = tmp_path / "profile.yml"
    input_path = tmp_path / "remote.jsonl"
    output_path = tmp_path / "scored.jsonl"
    _write_profile(profile_path)
    _write_config(config_path, profile_path)
    _write_jsonl(input_path, [_job()])

    cache = AnalysisCache(tmp_path / "data/cache/skills_fit_analyses.jsonl")
    with patch.object(
        batch, "hash_file", side_effect=lambda path: f"hash:{Path(path).name}"
    ):
        prompt_hash = batch.hash_file(batch.SKILLS_FIT_PROMPT_PATH)
    cache.put(
        dedup_hash="hashA",
        prompt_hash=prompt_hash,
        provider="openai",
        model="gpt-4o-mini",
        profile_version="test-v1",
        analysis=_analysis(4),
    )

    def fake_hash_file(path):
        return f"hash:{Path(path).name}"

    with (
        patch.object(batch, "hash_file", side_effect=fake_hash_file),
        patch.object(batch, "get_git_metadata", return_value=GIT_METADATA),
        patch.object(batch, "_get_client") as mock_client,
        patch.object(batch, "upload_and_create_batch") as mock_upload,
    ):
        counts = batch.run_skills_fit_batch(
            remote_input=input_path,
            local_input=tmp_path / "missing_local.jsonl",
            output=output_path,
            config_path=config_path,
        )

    mock_upload.assert_not_called()
    mock_client.assert_not_called()
    assert counts["cache_hits"] == 1
    assert counts["submitted"] == 0
    assert counts["scored_successfully"] == 1
    assert _read_jsonl(output_path)[0]["ai_fit"]["fit_score"] == 4


def test_run_batch_rejects_non_openai_provider(tmp_path):
    config_path = tmp_path / "skills_fit.yml"
    profile_path = tmp_path / "profile.yml"
    input_path = tmp_path / "remote.jsonl"
    _write_profile(profile_path)
    _write_config(config_path, profile_path, provider="ollama")
    _write_jsonl(input_path, [_job()])

    with pytest.raises(ValueError, match="provider=openai"):
        batch.run_skills_fit_batch(
            remote_input=input_path,
            local_input=tmp_path / "missing_local.jsonl",
            output=tmp_path / "scored.jsonl",
            config_path=config_path,
        )


def test_batch_output_matches_serial_shape_for_same_analysis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "skills_fit.yml"
    profile_path = tmp_path / "profile.yml"
    input_path = tmp_path / "remote.jsonl"
    serial_output = tmp_path / "serial.jsonl"
    batch_output = tmp_path / "batch.jsonl"
    _write_profile(profile_path)
    _write_config(config_path, profile_path)
    _write_jsonl(input_path, [_job()])

    def usage_analyze(*args, usage_callback=None, **kwargs):
        if usage_callback is not None:
            usage_callback(
                {"input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 20}
            )
        return _analysis(5)

    with (
        patch.object(runner, "DEFAULT_CACHE_PATH", tmp_path / "serial_cache.jsonl"),
        patch.object(runner, "generate_run_id", return_value="skillsfit-test"),
        patch.object(runner, "get_git_metadata", return_value=GIT_METADATA),
        patch.object(runner, "analyze_skills_fit", side_effect=usage_analyze),
    ):
        runner.run_skills_fit(
            remote_input=input_path,
            local_input=tmp_path / "missing_local.jsonl",
            output=serial_output,
            config_path=config_path,
        )

    with (
        patch.object(batch, "DEFAULT_CACHE_PATH", tmp_path / "batch_cache.jsonl"),
        patch.object(batch, "generate_run_id", return_value="skillsfit-test"),
        patch.object(batch, "get_git_metadata", return_value=GIT_METADATA),
        patch.object(batch, "_get_client", return_value=(MagicMock(), "gpt-4o-mini")),
        patch.object(
            batch, "upload_and_create_batch", return_value=("batch-test", "file-1")
        ),
        patch.object(batch, "poll_until_done", return_value=_completed_batch()),
        patch.object(batch, "download_results", return_value=_result_line("job-0", 5)),
    ):
        batch.run_skills_fit_batch(
            remote_input=input_path,
            local_input=tmp_path / "missing_local.jsonl",
            output=batch_output,
            config_path=config_path,
        )

    assert _read_jsonl(batch_output) == _read_jsonl(serial_output)
