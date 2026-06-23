"""create_application_events

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-23

Append-only event log for application activity (specs/application_activity_tracking.md
§3.1). Replaces the practice of hand-dating lines into the `notes` blob.

Key properties:
- Composite FK (user_id, dedup_hash) → app.user_applications ON DELETE CASCADE.
- `kind` CHECK constraint limits to 'status_change' | 'event'.
- GIN index on `tags` for ECS-style tag queries.
- Composite index (user_id, dedup_hash, occurred_at) for timeline reads.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.application_events (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID        NOT NULL,
            dedup_hash  TEXT        NOT NULL,
            kind        TEXT        NOT NULL CHECK (kind IN ('status_change', 'event')),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            body        TEXT,
            tags        TEXT[]      NOT NULL DEFAULT '{}',
            metadata    JSONB       NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (user_id, dedup_hash)
                REFERENCES app.user_applications (user_id, dedup_hash) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_application_events_app_time
            ON app.application_events (user_id, dedup_hash, occurred_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_application_events_tags
            ON app.application_events USING GIN (tags)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.application_events")
