import hashlib
import logging
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.git_info import get_git_metadata

log = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0.0"
MISMATCH_SCHEMA_VERSION = "2.0.0"

_REPO_ROOT = Path(__file__).parents[2]


# ---------------------------------------------------------------------------
# Hash primitives
# ---------------------------------------------------------------------------


def hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hash_string(text: str, encoding: str = "utf-8") -> str:
    return hash_bytes(text.encode(encoding))


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


# ---------------------------------------------------------------------------
# Run ID
# ---------------------------------------------------------------------------


def generate_run_id(prefix: str | None = None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:4]
    if prefix:
        return f"{prefix}_{ts}_{suffix}"
    return f"{ts}_{suffix}"


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


def _uv_version() -> str | None:
    try:
        return (
            subprocess.check_output(["uv", "--version"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        log.warning("uv not found; env.uv_version will be null in the run record")
        return None


def _collect_env(repo_root: Path) -> dict[str, Any]:
    lock_file = repo_root / "uv.lock"
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "uv_version": _uv_version(),
        "uv_lock_hash": hash_file(lock_file) if lock_file.exists() else None,
    }


# ---------------------------------------------------------------------------
# Run record assembly
# ---------------------------------------------------------------------------


def build_run_record(
    *,
    run_id: str,
    gold_file: Path,
    prompt_text: str,
    config: dict,
    config_file: str | Path,
    metrics: dict,
    mismatch_file: Path | None,
    repo_root: Path = _REPO_ROOT,
    schema_version: str = SCHEMA_VERSION,
    mismatch_schema_version: str = MISMATCH_SCHEMA_VERSION,
) -> dict:
    git = get_git_metadata()

    return {
        "schema_version": schema_version,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git": {
            "commit": git["commit"][:7],
            "dirty": git["dirty"],
        },
        "gold_file": str(gold_file),
        "gold_hash": hash_file(gold_file),
        "prompt_hash": hash_string(prompt_text),
        "config": {
            "provider": config.get("llm", {}).get("provider"),
            "model": config.get("llm", {}).get("model"),
            "temperature": config.get("llm", {}).get("temperature"),
            "policy_thresholds": config.get("policy_thresholds"),
            "config_file": str(config_file),
        },
        "env": _collect_env(repo_root),
        "metrics": metrics,
        "mismatch_file": str(mismatch_file) if mismatch_file else None,
        "mismatch_schema_version": mismatch_schema_version,
    }
