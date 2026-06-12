"""Generic append-only JSONL cache for per-job LLM analyses.

Two agents need the same cache shape — remote_filter (job-intrinsic
classification) and skills_fit (per-profile scoring). The on-disk format,
the composite-key construction, and the load/get/put dance are identical;
only the analysis Pydantic model and which fields make up the key differ.
This module owns that shared shape so subclasses are a tuple + a model
reference.

Subclass contract:
    class MyCache(AnalysisCache[MyAnalysis]):
        KEY_FIELDS = ("dedup_hash", "prompt_hash", "provider", "model", ...)
        ANALYSIS_MODEL = MyAnalysis
        DEFAULT_PATH = Path("data/cache/my_analyses.jsonl")

`get` and `put` accept the KEY_FIELDS as keyword arguments. A missing key
field raises TypeError — fail fast (CLAUDE.md). The composite key string
is the KEY_FIELDS values joined by `|` in declaration order, matching what
the pre-refactor remote_filter cache wrote, so existing on-disk JSONL
files load unchanged.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AnalysisCache(Generic[T]):
    KEY_FIELDS: ClassVar[tuple[str, ...]] = ()
    ANALYSIS_MODEL: ClassVar[type[BaseModel]]
    DEFAULT_PATH: ClassVar[Path]

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _composite_key(self, fields: dict[str, str]) -> str:
        missing = [k for k in self.KEY_FIELDS if k not in fields]
        if missing:
            raise TypeError(
                f"{type(self).__name__}: missing required key fields: {missing}"
            )
        return "|".join(fields[k] for k in self.KEY_FIELDS)

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    key = entry["key"]
                except (json.JSONDecodeError, KeyError) as exc:
                    log.warning("Skipping malformed cache line: %s", exc)
                    continue
                self._entries[key] = entry

    def get(self, **fields: str) -> T | None:
        key = self._composite_key(fields)
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            return self.ANALYSIS_MODEL(**entry["analysis"])  # type: ignore[return-value]
        except Exception as exc:
            log.warning("Cached analysis for %s failed validation: %s", key, exc)
            return None

    def put(self, *, analysis: T, **fields: str) -> None:
        key = self._composite_key(fields)
        # Write key fields in KEY_FIELDS order so the on-disk JSONL has stable
        # column order across runs (helps when someone greps the cache file).
        entry: dict[str, Any] = {"key": key}
        for k in self.KEY_FIELDS:
            entry[k] = fields[k]
        entry["analysis"] = analysis.model_dump()
        entry["cached_at"] = datetime.now(timezone.utc).isoformat()
        self._entries[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
