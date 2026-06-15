#!/usr/bin/env python3
"""Toggle a user's overnight-pipeline gate (issue #245).

Flips ``app.user_search_configs.pipeline_enabled`` for one user. A deactivated
user keeps their search config + profile but is skipped by the planner, so a
dormant / test account stops burning scrape + LLM spend on every overnight run.

Fails fast and loud on an unknown user or a user with no search config row — a
silent no-op would mean an account you *think* you deactivated keeps running and
costing money.

Usage:
    uv run scripts/set_pipeline_enabled.py --user-email a@b.com --disable
    uv run scripts/set_pipeline_enabled.py --user-email a@b.com --enable
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def _set_enabled(conn: psycopg.Connection, email: str, enabled: bool) -> None:
    email = email.strip().lower()
    row = conn.execute(
        """
        UPDATE app.user_search_configs sc
        SET pipeline_enabled = %(enabled)s,
            updated_at = now()
        FROM app.users u
        WHERE u.id = sc.user_id AND u.email = %(email)s
        RETURNING sc.pipeline_enabled
        """,
        {"enabled": enabled, "email": email},
    ).fetchone()
    if row is None:
        raise SystemExit(
            f"No app.user_search_configs row for email {email!r}. The user must "
            "exist and have a pushed search config (scripts/push_user_config.py)."
        )
    log.info("%s — pipeline_enabled=%s", email, row[0])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-email", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", dest="enabled", action="store_true")
    group.add_argument("--disable", dest="enabled", action="store_false")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    with psycopg.connect(database_url) as conn:
        _set_enabled(conn, args.user_email, args.enabled)
        conn.commit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
