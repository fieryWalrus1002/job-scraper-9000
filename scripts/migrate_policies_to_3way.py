#!/usr/bin/env python3
"""Re-derive stored per-user remote policies to the Phase 32 3-way axis.

Background: Phase 32 (#520) changed the remote_filter classification axis
(``fully_remote`` -> ``remote``; dropped ``onsite_disguised`` /
``location_restricted`` / ``unclear``). ``derive_policies`` was updated, but the
policies stored in ``app.user_search_configs`` were derived by the *pre*-Phase-32
transform and never regenerated. The scoring gate (``pipeline.scoring._gate_user``)
exact-matches a job's classification against ``acceptable_classifications``, so a
stored ``fully_remote`` never matches the new ``remote`` output — **silently
dropping every remote job for affected users** (found in the 2026-07-20 overnight
run: all scored postings were ``hybrid``; 0 of 653 remote jobs survived the gate).

This migration re-derives each stored search *payload* through the CURRENT
``derive_policies`` — identical to what ``scripts/push_user_config.py`` does on a
push, but sourced from the authoritative DB payload (so it needs no intake YAMLs
on disk) and applied to every user at once. It also regenerates
``acceptable_locations`` (the secondary local-presence gap from the same cause).

**Dry-run by default:** prints old -> new ``acceptable_classifications`` /
``acceptable_locations`` per user and writes nothing. Pass ``--apply`` to persist.

Usage:
    uv run scripts/migrate_policies_to_3way.py                  # dry-run, all users
    uv run scripts/migrate_policies_to_3way.py --user-email a@b.com
    uv run scripts/migrate_policies_to_3way.py --apply          # persist
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import ValidationError

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from user_config import SearchConfigInput, derive_policies  # noqa: E402

load_dotenv()
log = logging.getLogger(__name__)

_SELECT = """
    SELECT u.email AS email, sc.user_id AS user_id,
           sc.payload AS payload, sc.policies AS policies
    FROM app.user_search_configs sc
    JOIN app.users u ON u.id = sc.user_id
    {where}
    ORDER BY u.email
"""


def _accept(policies: dict) -> list:
    return ((policies or {}).get("remote") or {}).get(
        "acceptable_classifications"
    ) or []


def _locs(policies: dict) -> list:
    return ((policies or {}).get("relocation") or {}).get("acceptable_locations") or []


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--user-email", help="Limit to one user (default: all)")
    parser.add_argument(
        "--apply", action="store_true", help="Persist changes (default: dry-run)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    where = "WHERE u.email = %(email)s" if args.user_email else ""
    params = {"email": args.user_email.strip().lower()} if args.user_email else {}

    changes: list[tuple[str, str, dict, dict, dict]] = []
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(_SELECT.format(where=where), params).fetchall()
        if not rows:
            raise SystemExit("No app.user_search_configs rows matched.")

        for row in rows:
            email = row["email"]
            try:
                search = SearchConfigInput.model_validate(row["payload"])
            except ValidationError as exc:
                # Fail loud — a stored payload that no longer validates is real
                # drift that must be fixed by hand, not silently skipped.
                raise SystemExit(
                    f"{email}: stored search payload no longer validates against "
                    f"SearchConfigInput:\n{exc}"
                ) from exc
            new_policies = derive_policies(search).model_dump(mode="json")
            old_policies = row["policies"] or {}
            if new_policies == old_policies:
                log.info("%s — already current, skipping", email)
                continue
            changes.append(
                (email, row["user_id"], old_policies, new_policies, new_policies)
            )

        mode = "APPLY" if args.apply else "DRY-RUN"
        print("\n" + "=" * 72)
        print(f"  {mode} — {len(changes)} user(s) with policy changes")
        print("=" * 72)
        for email, _uid, old_p, new_p, _ in changes:
            print(f"\n{email}")
            print(f"  acceptable_classifications: {_accept(old_p)}")
            print(f"                          ->  {_accept(new_p)}")
            if _locs(old_p) != _locs(new_p):
                print(f"  acceptable_locations:       {_locs(old_p)}")
                print(f"                          ->  {_locs(new_p)}")

        if not changes:
            print("\nNothing to change — all stored policies are already 3-way.")
            return 0

        if not args.apply:
            print("\n(dry-run — no writes. Re-run with --apply to persist.)")
            return 0

        for email, uid, _old, new_p, _ in changes:
            conn.execute(
                "UPDATE app.user_search_configs SET policies = %(policies)s "
                "WHERE user_id = %(user_id)s",
                {"policies": Json(new_p), "user_id": uid},
            )
        conn.commit()
        print(f"\nApplied {len(changes)} policy update(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
