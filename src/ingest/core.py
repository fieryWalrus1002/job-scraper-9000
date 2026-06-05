import json
import logging
from pathlib import Path
from typing import Any

import psycopg

log = logging.getLogger(__name__)

_PROMOTED_METADATA_KEYS = frozenset(
    {"run_id", "scored_at", "model", "provider", "profile_version", "failure_reason"}
)
_PROMOTED_AI_FIT_KEYS = frozenset({"fit_score", "confidence", "score_rationale"})

_INSERT_SQL = """
INSERT INTO raw.scored_job_postings (
    dedup_hash, source, source_job_id, source_url,
    title, company, location, posted_at, description, scraped_at,
    remote_classification,
    salary_min_usd, salary_max_usd, salary_period,
    fit_score, confidence, score_rationale, ai_fit_detail,
    pipeline_metadata,
    run_id, scored_at, model, provider, profile_version, failure_reason,
    metadata
) VALUES (
    %(dedup_hash)s, %(source)s, %(source_job_id)s, %(source_url)s,
    %(title)s, %(company)s, %(location)s, %(posted_at)s, %(description)s, %(scraped_at)s,
    %(remote_classification)s,
    %(salary_min_usd)s, %(salary_max_usd)s, %(salary_period)s,
    %(fit_score)s, %(confidence)s, %(score_rationale)s, %(ai_fit_detail)s::jsonb,
    %(pipeline_metadata)s::jsonb,
    %(run_id)s, %(scored_at)s, %(model)s, %(provider)s, %(profile_version)s, %(failure_reason)s,
    %(metadata)s::jsonb
)
ON CONFLICT (dedup_hash) DO NOTHING
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def ensure_schema(conn: psycopg.Connection, schema_path: Path) -> None:
    """Explicitly injected schema dependency."""
    raw_sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(raw_sql)  # type: ignore[argument-type]
    conn.commit()
    log.info("Schema applied successfully from %s", schema_path)


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
        "salary_min_usd": record.get("salary_min_usd"),
        "salary_max_usd": record.get("salary_max_usd"),
        "salary_period": record.get("salary_period"),
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
