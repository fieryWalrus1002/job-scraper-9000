#!/usr/bin/env python3
"""Materialize DB user configs → the YAML files the pipeline consumes (spec §4).

The pipeline never learns about the DB (spec decision 4): this script reads
app.candidate_profiles / app.user_search_configs and writes, per user, the
``search.yml`` + ``candidate_profile.yml`` shapes the existing pipeline already
eats, plus a ``policies.yml`` for traceability (the pipeline doesn't consume
policies yet — Phase 13's concern; they're emitted so the admin can diff and
Phase 13 has a materialized artifact).

Output: ``runs/<email-slug>/{search.yml,candidate_profile.yml,policies.yml}``.
The email slug ( @ and . → _ ) keys the dir so two users never collide.

Per §8 verification: the emitted search.yml / candidate_profile.yml should diff
functionally identical to the hand-maintained files. policies.yml is new (the
hand-maintained world had no separate policies artifact), so it has no
hand-maintained counterpart to diff against.

Usage:
    uv run scripts/pull_user_configs.py --user-email a@b.com
    uv run scripts/pull_user_configs.py --all
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from user_config import (  # noqa: E402
    CandidateProfileInput,
    SearchConfigInput,
    candidate_profile_to_pipeline_yaml,
    dump_yaml,
    search_config_to_pipeline_yaml,
)

load_dotenv()
log = logging.getLogger(__name__)

RUNS_DIR = REPO_ROOT / "runs"

# Pull both config rows for a user in one query. LEFT JOINs so a user with only
# one of the two configured still materializes what they have (and we warn on
# the missing half rather than skip them silently).
_SELECT_SQL = """
    SELECT
        u.email                  AS email,
        cp.payload               AS profile_payload,
        cp.profile_version       AS profile_version,
        sc.payload               AS search_payload,
        sc.policies              AS policies
    FROM app.users u
    LEFT JOIN app.candidate_profiles  cp ON cp.user_id = u.id
    LEFT JOIN app.user_search_configs sc ON sc.user_id = u.id
    {where}
    ORDER BY u.email
"""


def _slug(email: str) -> str:
    """Filesystem-safe, collision-free dir name from an email."""
    return re.sub(r"[^a-z0-9._-]", "_", email.strip().lower()).replace(".", "_")


def _materialize(row: dict) -> None:
    email = row["email"]
    if row["profile_payload"] is None and row["search_payload"] is None:
        log.info("%s — no configs yet, skipping", email)
        return

    run_dir = RUNS_DIR / _slug(email)
    run_dir.mkdir(parents=True, exist_ok=True)

    if row["search_payload"] is not None:
        search = SearchConfigInput.model_validate(row["search_payload"])
        (run_dir / "search.yml").write_text(
            dump_yaml(search_config_to_pipeline_yaml(search))
        )
        # Emit the stored policies verbatim (the API may let users edit these
        # independently of the search-derived defaults — DB is source of truth).
        (run_dir / "policies.yml").write_text(dump_yaml(row["policies"] or {}))
    else:
        log.warning("%s — has a profile but no search config", email)

    if row["profile_payload"] is not None:
        profile = CandidateProfileInput.model_validate(row["profile_payload"])
        version = row["profile_version"]
        (run_dir / "candidate_profile.yml").write_text(
            dump_yaml(
                candidate_profile_to_pipeline_yaml(profile, profile_version=version)
            )
        )
        log.info("%s → %s (profile_version=%s)", email, run_dir, version)
    else:
        log.warning("%s — has a search config but no profile", email)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-email")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    if args.all:
        where, params = "", {}
    else:
        where = "WHERE u.email = %(email)s"
        params = {"email": args.user_email.strip().lower()}

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(_SELECT_SQL.format(where=where), params).fetchall()

    if not rows:
        raise SystemExit(
            "No matching users."
            if args.all
            else f"No app.users row for email {args.user_email!r}."
        )

    for row in rows:
        _materialize(row)

    log.info("Done — materialized %d user(s) under %s", len(rows), RUNS_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
