import json
import logging
from typing import Protocol, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class RunLogger(Protocol):
    def log_run(self, record: dict[str, Any]) -> None:
        """Persist evaluation run metrics and provenance."""
        ...

class JsonlRunLogger:
    def __init__(self, log_path: str | Path = "data/eval/runs.jsonl"):
        self.log_path = Path(log_path)
        # Ensure directory exists (infrastructure idempotency)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _sanitize(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Explicitly strip sensitive keys before writing to disk.
        Prevents API keys or credentials from leaking into telemetry.
        """
        # Deep copy to avoid mutating the caller's dictionary
        safe_record = json.loads(json.dumps(record))
        
        if "config" in safe_record and isinstance(safe_record["config"], dict):
            for key in list(safe_record["config"].keys()):
                # Catch standard credential patterns
                if any(secret in key.lower() for secret in ["key", "token", "secret", "password"]):
                    safe_record["config"][key] = "[REDACTED]"
                    
        return safe_record

    def log_run(self, record: dict[str, Any]) -> None:
        try:
            safe_record = self._sanitize(record)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(safe_record) + "\n")
        except Exception as e:
            # SC-1: Failure must not suppress or abort eval results
            logger.warning(f"Failed to write run log to {self.log_path}: {e}")