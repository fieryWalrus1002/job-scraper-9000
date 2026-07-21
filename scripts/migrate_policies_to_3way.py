#!/usr/bin/env python3
"""Re-derive stored per-user remote policies to the Phase 32 3-way axis.

Background: Phase 32 (#520) narrowed the remote_filter *classifier output* axis
to ``remote`` / ``hybrid`` / ``onsite`` (``fully_remote`` -> ``remote``; retired
``onsite_disguised`` / ``location_restricted`` / ``unclear`` as emitted labels).
``derive_policies`` was updated, but the policies stored in
``app.user_search_configs`` were derived by the *pre*-Phase-32 transform and never
regenerated. The scoring gate (``pipeline.scoring._gate_user``) exact-matches a
job's classification against the policy's ``acceptable_classifications``, so a
stored ``fully_remote`` never matches the new ``remote`` output — **silently
dropping every remote job for affected users** (found in the 2026-07-20 overnight
run: all scored postings were ``hybrid``; 0 of 653 remote jobs survived the gate).

Note the two axes are distinct: the classifier no longer *emits* ``unclear``, but
``derive_policies`` still keeps ``unclear`` in the acceptable *policy* set as a
permissive backstop for historical/default rows. This migration only re-derives
the policy set through the current transform; it does not itself decide policy.

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
    FOR UPDATE OF sc
"""


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    """Flatten a nested policy dict to ``dotted.path -> leaf`` for diffing.

    Lists and scalars are treated as leaves so a changed ``acceptable_locations``
    shows as one line rather than exploding per element.
    """
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: value}


def _policy_diff(old: dict, new: dict) -> list[tuple[str, object, object]]:
    """Every leaf field that differs between two policy objects, sorted by path."""
    flat_old, flat_new = _flatten(old), _flatten(new)
    paths = sorted(set(flat_old) | set(flat_new))
    _MISSING = object()
    diffs: list[tuple[str, object, object]] = []
    for p in paths:
        o, n = flat_old.get(p, _MISSING), flat_new.get(p, _MISSING)
        if o != n:
            diffs.append(
                (p, None if o is _MISSING else o, None if n is _MISSING else n)
            )
    return diffs


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

    changes: list[tuple[str, str, dict, dict]] = []
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
            changes.append((email, row["user_id"], old_policies, new_policies))

        mode = "APPLY" if args.apply else "DRY-RUN"
        print("\n" + "=" * 72)
        print(f"  {mode} — {len(changes)} user(s) with policy changes")
        print("=" * 72)
        for email, _uid, old_p, new_p in changes:
            print(f"\n{email}")
            # Full leaf-level diff: the dry-run preview must match the write
            # surface (the entire policies object is what --apply persists).
            for path, old_val, new_val in _policy_diff(old_p, new_p):
                print(f"  {path}:")
                print(f"      {old_val!r}")
                print(f"  ->  {new_val!r}")

        if not changes:
            print("\nNothing to change — all stored policies are already 3-way.")
            return 0

        if not args.apply:
            print("\n(dry-run — no writes. Re-run with --apply to persist.)")
            return 0

        for email, uid, _old, new_p in changes:
            conn.execute(
                "UPDATE app.user_search_configs "
                "SET policies = %(policies)s, updated_at = now() "
                "WHERE user_id = %(user_id)s",
                {"policies": Json(new_p), "user_id": uid},
            )
        conn.commit()
        print(f"\nApplied {len(changes)} policy update(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
