"""Worker wiring tests for the companies embedding veto."""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline.worker as worker
from pipeline.worker import EmbeddingVetoConfig, process_job


class _FakeResult:
    def fetchone(self):
        return ("veto@example.com",)


class _FakeConnection:
    def __init__(self):
        self.queries: list[str] = []

    def execute(self, query: str, params: object):
        self.queries.append(query)
        return _FakeResult()


def _config(tmp_path: Path, *, enabled: bool = True) -> EmbeddingVetoConfig:
    return EmbeddingVetoConfig(
        enabled=enabled,
        cut_depth=0.5,
        reference_mode="blend",
        provider="ollama",
        base_url="http://localhost:8080/v1",
        model="nomic-embed-text-v1.5",
        prefix_scheme="nomic",
        cache_path=tmp_path / "embeddings.jsonl",
        embedding_batch_size=100,
    )


def _job(source: str) -> dict[str, object]:
    return {
        "id": "job-id",
        "run_id": "run-id",
        "user_id": "user-id",
        "source": source,
        "query_payload": {},
    }


def _jobs() -> list[dict[str, str]]:
    return [
        {"title": "Best", "company": "Acme", "dedup_hash": "best"},
        {"title": "Worst", "company": "Acme", "dedup_hash": "worst"},
    ]


def test_process_job_gates_veto_to_companies(tmp_path: Path, monkeypatch):
    def veto_must_not_run(*args, **kwargs):
        raise AssertionError("veto must not run for keyword-targeted sources")

    monkeypatch.setattr(worker, "_apply_embedding_veto", veto_must_not_run)
    for source in ("linkedin", "jobspy"):
        count = process_job(
            _FakeConnection(),  # type: ignore[arg-type]
            _job(source),
            runs_dir=tmp_path,
            scrape_fn=lambda *_: [{"title": "ML Engineer", "company": "Acme"}],
        )
        assert count == 1


def test_process_job_companies_veto_is_produce_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        worker, "_load_embedding_veto_config", lambda _: _config(tmp_path)
    )
    monkeypatch.setattr(worker, "_load_reference_texts", lambda *_: ["Reference"])
    monkeypatch.setattr(worker, "_load_embedding_cache", lambda _: {})
    monkeypatch.setattr(worker, "_apply_embedding_veto", lambda jobs, **_: jobs[:1])
    conn = _FakeConnection()

    count = process_job(
        conn,  # type: ignore[arg-type]
        _job("companies"),
        runs_dir=tmp_path,
        scrape_fn=lambda *_: _jobs(),
    )

    assert count == 1
    # The worker only asks the DB for the user email. The veto only trims the
    # scrape JSONL artifact; it writes neither raw rows nor scores.
    assert len(conn.queries) == 1
    persisted = (
        tmp_path / "run-id" / "veto_example_com" / "scrape" / "companies.jsonl"
    ).read_text()
    assert '"Best"' in persisted
    assert '"Worst"' not in persisted


def test_disabled_companies_veto_leaves_today_behavior_unchanged(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        worker,
        "_load_embedding_veto_config",
        lambda _: _config(tmp_path, enabled=False),
    )
    jobs = [{"title": "ML Engineer", "company": "Acme"}]

    count = process_job(
        _FakeConnection(),  # type: ignore[arg-type]
        _job("companies"),
        runs_dir=tmp_path,
        scrape_fn=lambda *_: jobs,
    )

    assert count == 1


def test_enabled_veto_fails_loudly_when_reference_inputs_are_missing(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        worker, "_load_embedding_veto_config", lambda _: _config(tmp_path)
    )

    with pytest.raises(ValueError, match="Could not load profile"):
        process_job(
            _FakeConnection(),  # type: ignore[arg-type]
            _job("companies"),
            runs_dir=tmp_path,
            scrape_fn=lambda *_: _jobs(),
        )
