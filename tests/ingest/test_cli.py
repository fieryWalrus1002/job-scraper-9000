"""Tests for the ingest CLI: --blob-mode and --input validation, and blob lifecycle.

Fast tests (no Docker) cover env-var and argparse guard-rails.
Docker tests use Azurite to verify blob move/skip behaviour against the real
Azure SDK — the same paths that run in ACA.

Run all tests:
    uv run pytest tests/ingest/test_cli.py -v

Run only Docker tests:
    uv run pytest -m docker tests/ingest/test_cli.py -v
"""

from __future__ import annotations

import argparse

import pytest

from ingest.cli import _cmd_ingest, _ingest_from_blob, main


def _ns(**kwargs) -> argparse.Namespace:
    defaults = dict(
        db_url=None,
        input=None,
        schema_path="db/schema.sql",
        apply_schema=False,
        dry_run=False,
        blob_mode=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Fast tests — no Docker required
# ---------------------------------------------------------------------------


def test_blob_mode_without_connection_string_exits_1(monkeypatch):
    """--blob-mode exits 1 cleanly when AZURE_STORAGE_CONNECTION_STRING is absent."""
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    with pytest.raises(SystemExit) as exc:
        _ingest_from_blob(_ns(blob_mode=True), "postgresql://fake/db")
    assert exc.value.code == 1


def test_input_omitted_without_blob_mode_exits_1(monkeypatch):
    """--input omitted without --blob-mode exits 1 cleanly (not TypeError)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/db")
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    with pytest.raises(SystemExit) as exc:
        _cmd_ingest(_ns(blob_mode=False, input=None))
    assert exc.value.code == 1


def test_main_rejects_missing_input_without_blob_mode():
    """main() flat parser exits 2 (argparse error) when --input is omitted and --blob-mode is unset."""
    with pytest.raises(SystemExit) as exc:
        main(["--schema-path", "db/schema.sql"])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Blob lifecycle tests — require Azurite (Docker)
# ---------------------------------------------------------------------------


@pytest.mark.docker
def test_empty_blob_moved_to_processed(
    clean_blob_storage, monkeypatch, azurite_conn_str
):
    """An empty pending blob is moved to processed/ on success, preventing KEDA re-trigger."""
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", azurite_conn_str)
    pending = clean_blob_storage["pending"]
    processed = clean_blob_storage["processed"]

    pending.get_blob_client("empty.jsonl").upload_blob(b"", overwrite=True)
    _ingest_from_blob(_ns(blob_mode=True, dry_run=False), "postgresql://unused/db")

    assert "empty.jsonl" not in [b.name for b in pending.list_blobs()]
    assert "empty.jsonl" in [b.name for b in processed.list_blobs()]


@pytest.mark.docker
def test_dry_run_blobs_not_moved(clean_blob_storage, monkeypatch, azurite_conn_str):
    """In --dry-run mode, an empty pending blob is never moved to processed/."""
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", azurite_conn_str)
    pending = clean_blob_storage["pending"]
    processed = clean_blob_storage["processed"]

    pending.get_blob_client("pending.jsonl").upload_blob(b"", overwrite=True)
    _ingest_from_blob(_ns(blob_mode=True, dry_run=True), "postgresql://unused/db")

    assert "pending.jsonl" in [b.name for b in pending.list_blobs()]
    assert "pending.jsonl" not in [b.name for b in processed.list_blobs()]


@pytest.mark.docker
def test_dry_run_nonempty_blob_not_moved(
    clean_blob_storage, monkeypatch, azurite_conn_str
):
    """In --dry-run mode, a non-empty blob is parsed but never moved (DB call stubbed)."""
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", azurite_conn_str)
    monkeypatch.setattr(
        "ingest.cli._connect_and_ingest",
        lambda records, args, db_url: {
            "total": 1,
            "inserted": 1,
            "skipped": 0,
            "dry_run": True,
        },
    )
    pending = clean_blob_storage["pending"]
    processed = clean_blob_storage["processed"]

    pending.get_blob_client("real.jsonl").upload_blob(
        b'{"dedup_hash": "abc123"}\n', overwrite=True
    )
    _ingest_from_blob(_ns(blob_mode=True, dry_run=True), "postgresql://unused/db")

    assert "real.jsonl" in [b.name for b in pending.list_blobs()]
    assert "real.jsonl" not in [b.name for b in processed.list_blobs()]
