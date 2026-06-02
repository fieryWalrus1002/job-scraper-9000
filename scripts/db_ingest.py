#!/usr/bin/env python3
"""Ingest scored JSONL records into raw.scored_job_postings.

Usage:
    uv run scripts/db_ingest.py --run-date 2026-06-01
    uv run scripts/db_ingest.py --input data/scored/2026-06-01/skills_fit_scored.jsonl
    uv run scripts/db_ingest.py --run-date 2026-06-01 --apply-schema  # first run

Reads DATABASE_URL from the environment (set in .env):
    DATABASE_URL=postgresql://jobscraper:jobscraper@localhost:5432/jobscraper

Duplicate dedup_hash values are silently skipped (ON CONFLICT DO NOTHING).
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.skills_fit.io import read_jsonl  # noqa: E402

load_dotenv()

log = logging.getLogger(__name__)

_DEFAULT_OUTPUT_PATTERN = "data/scored/{run_date}/skills_fit_scored.jsonl"
_DDL_PATH = REPO_ROOT / "db" / "schema.sql"

_PROMOTED_METADATA_KEYS = frozenset(
    {"run_id", "scored_at", "model", "provider", "profile_version", "failure_reason"}
)
_PROMOTED_AI_FIT_KEYS = frozenset({"fit_score", "confidence", "score_rationale"})

_INSERT_SQL = """
INSERT INTO raw.scored_job_postings (
    dedup_hash, source, source_job_id, source_url,
    title, company, location, posted_at, description, scraped_at,
    remote_classification,
    fit_score, confidence, score_rationale, ai_fit_detail,
    pipeline_metadata,
    run_id, scored_at, model, provider, profile_version, failure_reason,
    metadata
) VALUES (
    %(dedup_hash)s, %(source)s, %(source_job_id)s, %(source_url)s,
    %(title)s, %(company)s, %(location)s, %(posted_at)s, %(description)s, %(scraped_at)s,
    %(remote_classification)s,
    %(fit_score)s, %(confidence)s, %(score_rationale)s, %(ai_fit_detail)s::jsonb,
    %(pipeline_metadata)s::jsonb,
    %(run_id)s, %(scored_at)s, %(model)s, %(provider)s, %(profile_version)s, %(failure_reason)s,
    %(metadata)s::jsonb
)
ON CONFLICT (dedup_hash) DO NOTHING
"""


def resolve_input_path(*, run_date: str | None, input_path: str | None) -> Path:
    if input_path:
        return Path(input_path)
    if run_date:
        return Path(_DEFAULT_OUTPUT_PATTERN.format(run_date=run_date))
    raise ValueError("--run-date or --input is required")


def ensure_schema(conn: psycopg.Connection) -> None:
    conn.execute(_DDL_PATH.read_text(encoding="utf-8"))
    conn.commit()
    log.info("Schema applied from %s", _DDL_PATH)


def _extract_row(record: dict) -> dict:
    ai_fit = record.get("ai_fit") or {}
    metadata = record.get("metadata") or {}

    ai_fit_detail = {k: v for k, v in ai_fit.items() if k not in _PROMOTED_AI_FIT_KEYS}
    leftover_metadata = {
        k: v for k, v in metadata.items() if k not in _PROMOTED_METADATA_KEYS
    }

    return {
        "dedup_hash": record["dedup_hash"],
        "source": record.get("source"),
        "source_job_id": record.get("source_job_id"),
        "source_url": record.get("source_url"),
        "title": record.get("title"),
        "company": record.get("company"),
        "location": record.get("location"),
        "posted_at": record.get("posted_at"),
        "description": record.get("description"),
        "scraped_at": record.get("scraped_at"),
        "remote_classification": record.get("remote_classification"),
        "fit_score": ai_fit.get("fit_score"),
        "confidence": ai_fit.get("confidence"),
        "score_rationale": ai_fit.get("score_rationale"),
        "ai_fit_detail": json.dumps(ai_fit_detail) if ai_fit_detail else None,
        "pipeline_metadata": json.dumps(record.get("pipeline_metadata") or {}),
        "run_id": metadata.get("run_id", ""),
        "scored_at": metadata.get("scored_at"),
        "model": metadata.get("model", ""),
        "provider": metadata.get("provider", ""),
        "profile_version": metadata.get("profile_version", ""),
        "failure_reason": metadata.get("failure_reason"),
        "metadata": json.dumps(leftover_metadata),
    }


def ingest(
    records: list[dict], *, conn: psycopg.Connection, dry_run: bool = False
) -> dict:
    rows = [_extract_row(r) for r in records]

    if dry_run:
        log.info("Dry run — would ingest %d records (no writes)", len(rows))
        return {"total": len(rows), "inserted": 0, "skipped": 0, "dry_run": True}

    inserted = 0
    skipped = 0
    with conn.transaction():
        for row in rows:
            cur = conn.execute(_INSERT_SQL, row)
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    log.info("Ingested %d new rows, skipped %d duplicates", inserted, skipped)
    return {
        "total": len(rows),
        "inserted": inserted,
        "skipped": skipped,
        "dry_run": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest scored JSONL into raw.scored_job_postings"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-date", metavar="YYYY-MM-DD")
    group.add_argument("--input", metavar="PATH")
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="Run db/schema.sql first (idempotent; pass on first use or after schema changes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse records but do not write to the database",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error("DATABASE_URL environment variable is not set")
        return 1

    try:
        input_path = resolve_input_path(run_date=args.run_date, input_path=args.input)
    except ValueError as exc:
        log.error(str(exc))
        return 1

    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        return 1

    records = read_jsonl(input_path)
    if not records:
        log.warning("No records found in %s", input_path)
        return 0

    log.info("Loaded %d records from %s", len(records), input_path)

    try:
        with psycopg.connect(database_url) as conn:
            if args.apply_schema:
                ensure_schema(conn)
            result = ingest(records, conn=conn, dry_run=args.dry_run)
    except psycopg.Error as exc:
        log.error("Database error: %s", exc)
        return 1

    print(
        f"total={result['total']} inserted={result['inserted']} "
        f"skipped={result['skipped']} dry_run={result['dry_run']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
