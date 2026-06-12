import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.remote_filter import batch
from agents.remote_filter.cache import AnalysisCache
from agents.remote_filter.models import RemoteAnalysis


FILTER_METADATA = {
    "schema_version": "3.0.0",
    "prompt_hash": "promptH",
    "prompt_file": "system_prompt.txt",
    "commit": "abc123",
    "dirty": False,
    "filtered_at": "2026-06-12T00:00:00Z",
}


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
  relocation:
    allow_required_relocation: false
    allow_local_presence_required: false
  uncertainty:
    on_unclear_classification: reject
  timezone:
    rejected_timezone_keywords: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


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
        "dedup_hash": "hashA",
    }
    return {**base, **overrides}


def _analysis(classification: str = "fully_remote", **overrides) -> RemoteAnalysis:
    data = {
        "reasoning_trace": "ok",
        "remote_classification": classification,
        "estimated_travel_days_per_year": None,
        "location_restrictions": [],
        "requires_relocation": False,
        "requires_local_presence": False,
        "timezone_requirements": [],
        "key_phrases": [classification],
    }
    return RemoteAnalysis(**{**data, **overrides})


def _result_line(custom_id: str, classification: str, **analysis_overrides) -> str:
    content = _analysis(classification, **analysis_overrides).model_dump_json()
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
                        "prompt_tokens_details": {"cached_tokens": 0},
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


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# build_request / parse_analysis (pure)
# ---------------------------------------------------------------------------


def test_build_request_uses_structured_remote_analysis_schema():
    request = batch.build_request(
        {
            "title": "Remote Engineer",
            "location": "USA",
            "description": "This role is fully remote.",
            "search_params": {"workplace": "remote"},
        },
        3,
        model="gpt-4o-mini",
        temperature=0.1,
        prompt_text="system prompt",
    )

    assert request["custom_id"] == "job-3"
    assert request["url"] == "/v1/chat/completions"
    body = request["body"]
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.1
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "remote_analysis"
    assert "Remote Engineer" in body["messages"][1]["content"]


def test_parse_analysis_happy_path():
    item = json.loads(_result_line("job-0", "fully_remote"))
    analysis = batch.parse_analysis(item)
    assert analysis is not None
    assert analysis.remote_classification == "fully_remote"


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
# run_remote_filter_batch orchestration
# ---------------------------------------------------------------------------


def test_run_batch_splits_pass_and_trash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "remote_agent.yml"
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(
        input_path,
        [
            _job(source_job_id="1", dedup_hash="hashA", title="RemoteRole"),
            _job(source_job_id="2", dedup_hash="hashB", title="HybridRole"),
        ],
    )

    content = (
        _result_line("job-0", "fully_remote")
        + "\n"
        + _result_line("job-1", "hybrid")
        + "\n"
    )

    with (
        patch.object(batch, "build_filter_metadata", return_value=FILTER_METADATA),
        patch.object(batch, "_get_client", return_value=(MagicMock(), "gpt-4o-mini")),
        patch.object(
            batch, "upload_and_create_batch", return_value=("batch-test", "file-1")
        ) as mock_upload,
        patch.object(batch, "poll_until_done", return_value=_completed_batch()),
        patch.object(batch, "download_results", return_value=content),
    ):
        counts = batch.run_remote_filter_batch(
            input_path=input_path,
            pass_path=pass_path,
            trash_path=trash_path,
            config_path=config_path,
            cache_path=cache_path,
        )

    mock_upload.assert_called_once()
    assert counts["pass"] == 1
    assert counts["trash"] == 1
    assert counts["submitted"] == 2
    assert counts["cache_misses"] == 2

    passes = _read_jsonl(pass_path)
    trashes = _read_jsonl(trash_path)
    assert [r["title"] for r in passes] == ["RemoteRole"]
    assert passes[0]["_filter_result"] == "pass"
    assert [r["title"] for r in trashes] == ["HybridRole"]
    assert trashes[0]["_filter_reason"] == "classification:hybrid"

    # Both analyses were written back to the cache for next time.
    assert len(_read_jsonl(cache_path)) == 2


def test_run_batch_serves_cache_hits_without_submitting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "remote_agent.yml"
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    from agents.remote_filter.utils import context_fingerprint

    primed_fp = context_fingerprint({"workplace": "remote"})
    seed = AnalysisCache(cache_path)
    seed.put(
        dedup_hash="hashA",
        prompt_hash=FILTER_METADATA["prompt_hash"],
        provider="openai",
        model="gpt-4o-mini",
        context_fp=primed_fp,
        analysis=_analysis("fully_remote"),
    )

    with (
        patch.object(batch, "build_filter_metadata", return_value=FILTER_METADATA),
        patch.object(batch, "_get_client") as mock_client,
        patch.object(batch, "upload_and_create_batch") as mock_upload,
    ):
        counts = batch.run_remote_filter_batch(
            input_path=input_path,
            pass_path=pass_path,
            trash_path=trash_path,
            config_path=config_path,
            cache_path=cache_path,
        )

    mock_upload.assert_not_called()
    mock_client.assert_not_called()
    assert counts["cache_hits"] == 1
    assert counts["submitted"] == 0
    assert counts["pass"] == 1
    assert _read_jsonl(pass_path)[0]["_filter_metadata"]["from_cache"] is True


def test_run_batch_rejects_non_openai_provider(tmp_path):
    config_path = tmp_path / "remote_agent.yml"
    input_path = tmp_path / "raw.jsonl"
    config_path.write_text(
        "llm:\n  provider: ollama\n  model: qwen2.5:14b\n"
        "policy_thresholds:\n  disallowed_classifications: []\n",
        encoding="utf-8",
    )
    _write_jsonl(input_path, [_job()])

    with pytest.raises(ValueError, match="provider=openai"):
        batch.run_remote_filter_batch(
            input_path=input_path,
            pass_path=tmp_path / "pass.jsonl",
            trash_path=tmp_path / "trash.jsonl",
            config_path=config_path,
            cache_path=None,
        )
