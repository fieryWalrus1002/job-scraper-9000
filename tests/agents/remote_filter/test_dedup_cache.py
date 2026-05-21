import json
from pathlib import Path
from unittest.mock import patch

from agents.remote_filter.cache import AnalysisCache
from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.runner import run_remote_filter
from agents.remote_filter.utils import dedup_jobs


FILTER_METADATA = {
    "schema_version": "2.0.0",
    "prompt_hash": "promptH",
    "prompt_file": "system_prompt.txt",
    "commit": "abc123",
    "dirty": False,
    "filtered_at": "2026-05-21T00:00:00Z",
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
  travel:
    max_estimated_days_per_year: 15
    prohibited_categories:
      - remote_with_frequent_travel
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


# ---------------------------------------------------------------------------
# dedup_jobs helper
# ---------------------------------------------------------------------------


def test_dedup_jobs_drops_duplicate_dedup_hash():
    jobs = [
        _job(source_job_id="1", dedup_hash="hashA"),
        _job(source_job_id="2", dedup_hash="hashA"),
        _job(source_job_id="3", dedup_hash="hashB"),
    ]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 1
    assert [j["source_job_id"] for j in deduped] == ["1", "3"]


def test_dedup_jobs_falls_back_to_source_job_id_when_no_dedup_hash():
    jobs = [
        _job(source_job_id="X", dedup_hash=""),
        _job(source_job_id="X", dedup_hash=""),
        _job(source_job_id="Y", dedup_hash=""),
    ]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 1
    assert [j["source_job_id"] for j in deduped] == ["X", "Y"]


def test_dedup_jobs_passes_through_jobs_missing_both_keys():
    jobs = [_job(source_job_id="", dedup_hash=""), _job(source_job_id="", dedup_hash="")]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 0
    assert len(deduped) == 2


# ---------------------------------------------------------------------------
# AnalysisCache
# ---------------------------------------------------------------------------


def test_analysis_cache_miss_then_hit_via_jsonl_roundtrip(tmp_path):
    cache_path = tmp_path / "cache.jsonl"
    cache = AnalysisCache(cache_path)
    assert cache.get("hashA", "p1", "gpt-4o-mini") is None

    analysis = _analysis("fully_remote")
    cache.put("hashA", "p1", "gpt-4o-mini", analysis)

    reopened = AnalysisCache(cache_path)
    hit = reopened.get("hashA", "p1", "gpt-4o-mini")
    assert hit is not None
    assert hit.remote_classification == "fully_remote"


def test_analysis_cache_changes_key_when_prompt_or_model_changes(tmp_path):
    cache_path = tmp_path / "cache.jsonl"
    cache = AnalysisCache(cache_path)
    cache.put("hashA", "p1", "gpt-4o-mini", _analysis("fully_remote"))

    assert cache.get("hashA", "p2", "gpt-4o-mini") is None  # prompt changed
    assert cache.get("hashA", "p1", "gpt-4o") is None  # model changed
    assert cache.get("hashA", "p1", "gpt-4o-mini") is not None


# ---------------------------------------------------------------------------
# Runner integration: within-batch dedup + across-batch cache
# ---------------------------------------------------------------------------


def test_run_remote_filter_collapses_within_batch_duplicates(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(
        input_path,
        [
            _job(source_job_id="1", dedup_hash="dupHash"),
            _job(source_job_id="2", dedup_hash="dupHash"),
            _job(source_job_id="3", dedup_hash="uniqueHash"),
        ],
    )

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        side_effect=[_analysis("fully_remote"), _analysis("fully_remote")],
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    assert mock_analyze.call_count == 2
    assert counts["input_total"] == 3
    assert counts["deduped"] == 1
    assert counts["total"] == 2
    assert counts["cache_misses"] == 2
    assert counts["cache_hits"] == 0


def test_run_remote_filter_serves_across_batch_cache_hits(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(
        input_path,
        [
            _job(source_job_id="1", dedup_hash="hashA", title="A"),
            _job(source_job_id="2", dedup_hash="hashB", title="B"),
        ],
    )

    # Prime the cache with hashA only; hashB must hit the LLM.
    seed = AnalysisCache(cache_path)
    seed.put("hashA", FILTER_METADATA["prompt_hash"], "gpt-4o-mini", _analysis("fully_remote"))

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        side_effect=[_analysis("fully_remote")],
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    assert mock_analyze.call_count == 1
    assert counts["cache_hits"] == 1
    assert counts["cache_misses"] == 1

    pass_records = [json.loads(line) for line in pass_path.read_text().splitlines()]
    assert len(pass_records) == 2
    by_title = {r["title"]: r for r in pass_records}
    assert by_title["A"]["_filter_metadata"]["from_cache"] is True
    assert by_title["B"]["_filter_metadata"]["from_cache"] is False


def test_run_remote_filter_writes_miss_results_to_cache(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        return_value=_analysis("fully_remote"),
    ):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    assert cache_path.exists()
    cached = AnalysisCache(cache_path)
    assert cached.get("hashA", FILTER_METADATA["prompt_hash"], "gpt-4o-mini") is not None


def test_run_remote_filter_no_cache_disables_lookup_and_write(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    pass_path = tmp_path / "pass.jsonl"
    trash_path = tmp_path / "trash.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        return_value=_analysis("fully_remote"),
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                pass_path=pass_path,
                trash_path=trash_path,
                config_path=config_path,
                cache_path=None,
            )

    assert mock_analyze.call_count == 1
    assert counts["cache_hits"] == 0
    assert counts["cache_misses"] == 0
