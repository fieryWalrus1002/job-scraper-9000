import time

from agents.remote_filter.models import RemoteAnalysis
from scripts import run_remote_filter_eval as eval_script


def _analysis(classification: str) -> RemoteAnalysis:
    return RemoteAnalysis(
        reasoning_trace=f"classified as {classification}",
        remote_classification=classification,  # type: ignore[arg-type]
        key_phrases=[classification],
    )


def _config() -> dict:
    return {
        "policy_thresholds": {
            "disallowed_classifications": [
                "hybrid",
                "onsite",
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
        }
    }


def test_parallel_eval_preserves_input_order_and_counts(monkeypatch):
    records = [
        {
            "title": "slow-pass",
            "company": "A",
            "description": "desc",
            "_human_verdict": "pass",
            "dedup_hash": "aaaa1111",
        },
        {
            "title": "fast-fn",
            "company": "B",
            "description": "desc",
            "_human_verdict": "pass",
            "_human_policy": "remote",
            "dedup_hash": "bbbb2222",
        },
        {
            "title": "medium-fp",
            "company": "C",
            "description": "desc",
            "_human_verdict": "trash",
            "_human_policy": "hybrid",
            "dedup_hash": "cccc3333",
        },
    ]

    def fake_analyze_remote(description, *, title, **kwargs):
        delays = {"slow-pass": 0.03, "fast-fn": 0.0, "medium-fp": 0.01}
        time.sleep(delays[title])
        if title == "fast-fn":
            return _analysis("hybrid")
        return _analysis("remote")

    monkeypatch.setattr(eval_script, "analyze_remote", fake_analyze_remote)

    mismatches, counts = eval_script.run_eval(
        records,
        _config(),
        run_id="test_run",
        workers=3,
    )

    assert counts == {"tp": 1, "fp": 1, "tn": 0, "fn": 1, "skipped": 0}
    assert [m.record_id for m in mismatches] == ["bbbb2222", "cccc3333"]


def test_run_eval_counts_skipped_records_without_inference(monkeypatch):
    calls = 0

    def fake_analyze_remote(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _analysis("remote")

    monkeypatch.setattr(eval_script, "analyze_remote", fake_analyze_remote)

    records = [
        {"title": "bad verdict", "description": "desc", "_human_verdict": "maybe"},
        {"title": "missing description", "description": "", "_human_verdict": "pass"},
    ]

    mismatches, counts = eval_script.run_eval(records, _config(), "test_run", workers=2)

    assert mismatches == []
    assert counts == {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "skipped": 2}
    assert calls == 0
