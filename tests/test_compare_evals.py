import json

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
) -> dict:
    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "config": {"model": model, "temperature": 0.0},
        "metrics": {
            "labels": ["remote", "hybrid", "onsite", "unclear"],
            "evaluated": 10,
            "skipped": 1,
            "total": 11,
            "confusion": {"remote": {"remote": 4, "hybrid": 1}},
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

    assert compare_evals.detect_eval_type(categorical) == "remote_filter_categorical"
    assert compare_evals.detect_eval_type(legacy_binary) == "remote_filter"
    assert compare_evals.detect_eval_type(ordinal) == "skills_fit"


def test_flatten_remote_filter_categorical_extracts_headline_metrics() -> None:
    row = compare_evals._flatten_remote_filter_categorical(_categorical_run())

    assert row["run_id"] == "cat-a"
    assert row["date"] == "2025-01-02"
    assert row["model"] == "gpt-4o-mini"
    assert row["temperature"] == 0.0
    assert row["total"] == 11
    assert row["skipped"] == 1
    assert row["micro_acc"] == 0.75
    assert row["remote_recall"] == 0.8
    assert row["macro_f1"] == 0.7
    assert row["travel_mae"] is None


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
    assert "↑ +0.1000" in diff
