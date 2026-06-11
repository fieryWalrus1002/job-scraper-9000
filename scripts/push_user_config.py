#!/usr/bin/env python3
"""Push a user's filled-in config templates into Postgres (Phase 12, spec §4).

The admin onboarding path: validate a friend's hand-filled intake template(s)
against the shared Pydantic models, then upsert into app.candidate_profiles /
app.user_search_configs. This is how users get configured on day one, before
the frontend settings form exists.

Fails fast and loud on an unknown user or an invalid payload — a silently
skipped typo would mean a config no-op that nobody notices until a run produces
nothing.

Usage:
    uv run scripts/push_user_config.py --user-email a@b.com \\
        --profile config/profile/alice.yml --search config/search/alice.yml
    uv run scripts/push_user_config.py --user-email a@b.com --search alice.yml

At least one of --profile / --search is required. The profile push prints the
computed profile_version (date.sha12 over the canonical payload) so the admin
can confirm what landed.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv
from psycopg.types.json import Json
from pydantic import ValidationError

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from user_config import (  # noqa: E402
    CandidateProfileInput,
    SearchConfigInput,
    compute_profile_version,
    derive_policies,
)

load_dotenv()
log = logging.getLogger(__name__)


def _resolve_user_id(conn: psycopg.Connection, email: str) -> str:
    row = conn.execute(
        "SELECT id FROM app.users WHERE email = %(email)s",
        {"email": email.strip().lower()},
    ).fetchone()
    if row is None:
        raise SystemExit(
            f"No app.users row for email {email!r}. Invite the user first "
            "(the email must already be in app.users)."
        )
    return row[0]


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return data


def _push_profile(conn: psycopg.Connection, user_id: str, path: Path) -> None:
    try:
        profile = CandidateProfileInput.model_validate(_load_yaml(path))
    except ValidationError as exc:
        raise SystemExit(f"{path} is not a valid candidate profile:\n{exc}") from exc

    # Store the human-facing format (what the form edits), not the pipeline
    # shape. profile_version is computed here and never client-supplied.
    payload = profile.model_dump(mode="json")
    version = compute_profile_version(payload)
    conn.execute(
        """
        INSERT INTO app.candidate_profiles (user_id, payload, profile_version)
        VALUES (%(user_id)s, %(payload)s, %(version)s)
        ON CONFLICT (user_id) DO UPDATE
        SET payload = EXCLUDED.payload,
            profile_version = EXCLUDED.profile_version,
            updated_at = now()
        """,
        {"user_id": user_id, "payload": Json(payload), "version": version},
    )
    log.info("profile pushed — profile_version=%s", version)


def _push_search(conn: psycopg.Connection, user_id: str, path: Path) -> None:
    try:
        search = SearchConfigInput.model_validate(_load_yaml(path))
    except ValidationError as exc:
        raise SystemExit(f"{path} is not a valid search config:\n{exc}") from exc

    payload = search.model_dump(mode="json")
    policies = derive_policies(search).model_dump(mode="json")
    conn.execute(
        """
        INSERT INTO app.user_search_configs (user_id, payload, policies)
        VALUES (%(user_id)s, %(payload)s, %(policies)s)
        ON CONFLICT (user_id) DO UPDATE
        SET payload = EXCLUDED.payload,
            policies = EXCLUDED.policies,
            updated_at = now()
        """,
        {"user_id": user_id, "payload": Json(payload), "policies": Json(policies)},
    )
    log.info("search config pushed (policies derived)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--profile", type=Path, help="candidate profile YAML")
    parser.add_argument("--search", type=Path, help="search config YAML")
    args = parser.parse_args()

    if not args.profile and not args.search:
        parser.error("at least one of --profile / --search is required")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    with psycopg.connect(database_url) as conn:
        user_id = _resolve_user_id(conn, args.user_email)
        if args.profile:
            _push_profile(conn, user_id, args.profile)
        if args.search:
            _push_search(conn, user_id, args.search)
        conn.commit()

    log.info("Done — %s", args.user_email.strip().lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
