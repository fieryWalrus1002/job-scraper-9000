"""Fixture tests for the local companies calibration audit."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.calibrate_companies_prefilter import (
    audit_user_runs,
    parse_scored_labels_jsonl,
    run,
)


class FakeEmbeddingClient:
    """Deterministic OpenAI-compatible fake that never performs network I/O."""

    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    @property
    def embeddings(self) -> FakeEmbeddingClient:
        return self

    def create(self, *, model: str, input: list[str]) -> SimpleNamespace:  # noqa: A002
        self.requests.append(input)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=self.vector(text)) for text in input]
        )

    @staticmethod
    def vector(text: str) -> list[float]:
        text = text.lower()
        if "junk job" in text:
            return [0.0, 1.0]
        if "good job" in text or "target job titles" in text:
            return [1.0, 0.0]
        return [0.5, 0.5]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def posting(dedup_hash: str, *, title: str = "Data engineer") -> dict[str, object]:
    return {
        "dedup_hash": dedup_hash,
        "title": title,
        "company": "Example Co",
        "description": "Build data systems.",
    }


def scored(
    dedup_hash: str,
    fit_score: int | None,
    *,
    model: str = "gpt-4.1-mini",
    run_id: str = "run-1",
) -> dict[str, object]:
    ai_fit: dict[str, object] | None
    if fit_score is None:
        ai_fit = None
    else:
        ai_fit = {"fit_score": fit_score}
    return {
        "dedup_hash": dedup_hash,
        "ai_fit": ai_fit,
        "metadata": {
            "profile_version": "2026-04-01",
            "provider": "openai",
            "model": model,
            "scored_at": "2026-04-01T12:00:00+00:00",
            "run_id": run_id,
        },
    }


def make_run(
    tmp_path: Path,
    run_id: str,
    raw_rows: list[dict[str, object]],
    scored_rows: list[dict[str, object]],
) -> Path:
    user_dir = tmp_path / run_id / "magnus"
    write_jsonl(user_dir / "scrape" / "companies.jsonl", raw_rows)
    write_jsonl(user_dir / "skills_fit" / "scored.jsonl", scored_rows)
    return user_dir


def test_join_counts_only_labels_in_the_raw_companies_pool(tmp_path: Path) -> None:
    make_run(
        tmp_path,
        "run-1",
        [posting("raw-only"), posting("matched"), posting("also-raw")],
        [scored("matched", 4), scored("scored-only", 1)],
    )

    report = audit_user_runs(tmp_path, "magnus")

    run_report = report["runs"][0]
    assert run_report["raw"] == 3
    assert run_report["labeled"] == 1
    assert run_report["good"] == 1
    assert run_report["selection_bias_coverage"] == pytest.approx(1 / 3)
    assert report["totals"]["selection_bias_coverage"] == pytest.approx(1 / 3)


def test_buckets_good_junk_and_failure_shapes(tmp_path: Path) -> None:
    null_fit_score = scored("null-score", 3)
    null_fit_score["ai_fit"] = {"fit_score": None}
    make_run(
        tmp_path,
        "run-1",
        [
            posting(value)
            for value in ("good", "junk", "neutral", "null-ai", "null-score")
        ],
        [
            scored("good", 4),
            scored("junk", 2),
            scored("neutral", 3),
            scored("null-ai", None),
            null_fit_score,
        ],
    )

    report = audit_user_runs(tmp_path, "magnus")

    run_report = report["runs"][0]
    assert run_report["labeled"] == 5
    assert run_report["good"] == 1
    assert run_report["junk"] == 1
    assert run_report["failures"] == 2


def test_provenance_models_are_separate_compatible_cohorts(tmp_path: Path) -> None:
    make_run(
        tmp_path,
        "run-1",
        [posting("one"), posting("two")],
        [scored("one", 4, model="model-a"), scored("two", 1, model="model-b")],
    )

    report = audit_user_runs(tmp_path, "magnus")

    cohorts = report["cohorts"]
    assert len(cohorts) == 2
    assert {(cohort["model"], cohort["labeled"]) for cohort in cohorts} == {
        ("model-a", 1),
        ("model-b", 1),
    }


def test_cohort_reports_chronological_holdout_feasibility(tmp_path: Path) -> None:
    later = scored("two", 4)
    later["metadata"]["scored_at"] = "2026-04-02T12:00:00+00:00"
    make_run(tmp_path, "run-1", [posting("one")], [scored("one", 4)])
    make_run(tmp_path, "run-2", [posting("two")], [later])

    report = audit_user_runs(tmp_path, "magnus")

    cohort = report["cohorts"][0]
    assert cohort["distinct_run_count"] == 2
    assert cohort["min_scored_at"] == "2026-04-01T12:00:00+00:00"
    assert cohort["max_scored_at"] == "2026-04-02T12:00:00+00:00"
    assert cohort["holdout_feasible"] is True


@pytest.mark.parametrize(
    ("labeled", "good", "expected"),
    [
        (299, 100, "insufficient"),
        (300, 99, "insufficient"),
        (300, 100, "shadow_eligible"),
        (1000, 300, "auto_switch_candidate"),
    ],
)
def test_eligibility_threshold_boundaries(
    tmp_path: Path, labeled: int, good: int, expected: str
) -> None:
    hashes = [f"job-{index}" for index in range(labeled)]
    make_run(
        tmp_path,
        "run-1",
        [posting(dedup_hash) for dedup_hash in hashes],
        [
            scored(dedup_hash, 4 if index < good else 3)
            for index, dedup_hash in enumerate(hashes)
        ],
    )

    report = audit_user_runs(tmp_path, "magnus")

    assert report["eligibility"]["verdict"] == expected


@pytest.mark.parametrize(
    "row",
    [
        {"ai_fit": None, "metadata": {}},
        {
            "dedup_hash": "bad-score",
            "ai_fit": {"fit_score": "four"},
            "metadata": {
                "profile_version": "2026-04-01",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "scored_at": "2026-04-01T12:00:00+00:00",
            },
        },
    ],
)
def test_malformed_scored_rows_raise_with_path(
    tmp_path: Path, row: dict[str, object]
) -> None:
    path = tmp_path / "scored.jsonl"
    write_jsonl(path, [row])

    with pytest.raises(ValueError, match=str(path)):
        parse_scored_labels_jsonl(path.read_text(encoding="utf-8"), path)


def test_cli_writes_json_and_prints_human_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_run(tmp_path, "run-1", [posting("one")], [scored("one", 4)])
    json_out = tmp_path / "audit.json"

    run(SimpleNamespace(runs_root=tmp_path, user_slug="magnus", json_out=json_out))

    assert json.loads(json_out.read_text(encoding="utf-8"))["totals"]["raw"] == 1
    assert "Per-run selection-bias coverage" in capsys.readouterr().out


def scoring_args(tmp_path: Path, *, reference_mode: list[str]) -> SimpleNamespace:
    profile = tmp_path / "profile.yml"
    profile.write_text(
        "summary: Data engineer\ncore_skills: [Python]\nadjacent_skills: []\npreferred_domains: []\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        runs_root=tmp_path / "runs",
        user_slug="magnus",
        json_out=tmp_path / "audit.json",
        score=True,
        reference_mode=reference_mode,
        profile=profile,
        target_title=["Data Engineer"],
        goal_summary="",
        provider="ollama",
        model="fake-embed",
        base_url="http://fake-ollama:11434/v1",
        prefix_scheme="nomic",
        cache=tmp_path / "cache.jsonl",
        curve_output_dir=tmp_path / "curves",
        cut_depths="10,15,20,25,30,35,40,45,50,55,60,65,70",
        embedding_batch_size=100,
        allow_ground_truth_reference=False,
    )


def make_eligible_scoring_run(tmp_path: Path) -> None:
    good_hashes = [f"good-{index}" for index in range(100)]
    junk_hashes = [f"junk-{index}" for index in range(200)]
    make_run(
        tmp_path / "runs",
        "run-1",
        [
            *[posting(dedup_hash, title="Good Job") for dedup_hash in good_hashes],
            *[posting(dedup_hash, title="Junk Job") for dedup_hash in junk_hashes],
        ],
        [
            *[scored(dedup_hash, 4) for dedup_hash in good_hashes],
            *[scored(dedup_hash, 1) for dedup_hash in junk_hashes],
        ],
    )


def test_scoring_emits_independent_curves_and_reuses_cache(tmp_path: Path) -> None:
    make_eligible_scoring_run(tmp_path)
    args = scoring_args(tmp_path, reference_mode=["blend", "keywords"])

    first = FakeEmbeddingClient()
    report = run(args, embedding_client=first)

    scoring = report["scoring"]
    assert scoring["eligible_cohort_count"] == 1
    curves = scoring["curves"]
    assert {curve["reference_mode"] for curve in curves} == {"blend", "keywords"}
    assert all(Path(curve["curve_csv"]).is_file() for curve in curves)
    for curve in curves:
        rows = curve["curve"]
        assert [row["good_lost"] for row in rows] == sorted(
            row["good_lost"] for row in rows
        )
    blend_rows = next(
        curve["curve"] for curve in curves if curve["reference_mode"] == "blend"
    )
    assert blend_rows[0]["jobs_cut"] == 30
    assert blend_rows[0]["dropped_purity"] == pytest.approx(1.0)
    blend_summary = next(
        summary
        for summary in scoring["summaries"]
        if summary["reference_mode"] == "blend"
    )
    assert blend_summary["max_cut_pct"] == 65
    max_cut_row = next(
        row
        for row in blend_rows
        if row["cut_depth_pct"] == blend_summary["max_cut_pct"]
    )
    next_row = next(
        row
        for row in blend_rows
        if row["cut_depth_pct"] == blend_summary["max_cut_pct"] + 5
    )
    assert max_cut_row["good_lost_pct"] <= 0.07
    assert next_row["good_lost_pct"] > 0.07
    assert first.requests

    second = FakeEmbeddingClient()
    run(args, embedding_client=second)

    assert second.requests == []


def test_exemplar_mode_refuses_without_its_gate(tmp_path: Path) -> None:
    make_eligible_scoring_run(tmp_path)
    args = scoring_args(tmp_path, reference_mode=["exemplar"])

    with pytest.raises(ValueError, match="allow-ground-truth-reference"):
        run(args, embedding_client=FakeEmbeddingClient())
