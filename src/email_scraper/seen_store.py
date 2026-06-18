"""SeenStore — a tiny membership cache for email dedup (Layer 1).

A *port*: callers depend on the `SeenStore` protocol, not on storage. The default
`JsonlSeenStore` appends keys to an append-only `data/cache/*.jsonl` file (the same
convention as the agent `AnalysisCache`s). A future central adapter (Postgres on
the Proxmox LAN, or Azure) can drop in for cross-node coordination without touching
any caller — the enrichment core stays storage-agnostic.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

DEFAULT_PROCESSED_PATH = Path("data/cache/email_processed.jsonl")


@runtime_checkable
class SeenStore(Protocol):
    """Membership cache: have we handled this key before?"""

    def has(self, key: str) -> bool: ...

    def add(self, key: str) -> None: ...


class JsonlSeenStore:
    """Append-only JSONL adapter. Loads keys into a set on construction."""

    def __init__(self, path: Path = DEFAULT_PROCESSED_PATH) -> None:
        self._path = Path(path)
        self._keys: set[str] = set()
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._keys.add(json.loads(line)["key"])
                except (ValueError, KeyError):
                    # A malformed line shouldn't blind the whole cache; skip it.
                    log.warning("Skipping malformed cache line in %s", self._path)
        log.info("Loaded %d seen key(s) from %s", len(self._keys), self._path)

    def has(self, key: str) -> bool:
        return key in self._keys

    def add(self, key: str) -> None:
        if key in self._keys:
            return
        self._keys.add(key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"key": key, "ts": datetime.now(timezone.utc).isoformat()})
                + "\n"
            )


def default_processed_store() -> JsonlSeenStore:
    """The default processed-email cache at ``data/cache/email_processed.jsonl``."""
    return JsonlSeenStore(DEFAULT_PROCESSED_PATH)
