import json
from pathlib import Path
from unittest.mock import patch

from agents.remote_filter.cache import AnalysisCache
from agents.remote_filter.input_models import RemoteFilterInput
from agents.remote_filter.models import RemoteAnalysis
from agents.remote_filter.runner import run_remote_filter


_BASE_KEY = {
    "dedup_hash": "hashA",
    "prompt_hash": "p1",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "context_fp": "none",
}


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


def _analysis(classification: str = "remote", **overrides) -> RemoteAnalysis:
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
# AnalysisCache
# ---------------------------------------------------------------------------


def test_analysis_cache_miss_then_hit_via_jsonl_roundtrip(tmp_path):
    cache_path = tmp_path / "cache.jsonl"
    cache = AnalysisCache(cache_path)
    assert cache.get(**_BASE_KEY) is None

    cache.put(**_BASE_KEY, analysis=_analysis("remote"))

    reopened = AnalysisCache(cache_path)
    hit = reopened.get(**_BASE_KEY)
    assert hit is not None
    assert hit.remote_classification == "remote"


def test_analysis_cache_changes_key_when_any_part_changes(tmp_path):
    cache_path = tmp_path / "cache.jsonl"
    cache = AnalysisCache(cache_path)
    cache.put(**_BASE_KEY, analysis=_analysis("remote"))

    assert cache.get(**{**_BASE_KEY, "prompt_hash": "p2"}) is None
    assert cache.get(**{**_BASE_KEY, "model": "gpt-4o"}) is None
    assert cache.get(**{**_BASE_KEY, "provider": "ollama"}) is None
    assert cache.get(**{**_BASE_KEY, "context_fp": "abcd1234"}) is None
    assert cache.get(**_BASE_KEY) is not None


# ---------------------------------------------------------------------------
# Runner integration: within-batch dedup + across-batch cache
# ---------------------------------------------------------------------------


def test_run_remote_filter_collapses_within_batch_duplicates(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
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
        side_effect=[_analysis("remote"), _analysis("remote")],
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
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
    classified_path = tmp_path / "classified.jsonl"
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
    # search_context from `_job` has workplace=remote → fingerprint matches the
    # one the runner computes for these records.
    from agents.remote_filter.utils import context_fingerprint

    primed_fp = context_fingerprint(
        RemoteFilterInput(description="", workplace="remote")
    )
    seed = AnalysisCache(cache_path)
    seed.put(
        dedup_hash="hashA",
        prompt_hash=FILTER_METADATA["prompt_hash"],
        provider="openai",
        model="gpt-4o-mini",
        context_fp=primed_fp,
        analysis=_analysis("remote"),
    )

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        side_effect=[_analysis("remote")],
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    assert mock_analyze.call_count == 1
    assert counts["cache_hits"] == 1
    assert counts["cache_misses"] == 1

    records = [json.loads(line) for line in classified_path.read_text().splitlines()]
    assert len(records) == 2
    by_title = {r["title"]: r for r in records}
    assert by_title["A"]["_filter_metadata"]["from_cache"] is True
    assert by_title["B"]["_filter_metadata"]["from_cache"] is False


def test_run_remote_filter_writes_miss_results_to_cache(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        return_value=_analysis("remote"),
    ):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    from agents.remote_filter.utils import context_fingerprint

    assert cache_path.exists()
    cached = AnalysisCache(cache_path)
    assert (
        cached.get(
            dedup_hash="hashA",
            prompt_hash=FILTER_METADATA["prompt_hash"],
            provider="openai",
            model="gpt-4o-mini",
            context_fp=context_fingerprint(
                RemoteFilterInput(description="", workplace="remote")
            ),
        )
        is not None
    )


def test_run_remote_filter_no_cache_disables_lookup_and_write(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        return_value=_analysis("remote"),
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=None,
            )

    assert mock_analyze.call_count == 1
    assert counts["cache_hits"] == 0
    assert counts["cache_misses"] == 0


# ---------------------------------------------------------------------------
# Copilot review fixes: search_context in key, miss counter on LLM failure,
# provider in key.
# ---------------------------------------------------------------------------


def test_run_remote_filter_user_timezone_change_misses_cache(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        return_value=_analysis("remote"),
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            # First run with PST primes the cache under one fingerprint.
            run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=cache_path,
                user_timezone="PST",
            )
            # Second run with EST must miss the cache and hit the LLM again,
            # because user_timezone is part of the prompt input.
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=cache_path,
                user_timezone="EST",
            )

    assert mock_analyze.call_count == 2
    assert counts["cache_hits"] == 0
    assert counts["cache_misses"] == 1


def test_run_remote_filter_counts_miss_even_when_llm_fails(tmp_path):
    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    # Cache miss → LLM call → LLM fails. Miss should still be counted so the
    # reported hit rate doesn't silently overstate savings on noisy runs.
    with patch("agents.remote_filter.runner.analyze_remote", return_value=None):
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=config_path,
                cache_path=cache_path,
            )

    assert counts["skipped"] == 1
    assert counts["cache_hits"] == 0
    assert counts["cache_misses"] == 1


def test_run_remote_filter_provider_change_misses_cache(tmp_path, monkeypatch):
    """Cache primed by an openai run must miss when the same job runs under ollama."""
    from agents.remote_filter.utils import context_fingerprint

    input_path = tmp_path / "raw.jsonl"
    classified_path = tmp_path / "classified.jsonl"
    config_path = tmp_path / "remote_agent.yml"
    cache_path = tmp_path / "cache.jsonl"
    _write_config(config_path)
    _write_jsonl(input_path, [_job(source_job_id="1", dedup_hash="hashA")])

    # Prime the cache with an openai entry under the same model string.
    primed_fp = context_fingerprint(
        RemoteFilterInput(description="", workplace="remote")
    )
    seed = AnalysisCache(cache_path)
    seed.put(
        dedup_hash="hashA",
        prompt_hash=FILTER_METADATA["prompt_hash"],
        provider="openai",
        model="gpt-4o-mini",
        context_fp=primed_fp,
        analysis=_analysis("remote"),
    )

    # Force the runner to resolve provider=ollama via env override; same model
    # string. Old (provider-less) cache key would have hit; new key must miss.
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

    with patch(
        "agents.remote_filter.runner.analyze_remote",
        return_value=_analysis("remote"),
    ) as mock_analyze:
        with patch(
            "agents.remote_filter.runner.build_filter_metadata",
            return_value=FILTER_METADATA,
        ):
            # Use a config without an llm section so the env vars win.
            bare_config = tmp_path / "bare.yml"
            bare_config.write_text(
                "policy_thresholds:\n"
                "  disallowed_classifications: []\n"
                "  travel:\n"
                "    max_estimated_days_per_year: 15\n"
                "  relocation:\n"
                "    allow_required_relocation: false\n"
                "    allow_local_presence_required: false\n"
                "  uncertainty:\n"
                "    on_unclear_classification: reject\n"
                "  timezone:\n"
                "    rejected_timezone_keywords: []\n",
                encoding="utf-8",
            )
            counts = run_remote_filter(
                input_path=input_path,
                classified_path=classified_path,
                config_path=bare_config,
                cache_path=cache_path,
            )

    assert mock_analyze.call_count == 1
    assert counts["cache_hits"] == 0
    assert counts["cache_misses"] == 1
