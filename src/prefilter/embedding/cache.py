"""Embedding cache keys, validation, and injectable cache-miss fetching."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from .models import CacheIdentity
from .reference import ALL_SCHEMA_VERSIONS


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def endpoint_identity(provider: str, base_url: str | None) -> str:
    if provider == "openai":
        return "openai-default"
    if provider != "ollama":
        raise ValueError(f"Unsupported provider: {provider}")
    if not base_url:
        raise ValueError("Ollama requires a base URL")
    parsed = urlparse(base_url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        raise ValueError("--base-url must be an absolute http(s) URL for ollama")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("--base-url has an invalid port") from exc
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host = f"{host}:{port}"
    return f"{scheme}://{host}{parsed.path.rstrip('/')}"


def cache_identity(
    *, schema_version: str, provider: str, endpoint: str, model: str, text: str
) -> CacheIdentity:
    return CacheIdentity(schema_version, provider, endpoint, model, sha256_text(text))


def _validated_vector(value: object, context: str) -> tuple[float, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context}: embedding must be a non-empty list")
    vector: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{context}: embedding[{index}] must be a finite number")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{context}: embedding[{index}] must be finite")
        vector.append(number)
    return tuple(vector)


def parse_cache_jsonl(text: str, path: Path) -> dict[str, tuple[float, ...]]:
    """Load all cache entries; malformed or conflicting entries are corruption."""
    entries: dict[str, tuple[float, ...]] = {}
    required = {
        "key",
        "schema_version",
        "provider",
        "endpoint_identity",
        "model",
        "input_sha256",
        "dimension",
        "embedding",
    }
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        context = f"Malformed cache {path} line {line_number}"
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{context}: invalid JSON: {exc.msg}") from exc
        if not isinstance(record, dict) or required - record.keys():
            raise ValueError(f"{context}: missing required cache metadata")
        for field in required - {"dimension", "embedding"}:
            if not isinstance(record[field], str) or not record[field]:
                raise ValueError(f"{context}: {field} must be a non-empty string")
        if record["schema_version"] not in ALL_SCHEMA_VERSIONS:
            raise ValueError(f"{context}: unknown schema_version")
        if record["provider"] not in {"openai", "ollama"}:
            raise ValueError(f"{context}: unknown provider")
        if not re.fullmatch(r"[0-9a-f]{64}", record["input_sha256"]):
            raise ValueError(f"{context}: input_sha256 must be a SHA-256 hex digest")
        if isinstance(record["dimension"], bool) or not isinstance(
            record["dimension"], int
        ):
            raise ValueError(f"{context}: dimension must be an integer")
        vector = _validated_vector(record["embedding"], context)
        if record["dimension"] != len(vector):
            raise ValueError(
                f"{context}: stored dimension disagrees with embedding length"
            )
        expected_key = json.dumps(
            [
                record["schema_version"],
                record["provider"],
                record["endpoint_identity"],
                record["model"],
                record["input_sha256"],
            ],
            separators=(",", ":"),
        )
        if record["key"] != expected_key:
            raise ValueError(f"{context}: key does not match cache metadata")
        previous = entries.get(record["key"])
        if previous is not None and previous != vector:
            raise ValueError(f"{context}: duplicate key has a different embedding")
        entries[record["key"]] = vector
    return entries


def _cache_entry(identity: CacheIdentity, vector: Sequence[float]) -> dict[str, object]:
    return {
        "key": identity.key,
        "schema_version": identity.schema_version,
        "provider": identity.provider,
        "endpoint_identity": identity.endpoint_identity,
        "model": identity.model,
        "input_sha256": identity.input_sha256,
        "dimension": len(vector),
        "embedding": list(vector),
    }


def fetch_missing_embeddings(
    client: Any,
    model: str,
    missing: dict[CacheIdentity, str],
    batch_size: int = 100,
) -> tuple[dict[str, tuple[float, ...]], int, int]:
    """Fetch cache misses in batches, validating the complete provider response."""
    if batch_size < 1:
        raise ValueError("embedding batch size must be at least 1")
    resolved: dict[str, tuple[float, ...]] = {}
    identities = list(missing)
    api_batches = 0
    for start in range(0, len(identities), batch_size):
        batch = identities[start : start + batch_size]
        inputs = [missing[identity] for identity in batch]
        response = client.embeddings.create(model=model, input=inputs)
        api_batches += 1
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != len(batch):
            raise ValueError(
                "Malformed embedding response: expected exactly one vector per requested input"
            )
        for position, (identity, item) in enumerate(zip(batch, data, strict=True)):
            vector = _validated_vector(
                getattr(item, "embedding", None),
                f"Malformed embedding response item {position}",
            )
            resolved[identity.key] = vector
    return resolved, len(identities), api_batches
