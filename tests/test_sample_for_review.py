import json
from pathlib import Path

import pytest

from scripts.sample_for_review import create_review_sample


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_sample_for_review_uses_production_classified_records(tmp_path):
    source = tmp_path / "classified.jsonl"
    output = tmp_path / "to_review.jsonl"
    gold = tmp_path / "ground_truth.jsonl"
    write_jsonl(
        source,
        [
            {
                "dedup_hash": "already-reviewed",
                "title": "Reviewed",
                "_remote_analysis": {"remote_classification": "remote"},
            },
            {
                "dedup_hash": "eligible",
                "title": "Eligible",
                "_remote_analysis": {"remote_classification": "hybrid"},
            },
            {
                "dedup_hash": "no-analysis",
                "title": "No analysis",
            },
        ],
    )
    write_jsonl(gold, [{"dedup_hash": "already-reviewed"}])

    sample = create_review_sample(source, output, n=10, gold_path=gold, seed=1)

    assert [record["dedup_hash"] for record in sample] == ["eligible"]
    written = [json.loads(line) for line in output.read_text().splitlines()]
    assert written == sample


def test_sample_for_review_warns_and_skips_classified_record_without_stable_key(
    tmp_path, caplog
):
    source = tmp_path / "classified.jsonl"
    output = tmp_path / "to_review.jsonl"
    gold = tmp_path / "ground_truth.jsonl"
    write_jsonl(
        source,
        [
            {
                "title": "No stable key",
                "_remote_analysis": {"remote_classification": "remote"},
            },
            {
                "dedup_hash": "eligible",
                "title": "Eligible",
                "_remote_analysis": {"remote_classification": "remote"},
            },
        ],
    )

    sample = create_review_sample(source, output, n=1, gold_path=gold)

    assert [record["dedup_hash"] for record in sample] == ["eligible"]
    assert "without a stable dedup key" in caplog.text


def test_sample_for_review_warns_on_keyed_record_missing_analysis(tmp_path, caplog):
    source = tmp_path / "classified.jsonl"
    output = tmp_path / "to_review.jsonl"
    gold = tmp_path / "ground_truth.jsonl"
    write_jsonl(
        source,
        [
            {
                "dedup_hash": "no-analysis",
                "title": "Keyed but no analysis",
                "company": "ExampleCo",
            },
            {
                "dedup_hash": "eligible",
                "title": "Eligible",
                "_remote_analysis": {"remote_classification": "remote"},
            },
        ],
    )

    with caplog.at_level("WARNING"):
        sample = create_review_sample(source, output, n=10, gold_path=gold, seed=1)

    # The malformed row is excluded but surfaced loudly, not dropped silently.
    assert [record["dedup_hash"] for record in sample] == ["eligible"]
    assert "missing _remote_analysis" in caplog.text
    assert "Keyed but no analysis @ ExampleCo" in caplog.text


def test_sample_for_review_names_missing_analysis_rows_when_none_are_eligible(tmp_path):
    source = tmp_path / "classified.jsonl"
    output = tmp_path / "to_review.jsonl"
    gold = tmp_path / "ground_truth.jsonl"
    write_jsonl(
        source,
        [{"dedup_hash": "no-analysis", "title": "No analysis", "company": "AcmeCo"}],
    )

    with pytest.raises(ValueError, match="missing _remote_analysis: #1 No analysis"):
        create_review_sample(source, output, n=1, gold_path=gold)


def test_sample_for_review_names_missing_key_rows_when_none_are_eligible(tmp_path):
    source = tmp_path / "classified.jsonl"
    output = tmp_path / "to_review.jsonl"
    gold = tmp_path / "ground_truth.jsonl"
    write_jsonl(
        source,
        [
            {
                "title": "No stable key",
                "company": "ExampleCo",
                "_remote_analysis": {"remote_classification": "remote"},
            }
        ],
    )

    with pytest.raises(ValueError, match="No stable key @ ExampleCo"):
        create_review_sample(source, output, n=1, gold_path=gold)


def test_sample_for_review_fails_when_no_classified_records(tmp_path):
    source = tmp_path / "classified.jsonl"
    output = tmp_path / "to_review.jsonl"
    gold = tmp_path / "ground_truth.jsonl"
    write_jsonl(source, [{"dedup_hash": "no-analysis"}])

    with pytest.raises(ValueError, match="No eligible records"):
        create_review_sample(source, output, n=1, gold_path=gold)
