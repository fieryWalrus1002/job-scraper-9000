#!/usr/bin/env python3
"""Backfill salary_min_usd / salary_max_usd / salary_period for existing rows.

Runs the regex extractor against every row in raw.job_postings
in raw.job_postings that currently has a NULL salary_min_usd and a non-empty description.

Usage:
    uv run scripts/backfill_salary.py
    uv run scripts/backfill_salary.py --dry-run   # print matches without writing
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from utils.salary import extract_salary  # noqa: E402

load_dotenv()
log = logging.getLogger(__name__)

_SELECT_SQL = """
    SELECT dedup_hash, description
    FROM raw.job_postings
    WHERE salary_min_usd IS NULL
      AND description IS NOT NULL
      AND description <> ''
"""

_UPDATE_SQL = """
    UPDATE raw.job_postings
    SET salary_min_usd = %(salary_min_usd)s,
        salary_max_usd = %(salary_max_usd)s,
        salary_period  = %(salary_period)s
    WHERE dedup_hash = %(dedup_hash)s
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error("DATABASE_URL not set")
        return 1

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        rows = conn.execute(_SELECT_SQL).fetchall()
        log.info("Candidates with NULL salary: %d", len(rows))

        hits = 0
        for row in rows:
            result = extract_salary(row["description"])
            if result is None:
                continue
            hits += 1
            log.info(
                "  %s → min=%s max=%s period=%s",
                row["dedup_hash"][:12],
                result.salary_min_usd,
                result.salary_max_usd,
                result.salary_period,
            )
            if not args.dry_run:
                conn.execute(
                    _UPDATE_SQL,
                    {
                        "dedup_hash": row["dedup_hash"],
                        "salary_min_usd": result.salary_min_usd,
                        "salary_max_usd": result.salary_max_usd,
                        "salary_period": result.salary_period,
                    },
                )

        if not args.dry_run:
            conn.commit()

    log.info(
        "Done — %d/%d rows updated%s",
        hits,
        len(rows),
        " (dry run)" if args.dry_run else "",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
