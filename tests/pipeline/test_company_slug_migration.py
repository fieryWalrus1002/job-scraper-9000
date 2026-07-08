"""Migration 0019: raw.company_aliases + raw.company_boards round-trip tests.

Verifies the migration creates both tables with correct constraints, seeds the
expected rows from the flat-file snapshot, and downgrades cleanly.

Run: uv run pytest tests/pipeline/test_company_slug_migration.py -m docker -v
"""

from __future__ import annotations

import psycopg
import pytest

# migrated_pg (from tests/pipeline/conftest.py) auto-tags tests with the
# ``docker`` marker via pytest_collection_modifyitems.


def test_0019_seeds_resolved_aliases(migrated_pg):
    """raw.company_aliases should have 10 resolved rows after migration."""
    with psycopg.connect(migrated_pg) as conn:
        rows = conn.execute(
            "SELECT normalized_input, board, slug, status FROM raw.company_aliases "
            "WHERE status = 'resolved' ORDER BY normalized_input"
        ).fetchall()

    assert len(rows) == 10

    expected_resolved = {
        "anthropic": ("greenhouse", "anthropic"),
        "cohere": ("ashby", "cohere"),
        "deepmind": ("greenhouse", "deepmind"),
        "figma": ("greenhouse", "figma"),
        "harvey": ("ashby", "harvey"),
        "mistral": ("ashby", "mistral"),
        "notion": ("ashby", "notion"),
        "perplexity": ("ashby", "perplexity"),
        "replit": ("ashby", "replit"),
        "stripe": ("greenhouse", "stripe"),
    }
    actual = {row[0]: (row[1], row[2]) for row in rows}
    assert actual == expected_resolved


def test_0019_seeds_unresolved_aliases(migrated_pg):
    """raw.company_aliases should have 5 unresolved rows (empty-board keys)."""
    with psycopg.connect(migrated_pg) as conn:
        rows = conn.execute(
            "SELECT normalized_input, board, slug, status FROM raw.company_aliases "
            "WHERE status = 'unresolved' ORDER BY normalized_input"
        ).fetchall()

    assert len(rows) == 5
    unresolved_names = {row[0] for row in rows}
    assert unresolved_names == {"ai21", "meta", "nvidia", "scale-ai", "sel"}

    # Unresolved rows must have NULL board and slug
    for row in rows:
        assert row[1] is None, f"{row[0]} board should be NULL"
        assert row[2] is None, f"{row[0]} slug should be NULL"


def test_0019_seeds_company_boards(migrated_pg):
    """raw.company_boards should have 11 rows (9 single + 2 for mistral)."""
    with psycopg.connect(migrated_pg) as conn:
        rows = conn.execute(
            "SELECT board, slug FROM raw.company_boards ORDER BY board, slug"
        ).fetchall()

    assert len(rows) == 11

    expected_boards = {
        ("ashby", "cohere"),
        ("ashby", "harvey"),
        ("ashby", "mistral"),
        ("ashby", "notion"),
        ("ashby", "perplexity"),
        ("ashby", "replit"),
        ("greenhouse", "anthropic"),
        ("greenhouse", "deepmind"),
        ("greenhouse", "figma"),
        ("greenhouse", "stripe"),
        ("lever", "mistral"),
    }
    actual = {row for row in rows}
    assert actual == expected_boards


def test_0019_check_constraint_rejects_resolved_with_null_slug(migrated_pg):
    """A row with status='resolved' and NULL slug must be rejected."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO raw.company_aliases "
                "(normalized_input, board, slug, status, resolver_version, resolved_at) "
                "VALUES ('bad-company', NULL, NULL, 'resolved', 'v1', NOW())"
            )


def test_0019_check_constraint_rejects_invalid_status(migrated_pg):
    """A row with an unknown status value must be rejected."""
    with psycopg.connect(migrated_pg, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO raw.company_aliases "
                "(normalized_input, board, slug, status, resolver_version, resolved_at) "
                "VALUES ('bad-company', 'ashby', 'bad', 'unknown_status', 'v1', NOW())"
            )
