import hashlib
import time

import pytest
from pydantic import ValidationError

from agent_eval.costing import (
    aggregate_token_totals,
    build_cost_summary,
    empty_token_totals,
)
from agent_eval.stats import latency_summary, percentile
from agents.remote_filter.input_models import RemoteFilterInput
from agents.remote_filter import eval as eval_core
from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.utils import _build_user_message
from scripts import run_remote_filter_eval as eval_script


def _analysis(classification: str, travel_days: int | None = None) -> RemoteAnalysis:
    return RemoteAnalysis(
        reasoning_trace=f"classified as {classification}",
        remote_classification=classification,  # type: ignore[arg-type]
        estimated_travel_days_per_year=travel_days,
        key_phrases=[classification],
    )


def _config() -> dict:
    return {"llm": {"provider": "fake"}}


def test_remote_analysis_rejects_retired_unclear_label():
    with pytest.raises(ValidationError):
        _analysis("unclear")


def test_parallel_eval_preserves_input_order_and_categorical_metrics(monkeypatch):
    records = [
        {
            "title": "slow-pass",
            "company": "A",
            "description": "desc",
            "_human_classification": "remote",
            "_human_travel_days": 8,
            "dedup_hash": "aaaa1111",
        },
        {
            "title": "fast-fn",
            "company": "B",
            "description": "desc",
            "_human_classification": "remote",
            "_human_travel_days": 2,
            "_human_policy": "remote",
            "dedup_hash": "bbbb2222",
        },
        {
            "title": "medium-fp",
            "company": "C",
            "description": "desc",
            "_human_classification": "hybrid",
            "_human_policy": "hybrid",
            "dedup_hash": "cccc3333",
        },
    ]

    def fake_analyze_remote(rf_input, **kwargs):
        assert isinstance(rf_input, RemoteFilterInput)
        assert set(kwargs) == {"llm_config", "usage_callback"}
        kwargs["usage_callback"](
            {"input_tokens": 100, "cached_input_tokens": 25, "output_tokens": 10}
        )
        delays = {"slow-pass": 0.03, "fast-fn": 0.0, "medium-fp": 0.01}
        time.sleep(delays[rf_input.title])
        if rf_input.title == "fast-fn":
            return _analysis("hybrid", travel_days=5)
        return _analysis("remote", travel_days=5)

    monkeypatch.setattr(eval_core, "analyze_remote", fake_analyze_remote)

    mismatches, metrics_input, prompt_hashes = eval_core.run_eval(
        records,
        _config(),
        run_id="test_run",
        workers=3,
    )
    metrics = eval_core.assemble_metrics(metrics_input)["metrics"]

    assert metrics_input.preds == ["remote", "hybrid", "remote"]
    assert metrics_input.golds == ["remote", "remote", "hybrid"]
    assert metrics_input.token_totals == {
        "input_tokens": 300,
        "cached_input_tokens": 75,
        "output_tokens": 30,
    }
    assert metrics["evaluated"] == 3
    assert metrics["skipped"] == 0
    assert metrics["confusion"] == [
        [1, 1, 0],
        [1, 0, 0],
        [0, 0, 0],
    ]
    assert metrics["travel_mae"] == 3.0
    assert metrics["travel_n"] == 2
    assert metrics["travel_gold_n"] == 2
    assert metrics["travel_pred_n"] == 3
    assert metrics["travel_coverage"] == 1.0
    assert metrics["travel_spurious_rate"] == pytest.approx(1 / 3)
    assert [m.record_id for m in mismatches] == ["bbbb2222", "cccc3333"]
    assert [h.dedup_hash for h in prompt_hashes] == [
        "aaaa1111",
        "bbbb2222",
        "cccc3333",
    ]
    assert all(len(h.resolved_user_message_hash) == 12 for h in prompt_hashes)


def test_assemble_metrics_counts_asymmetric_travel_presence():
    results = [
        eval_core.RecordEvalResult(
            index=0,
            job={"title": "both-present"},
            gold_classification="remote",
            pred_classification="remote",
            gold_travel_days=10,
            pred_travel_days=12,
            reason="both",
            elapsed=0.0,
        ),
        eval_core.RecordEvalResult(
            index=1,
            job={"title": "gold-only"},
            gold_classification="remote",
            pred_classification="remote",
            gold_travel_days=5,
            pred_travel_days=None,
            reason="missed travel",
            elapsed=0.0,
        ),
        eval_core.RecordEvalResult(
            index=2,
            job={"title": "pred-only"},
            gold_classification="remote",
            pred_classification="remote",
            gold_travel_days=None,
            pred_travel_days=7,
            reason="spurious travel",
            elapsed=0.0,
        ),
    ]

    metrics_input = eval_core._metrics_input_from_results(results)
    metrics = eval_core.assemble_metrics(metrics_input)["metrics"]

    assert metrics_input.gold_travel_days == [10]
    assert metrics_input.pred_travel_days == [12]
    assert metrics["travel_mae"] == 2.0
    assert metrics["travel_n"] == 1
    assert metrics["travel_gold_n"] == 2
    assert metrics["travel_pred_n"] == 2
    assert metrics["travel_coverage"] == 0.5
    assert metrics["travel_spurious_rate"] == 0.5


def test_assemble_metrics_fails_fast_on_misaligned_travel_lists():
    misaligned = eval_core.EvalMetricsInput(
        preds=["remote"],
        golds=["remote"],
        pred_travel_days=[10, 20],
        gold_travel_days=[10],
    )
    with pytest.raises(ValueError, match="pred_travel_days and gold_travel_days"):
        eval_core.assemble_metrics(misaligned)


def test_token_total_helpers_default_and_aggregate_shape():
    assert empty_token_totals() == {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
    }
    assert aggregate_token_totals(
        [
            {"input_tokens": 100, "cached_input_tokens": 25, "output_tokens": 10},
            {"input_tokens": 7, "output_tokens": 3},
        ]
    ) == {
        "input_tokens": 107,
        "cached_input_tokens": 25,
        "output_tokens": 13,
    }


def test_percentile_and_latency_summary_helpers():
    assert percentile([], 95) is None
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert latency_summary([0.1, 0.2, 0.3]) == {
        "latency_n": 3,
        "latency_avg_s": pytest.approx(0.2),
        "latency_p95_s": 0.3,
    }
    with pytest.raises(ValueError, match="percentile must be between 0 and 100"):
        percentile([1.0], 101)


def test_build_cost_summary_reports_cost_per_correct_for_openai():
    metrics = eval_core.assemble_metrics(
        eval_core.EvalMetricsInput(
            preds=["remote", "remote"],
            golds=["remote", "hybrid"],
            token_totals={
                "input_tokens": 1000,
                "cached_input_tokens": 0,
                "output_tokens": 200,
            },
        )
    )["metrics"]

    cost = build_cost_summary(
        {"llm": {"provider": "openai", "model": "gpt-4o-mini"}},
        metrics,
        {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 200},
    )

    assert cost["correct"] == 1
    assert cost["estimated_cost_usd"] == pytest.approx(0.00027)
    assert cost["estimated_cost_per_record_usd"] == pytest.approx(0.000135)
    assert cost["estimated_cost_per_correct_usd"] == pytest.approx(0.00027)
    assert cost["pricing_note"] == "openai_list_price_estimate"


def test_build_cost_summary_treats_local_provider_as_zero_api_cost():
    metrics = eval_core.assemble_metrics(
        eval_core.EvalMetricsInput(preds=["remote"], golds=["remote"])
    )["metrics"]

    cost = build_cost_summary(
        {"llm": {"provider": "ollama", "model": "qwen-27b-mtp"}},
        metrics,
        {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20},
    )

    assert cost["estimated_cost_usd"] == 0.0
    assert cost["estimated_cost_per_correct_usd"] == 0.0
    assert cost["breakdown"] is None
    assert cost["pricing_note"] == "local_provider_zero_api_cost"


def test_build_cost_summary_reports_missing_openai_pricing_without_crashing():
    metrics = eval_core.assemble_metrics(
        eval_core.EvalMetricsInput(preds=["remote"], golds=["remote"])
    )["metrics"]

    cost = build_cost_summary(
        {"llm": {"provider": "openai", "model": "gpt-imaginary"}},
        metrics,
        {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20},
    )

    assert cost["estimated_cost_usd"] is None
    assert cost["estimated_cost_per_record_usd"] is None
    assert cost["estimated_cost_per_correct_usd"] is None
    assert cost["breakdown"] is None
    assert cost["pricing_note"] == "missing_openai_pricing_entry"


def test_eval_main_persists_top_level_cost_tokens_and_timing(monkeypatch, tmp_path):
    class CapturingRunLogger:
        def __init__(self):
            self.records = []

        def log_run(self, record):
            self.records.append(record)

    gold_file = tmp_path / "gold.jsonl"
    gold_file.write_text(
        '{"title":"A","description":"desc","_human_classification":"remote"}\n'
    )
    config_file = tmp_path / "remote_agent.yml"
    config_file.write_text(
        "llm:\n  provider: openai\n  model: gpt-5.4-mini\n  temperature: 0.0\n"
    )
    logger = CapturingRunLogger()

    def fake_run_eval(records, config, run_id, workers=1):
        return (
            [],
            eval_core.EvalMetricsInput(
                preds=["remote"],
                golds=["remote"],
                elapsed_seconds=[0.25, 0.50],
                token_totals={
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 200,
                },
            ),
            [],
        )

    monkeypatch.setattr(eval_script, "run_eval", fake_run_eval)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_remote_filter_eval.py",
            "--gold",
            str(gold_file),
            "--config",
            str(config_file),
            "--runs-file",
            str(tmp_path / "runs.jsonl"),
            "--model",
            "gpt-4o-mini",
            "--run-id",
            "record-test",
            "--no-mismatches",
        ],
    )

    eval_script.main(run_logger=logger)

    record = logger.records[0]
    assert record["run_id"].startswith("record-test_")
    assert record["token_totals"] == {
        "input_tokens": 1000,
        "cached_input_tokens": 0,
        "output_tokens": 200,
    }
    assert record["cost"]["estimated_cost_usd"] == pytest.approx(0.00027)
    assert record["cost"]["estimated_cost_per_correct_usd"] == pytest.approx(0.00027)
    assert record["cost"]["pricing_note"] == "openai_list_price_estimate"
    assert record["metrics"]["latency_avg_s"] == pytest.approx(0.375)
    assert record["metrics"]["latency_p95_s"] == 0.50


def test_print_report_renders_empty_travel_rates_as_na(capsys):
    metrics = eval_core.assemble_metrics(
        eval_core.EvalMetricsInput(preds=["remote"], golds=["remote"])
    )

    eval_script.print_report(metrics, [], "test_run")

    out = capsys.readouterr().out
    assert "Travel coverage   : n/a  (0/0 gold-travel rows populated)" in out
    assert "Travel spurious   : n/a  (0/0 model-travel rows gold-None)" in out


def test_run_eval_fails_fast_on_retired_unclear_human_classification(monkeypatch):
    calls = 0

    def fake_analyze_remote(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _analysis("remote")

    monkeypatch.setattr(eval_core, "analyze_remote", fake_analyze_remote)

    records = [
        {
            "title": "retired unclear label",
            "description": "desc",
            "_human_classification": "unclear",
        },
    ]

    with pytest.raises(ValueError, match="invalid _human_classification.*unclear"):
        eval_core.run_eval(records, _config(), "test_run", workers=2)

    assert calls == 0


def test_run_eval_counts_missing_description_as_skipped_without_inference(monkeypatch):
    calls = 0

    def fake_analyze_remote(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _analysis("remote")

    monkeypatch.setattr(eval_core, "analyze_remote", fake_analyze_remote)

    records = [
        {
            "title": "missing description",
            "description": "",
            "_human_classification": "remote",
        },
    ]

    mismatches, metrics_input, prompt_hashes = eval_core.run_eval(
        records, _config(), "test_run", workers=2
    )

    assert mismatches == []
    assert metrics_input == eval_core.EvalMetricsInput(
        skipped=1,
        skip_reasons={"missing_description": 1},
        token_totals={
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
    )
    assert prompt_hashes == []
    assert calls == 0


def test_eval_uses_remote_filter_input_and_records_resolved_prompt_hash(monkeypatch):
    monkeypatch.setattr(eval_core, "USER_TIMEZONE", "Europe/Oslo")
    captured_inputs = []

    def fake_analyze_remote(rf_input, **kwargs):
        captured_inputs.append(rf_input)
        assert set(kwargs) == {"llm_config", "usage_callback"}
        kwargs["usage_callback"](
            {"input_tokens": 123, "cached_input_tokens": 23, "output_tokens": 45}
        )
        return _analysis("remote")

    monkeypatch.setattr(eval_core, "analyze_remote", fake_analyze_remote)

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
            "_human_classification": "hybrid",
            "_human_policy": "remote_policy",
            "dedup_hash": "dddd4444eeee",
        }
    ]

    mismatches, metrics_input, prompt_hashes = eval_core.run_eval(
        records,
        _config(),
        run_id="test_run",
    )
    metrics = eval_core.assemble_metrics(metrics_input)["metrics"]

    assert metrics_input.preds == ["remote"]
    assert metrics_input.golds == ["hybrid"]
    assert metrics["confusion"] == [
        [0, 1, 0],
        [0, 0, 0],
        [0, 0, 0],
    ]
    assert metrics["travel_gold_n"] == 0
    assert metrics["travel_pred_n"] == 0
    assert metrics["travel_coverage"] is None
    assert metrics["travel_spurious_rate"] is None
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
    assert prompt_hashes[0].dedup_hash == "dddd4444eeee"
    assert mismatches[0].resolved_user_message_hash == expected_hash
