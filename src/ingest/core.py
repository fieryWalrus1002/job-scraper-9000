import json
import logging
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import tuple_row

log = logging.getLogger(__name__)

_PROMOTED_METADATA_KEYS = frozenset(
    {"run_id", "scored_at", "model", "provider", "profile_version", "failure_reason"}
)
_PROMOTED_AI_FIT_KEYS = frozenset({"fit_score", "confidence", "score_rationale"})

# Shared posting storage: first scrape wins on conflict.
_POSTING_INSERT_SQL = """
INSERT INTO raw.job_postings (
    dedup_hash, source, source_job_id, source_url,
    title, company, location, posted_at, description, scraped_at,
    remote_classification,
    salary_min_usd, salary_max_usd, salary_period,
    pipeline_metadata, metadata
) VALUES (
    %(dedup_hash)s, %(source)s, %(source_job_id)s, %(source_url)s,
    %(title)s, %(company)s, %(location)s, %(posted_at)s, %(description)s, %(scraped_at)s,
    %(remote_classification)s,
    %(salary_min_usd)s, %(salary_max_usd)s, %(salary_period)s,
    %(pipeline_metadata)s::jsonb, %(metadata)s::jsonb
)
ON CONFLICT (dedup_hash) DO NOTHING
"""

# Per-user scores: re-runs are last-write-wins (a DO NOTHING here would
# strand stale scores forever once the profile evolves).
_SCORE_UPSERT_SQL = """
INSERT INTO raw.job_scores (
    user_id, dedup_hash,
    fit_score, confidence, score_rationale, ai_fit_detail,
    run_id, scored_at, model, provider, profile_version, failure_reason
) VALUES (
    %(user_id)s, %(dedup_hash)s,
    %(fit_score)s, %(confidence)s, %(score_rationale)s, %(ai_fit_detail)s::jsonb,
    %(run_id)s, %(scored_at)s, %(model)s, %(provider)s, %(profile_version)s,
    %(failure_reason)s
)
ON CONFLICT (user_id, dedup_hash) DO UPDATE SET
    fit_score       = EXCLUDED.fit_score,
    confidence      = EXCLUDED.confidence,
    score_rationale = EXCLUDED.score_rationale,
    ai_fit_detail   = EXCLUDED.ai_fit_detail,
    run_id          = EXCLUDED.run_id,
    scored_at       = EXCLUDED.scored_at,
    model           = EXCLUDED.model,
    provider        = EXCLUDED.provider,
    profile_version = EXCLUDED.profile_version,
    failure_reason  = EXCLUDED.failure_reason,
    ingested_at     = now()
RETURNING (xmax = 0) AS inserted
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _strip_nul(record: dict) -> dict:
    """Recursively drop NUL bytes (U+0000) from every string in the record.

    Postgres cannot store U+0000 in ``text`` or ``jsonb`` columns, so a single
    stray NUL — scraped descriptions and LLM output occasionally carry one —
    otherwise fails the whole ingest batch with UntranslatableCharacter. We
    scrub rather than crash, but count and WARN so it is never silent.
    """
    nul_count = 0

    def scrub(value: Any) -> Any:
        nonlocal nul_count
        if isinstance(value, str):
            nul_count += value.count("\x00")
            return value.replace("\x00", "")
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    cleaned = scrub(record)
    if nul_count:
        log.warning(
            "Stripped %d NUL byte(s) from record dedup_hash=%s before ingest "
            "(Postgres cannot store U+0000)",
            nul_count,
            cleaned.get("dedup_hash"),
        )
    return cleaned


def _extract_row(record: dict) -> dict:
    record = _strip_nul(record)
    ai_fit = record.get("ai_fit") or {}
    metadata = record.get("metadata") or {}

    ai_fit_detail = {k: v for k, v in ai_fit.items() if k not in _PROMOTED_AI_FIT_KEYS}
    leftover_metadata = {
        k: v for k, v in metadata.items() if k not in _PROMOTED_METADATA_KEYS
    }

    return {
        "dedup_hash": record["dedup_hash"],
        "user_email": record.get("user_email"),
        "source": record.get("source"),
        "source_job_id": record.get("source_job_id"),
        "source_url": record.get("source_url"),
        "title": record.get("title"),
        "company": record.get("company"),
        "location": record.get("location"),
        "posted_at": record.get("posted_at") or record.get("scraped_at"),
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


def resolve_user_ids(
    conn: psycopg.Connection, rows: list[dict], default_user_email: str | None
) -> None:
    """Attach user_id to every row, resolving emails against app.users.

    Each record carries its own user_email (multi-user batches are legal);
    --user-email supplies a default for records without one. Any record with
    no resolvable user fails the whole batch — silently assigning scores to
    the wrong feed is the one unrecoverable mistake here.
    """
    for i, row in enumerate(rows):
        email = row.get("user_email") or default_user_email
        if not email:
            raise ValueError(
                f"Record {i} (dedup_hash={row['dedup_hash']!r}) has no user_email "
                "and no --user-email default was given"
            )
        row["user_email"] = email.strip().lower()

    emails = sorted({row["user_email"] for row in rows})
    # Explicit tuple rows: callers may hand us dict_row connections.
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT email, id FROM app.users WHERE email = ANY(%(emails)s)",
            {"emails": emails},
        )
        id_by_email = dict(cur.fetchall())

    unknown = [e for e in emails if e not in id_by_email]
    if unknown:
        raise ValueError(
            f"Unknown user email(s) {unknown} — no matching app.users rows. "
            "Users are provisioned from config/auth.yml at API startup."
        )

    for row in rows:
        row["user_id"] = id_by_email[row["user_email"]]


def ingest(
    records: list[dict],
    *,
    conn: psycopg.Connection,
    dry_run: bool = False,
    default_user_email: str | None = None,
) -> dict:
    rows = [_extract_row(r) for r in records]

    if dry_run:
        log.info("Dry run — would ingest %d records (no writes)", len(rows))
        return {
            "total": len(rows),
            "postings_inserted": 0,
            "scores_inserted": 0,
            "scores_updated": 0,
            "dry_run": True,
        }

    postings_inserted = 0
    scores_inserted = 0
    scores_updated = 0
    with conn.transaction():
        resolve_user_ids(conn, rows, default_user_email)
        with conn.cursor(row_factory=tuple_row) as cur:
            for row in rows:
                cur.execute(_POSTING_INSERT_SQL, row)
                if cur.rowcount == 1:
                    postings_inserted += 1
                cur.execute(_SCORE_UPSERT_SQL, row)
                result = cur.fetchone()
                if result and result[0]:
                    scores_inserted += 1
                else:
                    scores_updated += 1

    log.info(
        "Ingested %d records: %d new postings, %d new scores, %d re-scored",
        len(rows),
        postings_inserted,
        scores_inserted,
        scores_updated,
    )
    return {
        "total": len(rows),
        "postings_inserted": postings_inserted,
        "scores_inserted": scores_inserted,
        "scores_updated": scores_updated,
        "dry_run": False,
    }
