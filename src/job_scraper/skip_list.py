import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DEFAULT_PATH = Path("config/known_failures.json")

# Only permanently skip on definitive "this board doesn't exist" responses.
# 429/5xx are transient — don't record them.
_PERMANENT_CODES = {403, 404, 410}


def load(path: Path = DEFAULT_PATH) -> dict:
    """Return {source_name: record} for all known permanent failures."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to load skip list from %s: %s", path, exc)
        return {}


def record(source_name: str, exc: Exception, path: Path = DEFAULT_PATH) -> None:
    """Persist a permanent failure for source_name so future runs skip it."""
    failures = load(path)
    url = ""
    if isinstance(exc, requests.HTTPError) and exc.request is not None:
        url = exc.request.url or ""
    failures[source_name] = {
        "error": str(exc),
        "url": url,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(failures, indent=2) + "\n")
    log.info("Recorded permanent failure for %s → %s", source_name, path)


def is_permanent(exc: Exception) -> bool:
    """True if this exception is a permanent failure worth recording in the skip list."""
    return (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and exc.response.status_code in _PERMANENT_CODES
    )
