import hashlib
import time

from agents.remote_filter.input_models import RemoteFilterInput
from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.utils import _build_user_message
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

    def fake_analyze_remote(rf_input, **kwargs):
        assert isinstance(rf_input, RemoteFilterInput)
        assert set(kwargs) == {"llm_config"}
        delays = {"slow-pass": 0.03, "fast-fn": 0.0, "medium-fp": 0.01}
        time.sleep(delays[rf_input.title])
        if rf_input.title == "fast-fn":
            return _analysis("hybrid")
        return _analysis("remote")

    monkeypatch.setattr(eval_script, "analyze_remote", fake_analyze_remote)

    mismatches, counts, prompt_hashes = eval_script.run_eval(
        records,
        _config(),
        run_id="test_run",
        workers=3,
    )

    assert counts == {"tp": 1, "fp": 1, "tn": 0, "fn": 1, "skipped": 0}
    assert [m.record_id for m in mismatches] == ["bbbb2222", "cccc3333"]
    assert [h.record_id for h in prompt_hashes] == [
        "aaaa1111",
        "bbbb2222",
        "cccc3333",
    ]
    assert all(len(h.resolved_user_message_hash) == 12 for h in prompt_hashes)


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

    mismatches, counts, prompt_hashes = eval_script.run_eval(
        records, _config(), "test_run", workers=2
    )

    assert mismatches == []
    assert counts == {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "skipped": 2}
    assert prompt_hashes == []
    assert calls == 0


def test_eval_uses_remote_filter_input_and_records_resolved_prompt_hash(monkeypatch):
    monkeypatch.setattr(eval_script, "USER_TIMEZONE", "Europe/Oslo")
    captured_inputs = []

    def fake_analyze_remote(rf_input, **kwargs):
        captured_inputs.append(rf_input)
        assert set(kwargs) == {"llm_config"}
        return _analysis("remote")

    monkeypatch.setattr(eval_script, "analyze_remote", fake_analyze_remote)

    records = [
        {
            "title": "Backend Engineer",
            "company": "ExampleCo",
            "location": "Berlin, Germany",
            "description": "Build APIs.",
            "search_params": {
                "keywords": "python",
                "workplace": "remote",
                "job_type": "fulltime",
            },
            "search_contexts": [
                {
                    "source": "linkedin",
                    "workplace": "remote",
                    "job_type": "fulltime",
                    "source_detail_location": "Remote",
                }
            ],
            "_human_verdict": "trash",
            "_human_policy": "remote_policy",
            "dedup_hash": "dddd4444eeee",
        }
    ]

    mismatches, counts, prompt_hashes = eval_script.run_eval(
        records,
        _config(),
        run_id="test_run",
    )

    assert counts == {"tp": 0, "fp": 1, "tn": 0, "fn": 0, "skipped": 0}
    assert len(captured_inputs) == 1
    rf_input = captured_inputs[0]
    assert isinstance(rf_input, RemoteFilterInput)
    assert rf_input.description == "Build APIs."
    assert rf_input.title == "Backend Engineer"
    assert rf_input.location == "Berlin, Germany"
    assert rf_input.keywords == "python"
    assert rf_input.workplace == "remote"
    assert rf_input.job_type == "fulltime"
    assert rf_input.user_timezone == "Europe/Oslo"
    assert len(rf_input.search_contexts) == 1

    expected_hash = hashlib.sha256(
        _build_user_message(rf_input).encode("utf-8")
    ).hexdigest()[:12]
    assert prompt_hashes[0].resolved_user_message_hash == expected_hash
    assert prompt_hashes[0].record_id == "dddd4444eeee"
    assert mismatches[0].resolved_user_message_hash == expected_hash
