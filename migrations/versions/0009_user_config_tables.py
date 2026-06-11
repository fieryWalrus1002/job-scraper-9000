"""user_config_tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-11

Per-user config storage for Phase 12 (specs/configs_in_db_design.md §2):
two tables, one row per user, JSONB payloads in the human-facing format.

- app.candidate_profiles — the scoring contract. ``profile_version`` is a
  content hash computed on save (the API/scripts compute it; the column just
  stores the opaque text).
- app.user_search_configs — search targeting plus per-user ``policies`` (the
  cheap prefilter / remote-classification gates, spec §6). ``policies``
  defaults to ``'{}'`` = permissive: an empty object means everything passes.

Both PK ``user_id`` enforces exactly-one-per-user (decision: a second persona
means a second account). FK ON DELETE CASCADE so deleting a user drops their
config. Additive, no backfill — the push script (scripts/push_user_config.py)
seeds rows.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.candidate_profiles (
            user_id         UUID        PRIMARY KEY
                                        REFERENCES app.users(id) ON DELETE CASCADE,
            payload         JSONB       NOT NULL,
            profile_version TEXT        NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.user_search_configs (
            user_id         UUID        PRIMARY KEY
                                        REFERENCES app.users(id) ON DELETE CASCADE,
            payload         JSONB       NOT NULL,
            policies        JSONB       NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.user_search_configs")
    op.execute("DROP TABLE IF EXISTS app.candidate_profiles")
