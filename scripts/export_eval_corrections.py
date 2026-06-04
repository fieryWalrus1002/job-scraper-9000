#!/usr/bin/env python3
"""Export dashboard-sourced eval corrections to JSONL gold-set format.

Reads from `app.eval_corrections` joined with `raw.scored_job_postings`,
filtered by `(original_model, profile_version)` so re-runs against a new
(model, profile) start from a clean baseline.

The output schema mirrors `data/eval/skills_fit_ground_truth.jsonl`:
full scraped job context + `_skills_fit_*` fields from the AI's existing
output + `_human_*` fields from the correction. The eval harness's
`load_gold()` uses "last entry per dedup_hash wins", so the corrections
file can either:
  - be loaded standalone via `--gold-file <out>` (if the harness ever
    grows that flag), or
  - be concatenated with the existing ground truth and re-run:
        cat data/eval/skills_fit_ground_truth.jsonl \\
            data/eval/skills_fit_corrections_gold.jsonl \\
            > /tmp/merged_gold.jsonl

Each record gets `_human_source: "dashboard"` so it's distinguishable from
records produced by `scripts/propose_skills_fit_seed.py` (which would
carry `_teacher_*` fields, not `_human_source`).

Usage:
    uv run scripts/export_eval_corrections.py \\
        --model gpt-4o-mini \\
        --profile-version 2026-05-26-v6-growth-skills-and-scope-cleanup

    uv run scripts/export_eval_corrections.py \\
        --model gpt-4o-mini --profile-version v6 \\
        --out data/eval/skills_fit_corrections_gold.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

log = logging.getLogger(__name__)

DEFAULT_OUT = Path("data/eval/skills_fit_corrections_gold.jsonl")

_SELECT_SQL = """
    SELECT
        c.dedup_hash,
        c.corrected_score,
        c.correction_reason,
        c.original_score,
        c.original_model,
        c.profile_version,
        c.corrected_at,

        j.source, j.source_job_id, j.source_url,
        j.title, j.company, j.location, j.posted_at, j.description,
        j.scraped_at,
        j.remote_classification::TEXT AS remote_classification,
        j.salary_min_usd, j.salary_max_usd, j.salary_period,

        j.fit_score, j.confidence::TEXT AS confidence, j.score_rationale,
        j.ai_fit_detail,
        j.run_id, j.scored_at, j.model AS scored_model, j.provider,
        j.profile_version AS scored_profile_version
    FROM app.eval_corrections c
    JOIN raw.scored_job_postings j USING (dedup_hash)
    WHERE c.original_model = %(model)s
      AND c.profile_version = %(profile_version)s
    ORDER BY c.corrected_at DESC
"""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def build_gold_record(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a joined (correction, job) row into the gold-set JSONL schema.

    Mirrors fields in `data/eval/skills_fit_ground_truth.jsonl`:
      - raw scraped job context
      - `_skills_fit_*` — the existing AI output (used as input context, not
        as ground truth)
      - `_human_*` — the corrected ground truth, with `_human_fit_score`
        being the value the eval harness reads via `load_gold()`
      - `_human_source` = "dashboard" — provenance tag distinguishing
        dashboard corrections from sampled-seed proposals
      - `_correction_metadata` — snapshots at correction time
    """
    ai = row.get("ai_fit_detail") or {}
    if not isinstance(ai, dict):
        ai = {}

    return {
        # ── Scraped job context ─────────────────────────────
        "source": row["source"],
        "source_job_id": row["source_job_id"],
        "source_url": row["source_url"],
        "title": row["title"],
        "company": row["company"],
        "location": row["location"],
        "posted_at": row["posted_at"],
        "description": row["description"],
        "scraped_at": row["scraped_at"],
        "dedup_hash": row["dedup_hash"],
        "remote_classification": row["remote_classification"],
        "salary_min_usd": row["salary_min_usd"],
        "salary_max_usd": row["salary_max_usd"],
        "salary_period": row["salary_period"],
        # ── AI output (existing) ────────────────────────────
        "_skills_fit_score": row["fit_score"],
        "_skills_fit_confidence": row["confidence"],
        "_skills_fit_rationale": row["score_rationale"],
        "_skills_fit_top_matches": ai.get("top_matches", []),
        "_skills_fit_gaps": ai.get("gaps", []),
        "_skills_fit_hard_concerns": ai.get("hard_concerns", []),
        "_skills_fit_core_job_duties": ai.get("core_job_duties", []),
        "_skills_fit_metadata": {
            "model": row["scored_model"],
            "provider": row["provider"],
            "profile_version": row["scored_profile_version"],
            "run_id": row["run_id"],
            "scored_at": row["scored_at"],
        },
        # ── Human gold label (from correction) ──────────────
        "_human_fit_score": row["corrected_score"],
        "_human_confidence": None,
        "_human_top_matches": [],
        "_human_gaps": [],
        "_human_hard_concerns": [],
        "_human_notes": row["correction_reason"] or "",
        "_human_source": "dashboard",
        # ── Correction provenance (snapshots at correction time) ──
        "_correction_metadata": {
            "original_score": row["original_score"],
            "original_model": row["original_model"],
            "profile_version": row["profile_version"],
            "corrected_at": row["corrected_at"],
        },
    }


def export_corrections(
    *,
    model: str,
    profile_version: str,
    out_path: Path,
    database_url: str,
) -> int:
    """Read corrections + joined jobs, write gold JSONL. Returns row count."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with psycopg.connect(database_url) as conn:
        conn.row_factory = dict_row
        with conn.cursor() as cur:
            cur.execute(
                _SELECT_SQL, {"model": model, "profile_version": profile_version}
            )
            with open(out_path, "w") as f:
                for row in cur:
                    record = build_gold_record(row)
                    f.write(json.dumps(record, default=_json_default) + "\n")
                    count += 1
    return count


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error(
            "DATABASE_URL is not set. Put it in .env, e.g. "
            "postgresql://jobscraper:jobscraper@localhost:5432/jobscraper"
        )
        sys.exit(2)
    return url


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--model",
        required=True,
        help="Filter corrections by original_model (snapshotted at correction time)",
    )
    p.add_argument(
        "--profile-version",
        required=True,
        help="Filter corrections by profile_version (snapshotted at correction time)",
    )
    p.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Output JSONL path (default: {DEFAULT_OUT})",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out_path = Path(args.out)

    n = export_corrections(
        model=args.model,
        profile_version=args.profile_version,
        out_path=out_path,
        database_url=_database_url(),
    )

    if n == 0:
        log.info(
            "No corrections found for model=%s profile_version=%s. "
            "Wrote empty file to %s",
            args.model,
            args.profile_version,
            out_path,
        )
    else:
        log.info(
            "Wrote %d correction(s) to %s (filter: model=%s profile_version=%s)",
            n,
            out_path,
            args.model,
            args.profile_version,
        )


if __name__ == "__main__":
    main()
