import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def get_git_metadata() -> dict:
    """
    Returns the current commit SHA, dirty flag, and UTC timestamp.

    If the repo is dirty (uncommitted changes), the commit hash is unreliable
    as a reproducibility reference — callers should surface this to the user.
    Returns dirty=True if git is unavailable, so callers treat unknown state
    conservatively.
    """
    try:
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )

        status = (
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )

        dirty = bool(status)
    except Exception:
        commit = "unknown"
        dirty = True

    return {
        "commit": commit,
        "dirty": dirty,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_prompt_hash(prompt_path: Path) -> str:
    """First 8 hex chars of SHA-256 of the prompt file. Changes whenever the file does."""
    return hashlib.sha256(prompt_path.read_bytes()).hexdigest()[:8]
