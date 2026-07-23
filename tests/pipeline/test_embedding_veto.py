"""Unit tests for embedding-veto ranking and configuration."""

from __future__ import annotations

from pathlib import Path

import pipeline.worker as worker
from pipeline.worker import (
    EmbeddingVetoConfig,
    _apply_embedding_veto,
    _load_embedding_veto_config,
)
from prefilter.embedding import (
    SCHEMAS_BY_PREFIX_SCHEME,
    apply_prefix_scheme,
    cache_identity,
    endpoint_identity,
)
from user_config import UserPolicies


def _config(tmp_path: Path, *, enabled: bool = True, cut_depth: float = 0.5):
    return EmbeddingVetoConfig(
        enabled=enabled,
        cut_depth=cut_depth,
        reference_mode="blend",
        provider="ollama",
        base_url="http://localhost:8080/v1",
        model="nomic-embed-text-v1.5",
        prefix_scheme="nomic",
        cache_path=tmp_path / "embeddings.jsonl",
        embedding_batch_size=100,
    )


def _cached_vectors(
    jobs: list[dict[str, str]], reference_text: str, config: EmbeddingVetoConfig
) -> dict[str, tuple[float, ...]]:
    schemas = SCHEMAS_BY_PREFIX_SCHEME[config.prefix_scheme]
    endpoint = endpoint_identity(config.provider, config.base_url)
    cache: dict[str, tuple[float, ...]] = {}
    reference = cache_identity(
        schema_version=schemas["reference"],
        provider=config.provider,
        endpoint=endpoint,
        model=config.model,
        text=apply_prefix_scheme(
            reference_text, role="reference", prefix_scheme=config.prefix_scheme
        ),
    )
    cache[reference.key] = (1.0, 0.0)
    vectors = {
        "Best": (1.0, 0.0),
        "Medium": (0.7, 0.7),
        "Low": (0.2, 1.0),
        "Worst": (0.0, 1.0),
    }
    for job in jobs:
        identity = cache_identity(
            schema_version=schemas["title"],
            provider=config.provider,
            endpoint=endpoint,
            model=config.model,
            text=apply_prefix_scheme(
                job["title"], role="job", prefix_scheme=config.prefix_scheme
            ),
        )
        cache[identity.key] = vectors[job["title"]]
    return cache


def _jobs() -> list[dict[str, str]]:
    return [
        {"title": "Medium", "company": "Acme", "dedup_hash": "medium"},
        {"title": "Worst", "company": "Acme", "dedup_hash": "worst"},
        {"title": "Best", "company": "Globex", "dedup_hash": "best"},
        {"title": "Low", "company": "Globex", "dedup_hash": "low"},
    ]


def test_embedding_veto_drops_exact_global_bottom_fraction_and_preserves_order(
    tmp_path: Path,
):
    jobs = _jobs()
    config = _config(tmp_path, cut_depth=0.5)
    survivors = _apply_embedding_veto(
        jobs,
        reference_text="Reference",
        config=config,
        cache=_cached_vectors(jobs, "Reference", config),
    )

    # floor(0.5 * 4) == 2. The two low-ranked jobs span both companies, so this
    # verifies one global rank cut rather than a per-company cut.
    assert [job["title"] for job in survivors] == ["Medium", "Best"]


def test_per_user_embedding_veto_overrides_replace_system_defaults(
    tmp_path: Path, monkeypatch
):
    config_path = tmp_path / "companies_prefilter.yml"
    config_path.write_text(
        "enabled: true\ncut_depth: 0.33\nreference_mode: blend\n"
        "provider: ollama\nbase_url: http://localhost:8080/v1\n"
        "model: nomic-embed-text-v1.5\nprefix_scheme: nomic\n"
        "cache_path: data/cache/companies_prefilter_embeddings.jsonl\n"
    )
    monkeypatch.setattr(worker, "_COMPANIES_PREFILTER_CONFIG_PATH", config_path)
    policies = UserPolicies.model_validate(
        {
            "prefilter": {
                "embedding_veto_enabled": False,
                "embedding_veto_depth": 0.25,
            }
        }
    )

    config = _load_embedding_veto_config(policies)

    assert config.enabled is False
    assert config.cut_depth == 0.25
