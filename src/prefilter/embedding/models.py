"""Data models for embedding-based prefilter ranking."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Posting:
    title: str
    company: str
    dedup_hash: str
    description: str
    source_url: str
    description_fallback: bool


@dataclass(frozen=True)
class RankedPosting:
    posting: Posting
    similarity: float
    global_rank: int
    company_rank: int
    ai_fit: int | None


@dataclass(frozen=True)
class CacheIdentity:
    schema_version: str
    provider: str
    endpoint_identity: str
    model: str
    input_sha256: str

    @property
    def key(self) -> str:
        """Serialize fields unambiguously; model names and URLs may contain ``|``."""
        return json.dumps(
            [
                self.schema_version,
                self.provider,
                self.endpoint_identity,
                self.model,
                self.input_sha256,
            ],
            separators=(",", ":"),
        )
