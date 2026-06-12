import json
from pathlib import Path

from agents.remote_filter.models import RemoteAnalysis
from scripts import poll_eval_batch, submit_eval_batch


def _config() -> dict:
    return {
        "llm": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1},
        "policy_thresholds": {
            "disallowed_classifications": [
                "hybrid",
                "onsite_disguised",
                "location_restricted",
            ],
            "travel": {
                "max_estimated_days_per_year": 15,
            },
            "relocation": {
                "allow_required_relocation": False,
                "allow_local_presence_required": False,
            },
            "uncertainty": {"on_unclear_classification": "reject"},
            "timezone": {"rejected_timezone_keywords": []},
        },
    }


def _analysis_json(classification: str) -> str:
    return RemoteAnalysis(
        reasoning_trace=f"classified as {classification}",
        remote_classification=classification,  # type: ignore[arg-type]
        key_phrases=[classification],
    ).model_dump_json()


def _batch_item(custom_id: str, content: str) -> dict:
    return {
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "body": {"choices": [{"message": {"content": content}}]},
        },
    }


def test_build_request_uses_structured_remote_analysis_schema(monkeypatch):
    monkeypatch.delenv("USER_TIMEZONE", raising=False)
    request = submit_eval_batch.build_request(
        {
            "title": "Remote Engineer",
            "location": "USA",
            "description": "This role is fully remote.",
            "search_params": {"workplace": "remote"},
        },
        3,
        _config(),
        "system prompt",
    )

    assert request["custom_id"] == "job-3"
    assert request["url"] == "/v1/chat/completions"
    body = request["body"]
    assert body["model"] == "gpt-4o-mini"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "remote_analysis"
    assert "Remote Engineer" in body["messages"][1]["content"]


def test_evaluate_batch_results_preserves_order_and_counts():
    records = [
        {
            "title": "pass",
            "company": "A",
            "_human_verdict": "pass",
            "dedup_hash": "aaaa1111",
        },
        {
            "title": "fn",
            "company": "B",
            "_human_verdict": "pass",
            "_human_policy": "fully_remote",
            "dedup_hash": "bbbb2222",
        },
        {
            "title": "fp",
            "company": "C",
            "_human_verdict": "trash",
            "_human_policy": "hybrid",
            "dedup_hash": "cccc3333",
        },
    ]
    results = {
        "job-2": _batch_item("job-2", _analysis_json("fully_remote")),
        "job-0": _batch_item("job-0", _analysis_json("fully_remote")),
        "job-1": _batch_item("job-1", _analysis_json("hybrid")),
    }

    mismatches, counts = poll_eval_batch.evaluate_batch_results(
        records,
        results,
        {"run_id": "batch_test", "config": _config(), "user_location": "USA"},
    )

    assert counts == {"tp": 1, "fp": 1, "tn": 0, "fn": 1, "skipped": 0}
    assert [m.record_id for m in mismatches] == ["bbbb2222", "cccc3333"]


def test_load_results_indexes_by_custom_id(tmp_path: Path):
    results_path = tmp_path / "results.jsonl"
    results_path.write_text(
        json.dumps({"custom_id": "job-1", "response": {}})
        + "\n"
        + json.dumps({"custom_id": "job-0", "response": {}})
        + "\n",
        encoding="utf-8",
    )

    results = poll_eval_batch.load_results(results_path)

    assert list(results) == ["job-1", "job-0"]
    assert results["job-0"]["custom_id"] == "job-0"
