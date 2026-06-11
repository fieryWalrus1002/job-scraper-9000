"""app.users provisioning: startup sync from auth.yml + JIT linking on login.

The allowlist in config/auth.yml stays the gate (who may enter); this module
keeps app.users in step with it. Rows are created by email at startup, and a
user's stable external id (Entra oid) is linked on their first authenticated
request. Joins are always on (identity_provider, external_id) after that, so
an email rotation in Entra never orphans a user's data.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import HTTPException

from .auth import AuthUser, Principal

log = logging.getLogger(__name__)

_USER_COLS = """
    id, external_id, identity_provider, email, display_name, role,
    created_at, last_login_at, starter_seeded_at
"""


async def sync_users(conn, users: list[AuthUser]) -> None:
    """Upsert app.users rows from the auth.yml allowlist (lifespan startup).

    Creates rows for new emails and keeps roles in step with the config.
    Removal from auth.yml only revokes access at the gate — rows remain.
    """
    for u in users:
        await conn.execute(
            """
            INSERT INTO app.users (email, role)
            VALUES (%(email)s, %(role)s)
            ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role
            """,
            {"email": u.email, "role": u.role},
        )
    log.info("Synced %d allowlisted users into app.users", len(users))


async def get_or_provision_user(conn, principal: Principal) -> dict[str, Any]:
    """Resolve a Principal to its app.users row, JIT-linking on first login."""
    if principal.identity_provider == "dev":
        # Bypass mode acts as the bootstrap admin: local data (job scores,
        # applications) is owned by that row after the 0007 backfill, so a
        # separate dev identity would see an empty feed. Fresh DBs with no
        # admin yet get a dev@localhost admin instead.
        cur = await conn.execute(
            f"""
            SELECT {_USER_COLS}
            FROM app.users
            WHERE role = 'admin'
            ORDER BY created_at
            LIMIT 1
            """
        )
        row = await cur.fetchone()
        if row is not None:
            return cast(dict[str, Any], row)
        cur = await conn.execute(
            f"""
            INSERT INTO app.users
                (external_id, identity_provider, email, display_name, role,
                 last_login_at)
            VALUES ('dev-bypass', 'dev', %(email)s, 'Dev Bypass', 'admin', now())
            ON CONFLICT (email) DO UPDATE SET last_login_at = now()
            RETURNING {_USER_COLS}
            """,
            {"email": principal.email},
        )
        return cast(dict[str, Any], await cur.fetchone())

    if not principal.external_id:
        log.error(
            "Authenticated principal %s has no stable external id "
            "(provider=%s, principal keys=%s) — cannot resolve a user. "
            "SWA should always forward userId; check the forwarded claims.",
            principal.email,
            principal.identity_provider,
            sorted(principal.raw_claims.keys()),
        )
        raise HTTPException(status_code=403, detail="Access denied")

    cur = await conn.execute(
        f"""
        SELECT {_USER_COLS}
        FROM app.users
        WHERE identity_provider = %(provider)s AND external_id = %(external_id)s
        """,
        {
            "provider": principal.identity_provider,
            "external_id": principal.external_id,
        },
    )
    row = await cur.fetchone()
    if row is not None:
        return cast(dict[str, Any], row)

    # First login: link the stable id to the allowlist-synced row. The
    # external_id IS NULL guard means an already-linked row is never silently
    # rebound to a different subject.
    cur = await conn.execute(
        f"""
        UPDATE app.users
        SET external_id       = %(external_id)s,
            identity_provider = %(provider)s,
            last_login_at     = now()
        WHERE email = %(email)s AND external_id IS NULL
        RETURNING {_USER_COLS}
        """,
        {
            "external_id": principal.external_id,
            "provider": principal.identity_provider,
            "email": principal.email,
        },
    )
    row = await cur.fetchone()
    if row is not None:
        log.info(
            "JIT-linked user %s to external id via provider %s",
            principal.email,
            principal.identity_provider,
        )
        return cast(dict[str, Any], row)

    # Allowlist let them in but no row could be resolved or linked: either
    # startup sync never ran, or the email's row is already linked to a
    # different external id (e.g. the forwarded claim shape changed).
    cur = await conn.execute(
        "SELECT external_id, identity_provider FROM app.users WHERE email = %(email)s",
        {"email": principal.email},
    )
    existing = await cur.fetchone()
    if existing is None:
        log.error(
            "User %s passed the allowlist but has no app.users row — "
            "startup sync and auth.yml disagree",
            principal.email,
        )
    else:
        log.error(
            "User %s is already linked to a different external id "
            "(provider=%s); incoming provider=%s. If the identity claim shape "
            "changed, clear external_id on the row to relink.",
            principal.email,
            cast(dict[str, Any], existing)["identity_provider"],
            principal.identity_provider,
        )
    raise HTTPException(status_code=403, detail="Access denied")
