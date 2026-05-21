import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RemoteAnalysis

log = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path("data/cache/remote_filter_analyses.jsonl")


def _composite_key(dedup_hash: str, prompt_hash: str, model: str) -> str:
    return f"{dedup_hash}|{prompt_hash}|{model}"


class AnalysisCache:
    """Append-only JSONL cache for remote-filter analyses.

    Key: (dedup_hash, prompt_hash, model). When prompt or model changes the
    composite key changes and entries cache-miss, so no manual invalidation
    is needed. Later entries with the same key override earlier ones on load.
    """

    def __init__(self, path: Path | str = DEFAULT_CACHE_PATH) -> None:
        self.path = Path(path)
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
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

    def get(
        self, dedup_hash: str, prompt_hash: str, model: str
    ) -> RemoteAnalysis | None:
        key = _composite_key(dedup_hash, prompt_hash, model)
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            return RemoteAnalysis(**entry["analysis"])
        except Exception as exc:
            log.warning("Cached analysis for %s failed validation: %s", key, exc)
            return None

    def put(
        self,
        dedup_hash: str,
        prompt_hash: str,
        model: str,
        analysis: RemoteAnalysis,
    ) -> None:
        key = _composite_key(dedup_hash, prompt_hash, model)
        entry = {
            "key": key,
            "dedup_hash": dedup_hash,
            "prompt_hash": prompt_hash,
            "model": model,
            "analysis": analysis.model_dump(),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self._entries[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
