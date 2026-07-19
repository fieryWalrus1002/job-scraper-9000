from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator


class SearchProvenance(BaseModel):
    source: str | None = None
    workplace: str | None = None
    job_type: str | None = None
    source_detail_location: str | None = None

    def to_prompt_dict(self) -> dict[str, str]:
        """Return the non-empty fields consumed by the remote-filter prompt."""
        return self.model_dump(exclude_none=True, exclude_defaults=True)


class RemoteFilterInput(BaseModel):
    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    description: str
    title: str | None = None
    location: str | None = None
    keywords: str | None = None
    workplace: str | None = None
    job_type: str | None = None
    user_timezone: str | None = None
    search_contexts: list[SearchProvenance] = Field(default_factory=list)

    @field_validator("search_contexts", mode="after")
    @classmethod
    def _canonicalize_search_contexts(
        cls, value: list[SearchProvenance]
    ) -> list[SearchProvenance]:
        return normalize_search_contexts(value)

    @classmethod
    def from_posting(
        cls, job: dict, user_timezone: str | None = None
    ) -> "RemoteFilterInput":
        """Build the validated remote-filter input contract from a raw posting."""
        search_params = dict(job.get("search_params") or {})
        return cls(
            description=job.get("description") or "",
            title=job.get("title") or None,
            location=job.get("location") or None,
            keywords=search_params.get("keywords") or None,
            workplace=search_params.get("workplace") or None,
            job_type=search_params.get("job_type") or None,
            user_timezone=user_timezone or search_params.get("user_timezone") or None,
            search_contexts=normalize_search_contexts(job.get("search_contexts") or []),
        )

    def prompt_context_projection(self) -> dict[str, object]:
        """Return the canonical fields that affect prompt text and cache keys."""
        relevant: dict[str, object] = {}
        if self.keywords:
            relevant["keywords"] = self.keywords
        if self.workplace:
            relevant["workplace"] = self.workplace
        if self.job_type:
            relevant["job_type"] = self.job_type
        if self.search_contexts:
            relevant["search_contexts"] = [
                context.to_prompt_dict() for context in self.search_contexts
            ]
        if self.user_timezone:
            relevant["user_timezone"] = self.user_timezone
        return relevant


def normalize_search_contexts(
    search_contexts: Iterable[Mapping[str, Any] | SearchProvenance],
) -> list[SearchProvenance]:
    """Canonicalize provenance contexts for stable prompts and cache keys."""
    prompt_fields = set(SearchProvenance.model_fields)
    normalized: dict[str, SearchProvenance] = {}
    for context in search_contexts:
        raw = (
            context.to_prompt_dict()
            if isinstance(context, SearchProvenance)
            else context
        )
        cleaned = {
            k: v
            for k, v in raw.items()
            if k in prompt_fields and v not in (None, "", [], {})
        }
        if not cleaned or set(cleaned) == {"source"}:
            continue
        provenance = SearchProvenance(**cleaned)
        marker = json.dumps(
            provenance.to_prompt_dict(), sort_keys=True, separators=(",", ":")
        )
        normalized[marker] = provenance
    return [normalized[marker] for marker in sorted(normalized)]
