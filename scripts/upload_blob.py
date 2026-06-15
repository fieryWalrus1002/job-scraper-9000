#!/usr/bin/env python3
"""Upload a run's per-user scored files to the ``pending`` blob container (Phase 15 §5).

Walks ``data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl`` via
:func:`pipeline.scoring.iter_run_user_outputs` and uploads each to
``pending/<run_id>/<slug>__scored.jsonl``.

One blob per user (D4): the in-Azure ACA ingest job is KEDA ``azure-blob``
triggered with ``blobCountPerJob=1``, so one blob per user fans out one Job
execution per user and preserves the dead-letter failure isolation (a bad
record dead-letters that user's blob alone). Records self-route on ingest by
their stamped ``user_email`` (slice 2), so no per-blob ``--user-email`` is
needed.

Auth: AAD via ``az ... --auth-mode login`` (D3). The uploader runs on a laptop
with ``az login`` — no account key on disk. The operator's identity needs the
**Storage Blob Data Contributor** role on the storage account.

Usage:
    uv run scripts/upload_blob.py --run-id 2026-06-12T1635-overnight
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pipeline.scoring import iter_run_user_outputs  # noqa: E402

log = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "pipeline_runs"
PENDING_CONTAINER = "pending"

UploadFn = Callable[..., None]
"""``(account_name=, container=, blob_name=, file_path=) -> None``."""


def _az_upload(
    *, account_name: str, container: str, blob_name: str, file_path: Path
) -> None:
    """Upload one file via the ``az`` CLI with AAD auth (D3).

    ``check=True`` so a non-zero exit raises: a swallowed upload failure means
    a user's scores silently never reach the cloud DB — exactly the
    fail-quiet smell this phase set out to remove.
    """
    subprocess.run(
        [
            "az",
            "storage",
            "blob",
            "upload",
            "--account-name",
            account_name,
            "--container-name",
            container,
            "--name",
            blob_name,
            "--file",
            str(file_path),
            "--auth-mode",
            "login",
            "--overwrite",
        ],
        check=True,
    )


def upload_run(
    *,
    run_id: str,
    account_name: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    container: str = PENDING_CONTAINER,
    upload_fn: UploadFn = _az_upload,
) -> list[str]:
    """Upload each of a run's per-user scored files to
    ``<container>/<run_id>/<slug>__scored.jsonl`` (overwrite/idempotent).

    Returns the blob names uploaded, in the walk's deterministic order.
    ``upload_fn`` is injectable so tests run without touching Azure. Raises
    if the run produced no per-user outputs — an empty upload is almost
    always an operator error (wrong ``run_id``), not a quiet no-op.
    """
    blob_names: list[str] = []
    for out in iter_run_user_outputs(runs_dir, run_id):
        blob_name = f"{run_id}/{out.slug}__scored.jsonl"
        log.info("Uploading %s → %s/%s", out.user_email, container, blob_name)
        upload_fn(
            account_name=account_name,
            container=container,
            blob_name=blob_name,
            file_path=out.scored_path,
        )
        blob_names.append(blob_name)

    if not blob_names:
        raise SystemExit(
            f"No per-user scored files found for run_id={run_id!r} under "
            f"{runs_dir} — wrong --run-id, or the pipeline produced nothing?"
        )
    log.info("Uploaded %d blob(s) to container %r", len(blob_names), container)
    return blob_names


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, dest="run_id")
    parser.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR, type=Path)
    parser.add_argument("--container", default=PENDING_CONTAINER)
    parser.add_argument(
        "--account-name",
        default=os.environ.get("AZURE_STORAGE_ACCOUNT"),
        help="Storage account name (default: $AZURE_STORAGE_ACCOUNT)",
    )
    args = parser.parse_args()

    if not args.account_name:
        raise SystemExit(
            "Storage account not set — pass --account-name or set "
            "AZURE_STORAGE_ACCOUNT (the Justfile loads it from .env)"
        )

    upload_run(
        run_id=args.run_id,
        account_name=args.account_name,
        runs_dir=args.runs_dir,
        container=args.container,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
