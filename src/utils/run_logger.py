import json
import logging
from typing import Protocol, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class RunLogger(Protocol):
    def log_run(self, record: dict[str, Any]) -> None:
        """Persist evaluation run metrics and provenance."""
        ...


class MLFlowRunLogger:
    def __init__(self, mlflow_client, experiment_name: str):
        self.client = mlflow_client
        self.experiment_name = experiment_name

    def log_run(self, record: dict[str, Any]) -> None:
        """
        Encapsulates the stateful interaction with MLFlow, including error
        handling to ensure robustness.
         - SC-1: If MLFlow logging fails (e.g., due to network issues), it
           logs a warning but does not raise an exception, ensuring that the
           main evaluation flow is not disrupted.
         - SC-2: The method expects a dictionary of run metadata (e.g.,
         parameters, metrics) and attempts to log each key-value pair to MLFlow
         under the specified experiment.
        """
        try:
            # SC-1: Log run metadata to MLFlow (non-blocking)
            with self.client.start_run(experiment_id=self.experiment_name) as run:
                for key, value in record.items():
                    self.client.log_param(run.info.run_id, key, value)
        except Exception as e:
            # SC-1: Failure must not suppress or abort eval results
            logger.warning(f"Failed to log run to MLFlow: {e}")


class JsonlRunLogger:
    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)

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
                if any(
                    secret in key.lower()
                    for secret in ["key", "token", "secret", "password"]
                ):
                    safe_record["config"][key] = "[REDACTED]"

        return safe_record

    def _existing_run_ids(self) -> set[str]:
        try:
            if not self.log_path.exists():
                return set()
            ids = set()
            for line in self.log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    ids.add(json.loads(line).get("run_id", ""))
            return ids
        except OSError:
            return set()

    def log_run(self, record: dict[str, Any]) -> None:
        run_id = record.get("run_id")
        if run_id and run_id in self._existing_run_ids():
            raise ValueError(f"run_id '{run_id}' already exists in {self.log_path}")
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            safe_record = self._sanitize(record)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(safe_record) + "\n")
        except Exception as e:
            # SC-1: I/O failures must not suppress or abort eval results
            logger.warning(f"Failed to write run log to {self.log_path}: {e}")
