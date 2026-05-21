import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# TODO: when skills_fit ships its own analysis cache, extract a generic
# base class (probably src/utils/analysis_cache.py) and make this a typed
# subclass over RemoteAnalysis. Two consumers > one — design the abstraction
# then, not now.
from .models import RemoteAnalysis

log = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path("data/cache/remote_filter_analyses.jsonl")


def _composite_key(
    *,
    dedup_hash: str,
    prompt_hash: str,
    provider: str,
    model: str,
    context_fp: str,
) -> str:
    return f"{dedup_hash}|{prompt_hash}|{provider}|{model}|{context_fp}"


class AnalysisCache:
    """Append-only JSONL cache for remote-filter analyses.

    Composite key: (dedup_hash, prompt_hash, provider, model, context_fp).
    Any change to the prompt, the provider/model pair, or the search-context
    fields the prompt reads (keywords, workplace, job_type, user_timezone)
    changes the key and forces a miss — no manual invalidation needed.
    Later entries with the same key override earlier ones on load.
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
        self,
        *,
        dedup_hash: str,
        prompt_hash: str,
        provider: str,
        model: str,
        context_fp: str,
    ) -> RemoteAnalysis | None:
        key = _composite_key(
            dedup_hash=dedup_hash,
            prompt_hash=prompt_hash,
            provider=provider,
            model=model,
            context_fp=context_fp,
        )
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
        *,
        dedup_hash: str,
        prompt_hash: str,
        provider: str,
        model: str,
        context_fp: str,
        analysis: RemoteAnalysis,
    ) -> None:
        key = _composite_key(
            dedup_hash=dedup_hash,
            prompt_hash=prompt_hash,
            provider=provider,
            model=model,
            context_fp=context_fp,
        )
        entry = {
            "key": key,
            "dedup_hash": dedup_hash,
            "prompt_hash": prompt_hash,
            "provider": provider,
            "model": model,
            "context_fp": context_fp,
            "analysis": analysis.model_dump(),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self._entries[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
