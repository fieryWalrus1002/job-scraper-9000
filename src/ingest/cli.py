#!/usr/bin/env python3
"""CLI adapter for the ingest module.

Registered as a subcommand of job-scraper-9000 via register().
Also callable standalone (docker container entrypoint) via main().

Usage (pipeline CLI — DATABASE_URL read from .env automatically):
    uv run job-scraper-9000 ingest --input <path> --schema-path db/schema.sql

Usage (standalone / container — must pass --db-url explicitly):
    python -m ingest.cli --db-url $DATABASE_URL --input <path> --schema-path db/schema.sql

Usage (blob mode — ACA Job entrypoint):
    python -m ingest.cli --schema-path db/schema.sql --apply-schema --blob-mode
    Requires AZURE_STORAGE_CONNECTION_STRING env var.
    Processes all blobs in the "pending" container:
      - on success → moved to "processed"
      - empty blob → moved to "processed" (no-op success)
      - unparseable JSONL → moved to "failed" with a reason metadata tag
        (dead-letter, so KEDA doesn't re-trigger on the same poison blob)
    In --dry-run mode, blobs are never moved.

Duplicate dedup_hash values are silently skipped (ON CONFLICT DO NOTHING).
"""

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _connect_and_ingest(records, args, database_url: str) -> dict:
    import psycopg

    from .core import ensure_schema, ingest

    schema_path = Path(args.schema_path)
    if args.apply_schema and not schema_path.exists():
        log.error("Schema file not found: %s", schema_path)
        sys.exit(1)

    try:
        with psycopg.connect(database_url) as conn:
            if args.apply_schema:
                ensure_schema(conn, schema_path)
            return ingest(records, conn=conn, dry_run=args.dry_run)
    except psycopg.Error as exc:
        log.error("Database error: %s", exc)
        sys.exit(1)


def _move_blob(
    pending,
    target,
    name: str,
    data: bytes,
    metadata: dict[str, str] | None = None,
) -> None:
    target.get_blob_client(name).upload_blob(data, overwrite=True, metadata=metadata)
    pending.get_blob_client(name).delete_blob()
    log.info("Moved %s → %s/%s", name, target.container_name, name)


def _ingest_from_blob(args: argparse.Namespace, database_url: str) -> None:
    import os
    import tempfile

    from azure.storage.blob import BlobServiceClient

    from .core import read_jsonl

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        log.error("AZURE_STORAGE_CONNECTION_STRING is not set")
        sys.exit(1)

    service = BlobServiceClient.from_connection_string(conn_str)
    pending = service.get_container_client("pending")
    processed = service.get_container_client("processed")
    failed = service.get_container_client("failed")

    blobs = list(pending.list_blobs())
    if not blobs:
        log.info("No pending blobs to process")
        print("total=0 inserted=0 skipped=0 blobs=0 failed=0")
        return

    total = inserted = skipped = failed_count = 0
    for blob_props in blobs:
        name = blob_props.name
        log.info("Processing blob: %s", name)
        data = pending.download_blob(name).readall()

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        try:
            try:
                records = read_jsonl(tmp_path)
            except (ValueError, UnicodeDecodeError) as exc:
                log.exception("Blob %s is unparseable — moving to failed/", name)
                failed_count += 1
                if not args.dry_run:
                    _move_blob(
                        pending,
                        failed,
                        name,
                        data,
                        metadata={
                            "reason": "unparseable_jsonl",
                            "error": str(exc)[:200],
                        },
                    )
                continue
        finally:
            tmp_path.unlink(missing_ok=True)

        if not records:
            log.warning(
                "Blob %s had no records — moving to processed (no-op success)",
                name,
            )
            if not args.dry_run:
                _move_blob(pending, processed, name, data)
            continue

        result = _connect_and_ingest(records, args, database_url)
        total += result["total"]
        inserted += result["inserted"]
        skipped += result["skipped"]

        if not args.dry_run:
            _move_blob(pending, processed, name, data)
        else:
            log.info("Dry run — skipping blob move for %s", name)

    print(
        f"total={total} inserted={inserted} skipped={skipped} "
        f"blobs={len(blobs)} failed={failed_count} "
        f"dry_run={str(args.dry_run).lower()}"
    )


def _cmd_ingest(args: argparse.Namespace) -> None:
    import os

    from .core import read_jsonl

    database_url = args.db_url or os.environ.get("DATABASE_URL")
    if not database_url:
        log.error("No database URL: pass --db-url or set DATABASE_URL in .env")
        sys.exit(1)

    if args.blob_mode:
        _ingest_from_blob(args, database_url)
        return

    if not args.input:
        log.error("--input is required when not using --blob-mode")
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    records = read_jsonl(input_path)
    if not records:
        log.warning("No records found in %s", input_path)
        print(f"total=0 inserted=0 skipped=0 dry_run={str(args.dry_run).lower()}")
        return

    log.info("Loaded %d records from %s", len(records), input_path)
    result = _connect_and_ingest(records, args, database_url)

    print(
        f"total={result['total']} "
        f"inserted={result['inserted']} "
        f"skipped={result['skipped']} "
        f"dry_run={str(result['dry_run']).lower()}"
    )


def _add_ingest(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "ingest",
        help="Ingest scored JSONL records into raw.scored_job_postings",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="PostgreSQL connection string (falls back to DATABASE_URL env var)",
    )
    p.add_argument(
        "--input",
        default=None,
        help="Path to scored JSONL file (required unless --blob-mode)",
    )
    p.add_argument("--schema-path", required=True, help="Path to db/schema.sql")
    p.add_argument(
        "--apply-schema", action="store_true", help="Apply schema DDL before ingesting"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Parse records but do not write to DB"
    )
    p.add_argument(
        "--blob-mode",
        action="store_true",
        help=(
            "Pull from Azure Blob Storage 'pending' container instead of --input. "
            "Requires AZURE_STORAGE_CONNECTION_STRING env var."
        ),
    )
    p.set_defaults(func=_cmd_ingest)


def register(sub: argparse._SubParsersAction) -> None:
    _add_ingest(sub)


def main(argv: list[str] | None = None) -> int:
    """Standalone entrypoint for container use — flat parser, no subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Ingest scored JSONL into raw.scored_job_postings"
    )
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--input", default=None)
    parser.add_argument("--schema-path", required=True)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--blob-mode",
        action="store_true",
        help="Pull from Azure Blob Storage 'pending' container",
    )
    args = parser.parse_args(argv)
    if not args.blob_mode and not args.input:
        parser.error("--input is required unless --blob-mode is set")
    _cmd_ingest(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
