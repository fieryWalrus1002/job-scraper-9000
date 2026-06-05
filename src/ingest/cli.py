#!/usr/bin/env python3
"""CLI adapter for the ingest module.

Registered as a subcommand of job-scraper-9000 via register().
Also callable standalone (docker container entrypoint) via main().

Usage (pipeline CLI — DATABASE_URL read from .env automatically):
    uv run job-scraper-9000 ingest --input <path> --schema-path db/schema.sql

Usage (standalone / container — must pass --db-url explicitly):
    python -m ingest.cli --db-url $DATABASE_URL --input <path> --schema-path db/schema.sql

Duplicate dedup_hash values are silently skipped (ON CONFLICT DO NOTHING).
"""

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _cmd_ingest(args: argparse.Namespace) -> None:
    import psycopg

    from .core import ensure_schema, ingest, read_jsonl

    import os

    database_url = args.db_url or os.environ.get("DATABASE_URL")
    if not database_url:
        log.error("No database URL: pass --db-url or set DATABASE_URL in .env")
        sys.exit(1)

    input_path = Path(args.input)
    schema_path = Path(args.schema_path)

    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    if args.apply_schema and not schema_path.exists():
        log.error("Schema file not found: %s", schema_path)
        sys.exit(1)

    records = read_jsonl(input_path)
    if not records:
        log.warning("No records found in %s", input_path)
        print("total=0 inserted=0 skipped=0 dry_run=false")
        return

    log.info("Loaded %d records from %s", len(records), input_path)

    try:
        with psycopg.connect(database_url) as conn:
            if args.apply_schema:
                ensure_schema(conn, schema_path)
            result = ingest(records, conn=conn, dry_run=args.dry_run)
    except psycopg.Error as exc:
        log.error("Database error: %s", exc)
        sys.exit(1)

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
    p.add_argument("--input", required=True, help="Path to scored JSONL file")
    p.add_argument("--schema-path", required=True, help="Path to db/schema.sql")
    p.add_argument(
        "--apply-schema", action="store_true", help="Apply schema DDL before ingesting"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Parse records but do not write to DB"
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
    parser.add_argument("--db-url", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--schema-path", required=True)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    _cmd_ingest(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
