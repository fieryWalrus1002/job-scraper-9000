"""company_slug_tables

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-08

raw.company_aliases  — name→slug resolution cache (spec §4.1)
raw.company_boards   — verified live boards, (board, slug) canonical identity
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.company_boards (
            board          text NOT NULL,
            slug           text NOT NULL,
            last_verified_at timestamptz NOT NULL,
            PRIMARY KEY (board, slug)
        )
    """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.company_aliases (
            normalized_input   text PRIMARY KEY,
            board              text,
            slug               text,
            status             text NOT NULL,
            resolver_version   text NOT NULL,
            resolved_at        timestamptz NOT NULL,
            CONSTRAINT company_aliases_status_check
                CHECK (
                    status IN ('resolved', 'unresolved', 'needs_review')
                ),
            CONSTRAINT company_aliases_resolved_implies_board_slug
                CHECK (
                    status != 'resolved' OR (board IS NOT NULL AND slug IS NOT NULL)
                )
        )
    """
    )

    # Seed resolved entries from the baked flat file.
    # Slugs that were keys with non-empty board lists are verified ATS tokens.
    _SEED_RESOLVED = [
        ("anthropic", "greenhouse", "anthropic"),
        ("cohere", "ashby", "cohere"),
        ("deepmind", "greenhouse", "deepmind"),
        ("figma", "greenhouse", "figma"),
        ("harvey", "ashby", "harvey"),
        ("notion", "ashby", "notion"),
        ("perplexity", "ashby", "perplexity"),
        ("replit", "ashby", "replit"),
        ("stripe", "greenhouse", "stripe"),
    ]
    # mistral has two boards — seed the first as resolved; second board also gets a
    # company_boards row. Both canonical identities land in raw.company_boards.
    _SEED_RESOLVED_MULTI = [
        ("mistral", [("ashby", "mistral"), ("lever", "mistral")]),
    ]

    # Unresolved (empty-board) keys from the flat file.
    _SEED_UNRESOLVED = ["ai21", "meta", "nvidia", "scale-ai", "sel"]

    now = "NOW()"
    version = "'v1'"

    for normalized, board, slug in _SEED_RESOLVED:
        op.execute(
            f"""
            INSERT INTO raw.company_boards (board, slug, last_verified_at)
            VALUES ('{board}', '{slug}', {now})
            ON CONFLICT DO NOTHING
        """
        )
        op.execute(
            f"""
            INSERT INTO raw.company_aliases
                (normalized_input, board, slug, status, resolver_version, resolved_at)
            VALUES ('{normalized}', '{board}', '{slug}', 'resolved', {version}, {now})
            ON CONFLICT DO NOTHING
        """
        )

    for normalized, pairs in _SEED_RESOLVED_MULTI:
        primary_board, primary_slug = pairs[0]
        for board, slug in pairs:
            op.execute(
                f"""
                INSERT INTO raw.company_boards (board, slug, last_verified_at)
                VALUES ('{board}', '{slug}', {now})
                ON CONFLICT DO NOTHING
            """
            )
        # Alias points to the first board (ashby for mistral); multiple boards
        # for same company is an edge case the resolver handles as needs_review
        # going forward, but for seed data we know it's a real dual-board company.
        op.execute(
            f"""
            INSERT INTO raw.company_aliases
                (normalized_input, board, slug, status, resolver_version, resolved_at)
            VALUES ('{normalized}', '{primary_board}', '{primary_slug}', 'resolved', {version}, {now})
            ON CONFLICT DO NOTHING
        """
        )

    for normalized in _SEED_UNRESOLVED:
        op.execute(
            f"""
            INSERT INTO raw.company_aliases
                (normalized_input, board, slug, status, resolver_version, resolved_at)
            VALUES ('{normalized}', NULL, NULL, 'unresolved', {version}, {now})
            ON CONFLICT DO NOTHING
        """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw.company_aliases")
    op.execute("DROP TABLE IF EXISTS raw.company_boards")
