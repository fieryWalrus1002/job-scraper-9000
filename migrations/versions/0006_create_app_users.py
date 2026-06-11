"""create_app_users

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-10

Creates app.users — the identity table for the multi-user phase
(specs/multi_user_design.md §3). Internal UUID PK; the stable external
subject (Entra oid) is linked at first login, so external_id starts NULL.
Email is the allowlist/JIT-link key, never the join key.

Seeds the bootstrap admin so the next migration's data backfills have an
owner. The admin email resolves, in order:

1. BOOTSTRAP_ADMIN_EMAIL env var
2. config/auth.yml mounted in this container (new `users:` format, falling
   back to the first `allowed_emails:` entry if the secret volume still has
   the legacy shape)
3. If AUTH_BYPASS=1 (dev/test): skip the seed — the dev-bypass path and
   startup sync populate the table instead
4. Otherwise: fail fast. Never seed a placeholder.

The YAML parsing is intentionally self-contained — migrations must not
import live app code, whose semantics drift after the migration is frozen.
"""

import os
import sys
from pathlib import Path
from typing import Sequence, Union

import yaml
from alembic import op
from sqlalchemy import text

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUTH_CONFIG = Path("config/auth.yml")


def _resolve_bootstrap_admin_email() -> str | None:
    env_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL")
    if env_email and env_email.strip():
        return env_email.strip().lower()

    if _AUTH_CONFIG.exists():
        data = yaml.safe_load(_AUTH_CONFIG.read_text())
        if isinstance(data, dict):
            for entry in data.get("users") or []:
                if (
                    isinstance(entry, dict)
                    and entry.get("role") == "admin"
                    and isinstance(entry.get("email"), str)
                ):
                    return entry["email"].strip().lower()
            legacy = data.get("allowed_emails") or []
            if legacy and isinstance(legacy[0], str) and legacy[0].strip():
                sys.stderr.write(
                    "0006: auth.yml still uses legacy 'allowed_emails'; seeding "
                    "its first entry as admin. Migrate the file to the 'users' "
                    "format — the API will refuse to start on the legacy shape.\n"
                )
                return legacy[0].strip().lower()

    if os.environ.get("AUTH_BYPASS") == "1":
        return None

    raise RuntimeError(
        "0006: cannot resolve a bootstrap admin email. Set BOOTSTRAP_ADMIN_EMAIL "
        f"or provide an admin entry in {_AUTH_CONFIG}. Refusing to seed a "
        "placeholder."
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.users (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            external_id       TEXT,
            identity_provider TEXT,
            email             TEXT        NOT NULL UNIQUE,
            display_name      TEXT,
            role              TEXT        NOT NULL DEFAULT 'member'
                                          CHECK (role IN ('admin', 'member')),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_login_at     TIMESTAMPTZ,
            UNIQUE (identity_provider, external_id)
        )
    """)

    admin_email = _resolve_bootstrap_admin_email()
    if admin_email is None:
        sys.stderr.write(
            "0006: AUTH_BYPASS=1 and no admin email available — skipping "
            "bootstrap admin seed (dev/test only)\n"
        )
        return
    op.get_bind().execute(
        text(
            "INSERT INTO app.users (email, role) VALUES (:email, 'admin') "
            "ON CONFLICT (email) DO UPDATE SET role = 'admin'"
        ),
        {"email": admin_email},
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.users")
