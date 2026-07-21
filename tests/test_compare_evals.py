import json

import pytest

from agent_eval import bakeoff, run_compare
from scripts import compare_evals


def _categorical_run(
    run_id: str = "cat-a",
    *,
    timestamp: str = "2025-01-02T03:04:05Z",
    model: str = "gpt-4o-mini",
    micro_accuracy: float = 0.75,
    remote_recall: float = 0.8,
    macro_f1: float = 0.7,
    travel_mae: float | None = None,
    estimated_cost_usd: float | None = None,
    estimated_cost_per_correct_usd: float | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "config": {"model": model, "temperature": 0.0},
        "gold_hash": "gold-123",
        "prompt_hash": "prompt-123",
        "cost": {
            "estimated_cost_usd": estimated_cost_usd,
            "estimated_cost_per_correct_usd": estimated_cost_per_correct_usd,
        },
        "metrics": {
            "labels": ["remote", "hybrid", "onsite", "unclear"],
            "evaluated": 10,
            "skipped": 1,
            "total": 11,
            "confusion": [
                [4, 1, 0, 0],
                [1, 2, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            "per_class": {
                "remote": {
                    "precision": 0.9,
                    "recall": remote_recall,
                    "f1": 0.85,
                    "support": 5,
                },
            },
            "macro_precision": 0.72,
            "macro_recall": 0.69,
            "macro_f1": macro_f1,
            "micro_accuracy": micro_accuracy,
            "travel_mae": travel_mae,
            "travel_n": 0 if travel_mae is None else 3,
        },
    }


def test_detect_eval_type_disambiguates_supported_metric_families() -> None:
    categorical = _categorical_run()
    legacy_binary = {
        "metrics": {
            "total": 3,
            "accuracy": 0.67,
            "precision": 0.5,
            "recall": 1.0,
            "f1": 0.67,
        }
    }
    ordinal = {"metrics": {"total": 3, "exact_match_acc": 0.5}}

    assert run_compare.detect_eval_type(categorical) == "remote_filter_categorical"
    assert run_compare.detect_eval_type(legacy_binary) == "remote_filter"
    assert run_compare.detect_eval_type(ordinal) == "skills_fit"


def test_detect_eval_type_returns_unknown_for_ambiguous_metrics() -> None:
    # A drifted record carrying both `accuracy` and `micro_accuracy` matches two
    # detectors — resolve to "unknown" instead of letting registry order decide.
    ambiguous = {"metrics": {"total": 3, "accuracy": 0.5, "micro_accuracy": 0.8}}
    assert run_compare.detect_eval_type(ambiguous) == "unknown"


def test_flatten_remote_filter_categorical_fails_fast_on_missing_headline() -> None:
    missing_macro = _categorical_run()
    del missing_macro["metrics"]["macro_f1"]
    with pytest.raises(ValueError, match="macro_f1"):
        run_compare.flatten_remote_filter_categorical(missing_macro)

    missing_recall = _categorical_run()
    del missing_recall["metrics"]["per_class"]["remote"]["recall"]
    with pytest.raises(ValueError, match=r"per_class\.remote\.recall"):
        run_compare.flatten_remote_filter_categorical(missing_recall)


def test_flatten_remote_filter_categorical_extracts_headline_metrics() -> None:
    row = run_compare.flatten_remote_filter_categorical(_categorical_run())

    assert row["run_id"] == "cat-a"
    assert row["date"] == "2025-01-02"
    assert row["model"] == "gpt-4o-mini"
    assert row["temperature"] == 0.0
    assert row["total"] == 11
    assert row["skipped"] == 1
    assert row["micro_acc"] == 0.75
    assert row["remote_recall"] == 0.8
    assert row["remote_fn"] == 1
    assert row["remote_fp"] == 1
    assert row["macro_f1"] == 0.7
    assert row["travel_mae"] is None
    assert row["est_cost"] is None
    assert row["cost_per_correct"] is None


def test_bakeoff_comparable_guard_fails_fast_on_mixed_prompt_hash() -> None:
    runs = [_categorical_run("a"), _categorical_run("b")]
    runs[1]["prompt_hash"] = "different-prompt"

    with pytest.raises(ValueError, match="mixed prompt_hash"):
        bakeoff.ensure_bakeoff_comparable(runs)


def test_bakeoff_render_rows_are_sorted_and_champion_marked() -> None:
    rows = [
        run_compare.flatten_remote_filter_categorical(
            _categorical_run(
                "expensive",
                estimated_cost_usd=0.20,
                estimated_cost_per_correct_usd=0.01,
            )
        ),
        run_compare.flatten_remote_filter_categorical(
            _categorical_run(
                "cheap",
                estimated_cost_usd=0.05,
                estimated_cost_per_correct_usd=0.002,
            )
        ),
    ]

    rendered = bakeoff.build_bakeoff_render_rows(rows, champion_run_id="expensive")

    assert [row["run_id"] for row in rendered] == ["cheap", "expensive"]
    assert rendered[1]["champion"] == "*"
    assert rendered[0]["cost_per_correct"] == "$0.002000"


def test_bakeoff_renders_cost_table_sorted_by_cost_per_correct(
    tmp_path, monkeypatch, capsys
) -> None:
    runs_file = tmp_path / "runs.jsonl"
    runs = [
        _categorical_run(
            "expensive",
            timestamp="2025-01-02T03:04:05Z",
            model="gpt-5.6-luna",
            estimated_cost_usd=0.20,
            estimated_cost_per_correct_usd=0.01,
        ),
        _categorical_run(
            "cheap",
            timestamp="2025-01-03T03:04:05Z",
            model="gpt-5.4-nano",
            estimated_cost_usd=0.05,
            estimated_cost_per_correct_usd=0.002,
        ),
    ]
    runs_file.write_text("\n".join(json.dumps(run) for run in runs) + "\n")
    monkeypatch.setattr(
        compare_evals, "load_champions", lambda: {"remote_filter": "expensive"}
    )
    monkeypatch.setattr(
        "sys.argv",
        ["compare_evals.py", "--runs-file", str(runs_file), "--bakeoff", "--last", "2"],
    )

    compare_evals.main()

    out = capsys.readouterr().out
    assert "[remote_filter_bakeoff]" in out
    assert "$0.002000" in out
    assert "$0.010000" in out
    assert out.index("cheap") < out.index("expensive")
    assert "*" in out


def test_categorical_last_and_diff_render_against_runs_fixture(
    tmp_path, monkeypatch, capsys
) -> None:
    runs_file = tmp_path / "runs.jsonl"
    runs = [
        _categorical_run("cat-a", travel_mae=None),
        _categorical_run(
            "cat-b",
            timestamp="2025-01-03T03:04:05Z",
            model="gpt-5.4-mini",
            micro_accuracy=0.85,
            remote_recall=0.9,
            macro_f1=0.82,
            travel_mae=1.25,
        ),
    ]
    runs_file.write_text("\n".join(json.dumps(run) for run in runs) + "\n")

    monkeypatch.setattr(
        "sys.argv", ["compare_evals.py", "--runs-file", str(runs_file), "--last", "2"]
    )
    compare_evals.main()
    summary = capsys.readouterr().out
    assert "[remote_filter_categorical]" in summary
    assert "cat-a" in summary
    assert "cat-b" in summary
    assert "—" in summary

    monkeypatch.setattr(
        "sys.argv",
        ["compare_evals.py", "--runs-file", str(runs_file), "--diff", "cat-a", "cat-b"],
    )
    compare_evals.main()
    diff = capsys.readouterr().out
    assert "micro_acc" in diff
    assert "remote_recall" in diff
    assert "macro_f1" in diff
    # travel_mae is a displayed metric — it must also be diffable, incl. the
    # None→"—" case (cat-a travel_mae=None, cat-b=1.25).
    assert "travel_mae" in diff
    assert "—" in diff
    assert "↑ +0.1000" in diff
