"""Shared OpenAI Batch API mechanics.

Pure plumbing reused by the teacher-batch scripts, the eval-batch scripts, and
the production ``--batch`` agent paths: upload a JSONL request file, create a
batch, poll it to a terminal state, and pull the completed output file's text.

Domain-specific concerns stay with the callers: building requests (which know
their own schema/prompt), sidecar/provenance, result scoring, and where files
land on disk.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from openai import OpenAI
from openai.types import Batch

log = logging.getLogger(__name__)

BATCH_ENDPOINT: Literal["/v1/chat/completions"] = "/v1/chat/completions"
COMPLETION_WINDOW: Literal["24h"] = "24h"

# Statuses from which a batch will not advance further.
TERMINAL_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})


def upload_and_create_batch(client: OpenAI, request_file: Path) -> tuple[str, str]:
    """Upload a JSONL request file and create a batch over it.

    Returns ``(batch_id, input_file_id)``. All callers target the chat
    completions endpoint with a 24h completion window.
    """
    log.info("Uploading %s ...", request_file)
    with open(request_file, "rb") as f:
        file_obj = client.files.create(file=f, purpose="batch")
    log.info("File uploaded: %s", file_obj.id)

    batch = client.batches.create(
        input_file_id=file_obj.id,
        endpoint=BATCH_ENDPOINT,
        completion_window=COMPLETION_WINDOW,
    )
    log.info("Batch created: %s  status=%s", batch.id, batch.status)
    return batch.id, file_obj.id


def poll_until_done(client: OpenAI, batch_id: str, poll_interval: int = 60) -> Batch:
    """Poll ``batch_id`` every ``poll_interval`` seconds until it is terminal."""
    log.info("Polling batch %s every %ds ...", batch_id, poll_interval)
    while True:
        batch = client.batches.retrieve(batch_id)
        counts = batch.request_counts
        if counts is not None:
            log.info(
                "status=%-12s  completed=%d/%d  failed=%d",
                batch.status,
                counts.completed,
                counts.total,
                counts.failed,
            )
        else:
            log.info("status=%-12s  (counts unavailable)", batch.status)

        if batch.status in TERMINAL_STATUSES:
            return batch

        time.sleep(poll_interval)


def poll_all_until_done(
    client: OpenAI, batch_ids: list[str], poll_interval: int = 60
) -> dict[str, Batch]:
    """Poll many batches in one loop until every one is terminal.

    One ``client.batches.retrieve`` per still-outstanding id per tick; an id is
    dropped from the outstanding set once its status is terminal. Logs
    ``<n> of <m> terminal`` each tick. Returns ``{batch_id: terminal Batch}`` for
    every requested id. One thread — this interleaves waiting, it does not
    parallelize. An empty ``batch_ids`` returns ``{}`` without sleeping.
    """
    outstanding = list(dict.fromkeys(batch_ids))  # de-dup, preserve order
    total = len(outstanding)
    terminal: dict[str, Batch] = {}
    if not outstanding:
        return terminal
    log.info("Polling %d batch(es) every %ds ...", total, poll_interval)
    while outstanding:
        still_pending: list[str] = []
        for batch_id in outstanding:
            batch = client.batches.retrieve(batch_id)
            if batch.status in TERMINAL_STATUSES:
                terminal[batch_id] = batch
            else:
                still_pending.append(batch_id)
        log.info(
            "%d of %d batch(es) terminal (%d still running)",
            len(terminal),
            total,
            len(still_pending),
        )
        outstanding = still_pending
        if outstanding:
            time.sleep(poll_interval)
    return terminal


def download_results(client: OpenAI, batch: Batch) -> str:
    """Return the text of a completed batch's output file.

    Fails loudly: raises ``RuntimeError`` if the batch is not ``completed`` or
    has no output file. Callers inspect ``batch.error_file_id`` themselves for
    failure detail.
    """
    if batch.status != "completed":
        raise RuntimeError(f"Batch {batch.id} ended with status={batch.status}")
    if not batch.output_file_id:
        raise RuntimeError(f"Batch {batch.id} completed but output_file_id is missing")
    return client.files.content(batch.output_file_id).text
