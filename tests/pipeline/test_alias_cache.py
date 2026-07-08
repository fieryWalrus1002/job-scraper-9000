"""Live-DB tests for AliasCache (raw.company_aliases + raw.company_boards)."""

from __future__ import annotations

from unittest.mock import patch

import psycopg

from pipeline.alias_cache import AliasCache
from pipeline.resolver import ResolveResult


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


def test_lookup_miss(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    result = AliasCache.lookup(conn, "unknown-company")
    assert result is None


# ---------------------------------------------------------------------------
# write + lookup (resolved)
# ---------------------------------------------------------------------------


def test_write_and_lookup_resolved(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    result = ResolveResult(board="linkedin", slug="acme", status="resolved")
    AliasCache.write(conn, "acme", result)

    cached = AliasCache.lookup(conn, "acme")
    assert cached is not None
    assert cached.board == "linkedin"
    assert cached.slug == "acme"
    assert cached.status == "resolved"


# ---------------------------------------------------------------------------
# write + lookup (unresolved, within TTL)
# ---------------------------------------------------------------------------


def test_write_and_lookup_unresolved(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    result = ResolveResult(board=None, slug=None, status="unresolved")
    AliasCache.write(conn, "ghost-corp", result)

    cached = AliasCache.lookup(conn, "ghost-corp")
    assert cached is not None
    assert cached.status == "unresolved"
    assert cached.board is None
    assert cached.slug is None


# ---------------------------------------------------------------------------
# unresolved TTL expired → treated as miss
# ---------------------------------------------------------------------------


def test_unresolved_ttl_expired(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    result = ResolveResult(board=None, slug=None, status="unresolved")
    AliasCache.write(conn, "old-ghost", result)

    # Backdate resolved_at by 91 days (> 90-day TTL)
    conn.execute(
        "UPDATE raw.company_aliases SET resolved_at = NOW() - INTERVAL '91 days' WHERE normalized_input = %s",
        ("old-ghost",),
    )

    cached = AliasCache.lookup(conn, "old-ghost")
    assert cached is None  # TTL expired → miss


# ---------------------------------------------------------------------------
# company_boards upsert
# ---------------------------------------------------------------------------


def test_company_boards_upsert(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    result = ResolveResult(board="linkedin", slug="acme", status="resolved")
    AliasCache.write(conn, "acme", result)

    # Row exists in company_boards
    row = conn.execute(
        "SELECT board, slug, last_verified_at FROM raw.company_boards WHERE board = %s AND slug = %s",
        ("linkedin", "acme"),
    ).fetchone()
    assert row is not None
    assert row[0] == "linkedin"
    assert row[1] == "acme"
    first_verified = row[2]

    # Backdate the row, then write again — ON CONFLICT DO UPDATE should refresh it
    conn.execute(
        "UPDATE raw.company_boards SET last_verified_at = NOW() - INTERVAL '1 day' WHERE board = %s AND slug = %s",
        ("linkedin", "acme"),
    )
    backdated = conn.execute(
        "SELECT last_verified_at FROM raw.company_boards WHERE board = %s AND slug = %s",
        ("linkedin", "acme"),
    ).fetchone()
    assert backdated[0] < first_verified

    AliasCache.write(conn, "acme", result)

    # Verify exactly one row (upsert, not duplicate) and timestamp refreshed
    count = conn.execute(
        "SELECT COUNT(*) FROM raw.company_boards WHERE board = %s AND slug = %s",
        ("linkedin", "acme"),
    ).fetchone()
    assert count[0] == 1

    row2 = conn.execute(
        "SELECT last_verified_at FROM raw.company_boards WHERE board = %s AND slug = %s",
        ("linkedin", "acme"),
    ).fetchone()
    assert row2[0] > backdated[0]  # newer than the backdated value


# ---------------------------------------------------------------------------
# collision detection → needs_review
# ---------------------------------------------------------------------------


def test_collision_marks_needs_review(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)

    # First write: resolved to slug "acme1"
    AliasCache.write(
        conn, "acme", ResolveResult(board="linkedin", slug="acme1", status="resolved")
    )

    # Second write: resolved to different slug "acme2"
    AliasCache.write(
        conn, "acme", ResolveResult(board="indeed", slug="acme2", status="resolved")
    )

    # Should be marked needs_review, slug preserved
    row = conn.execute(
        "SELECT slug, status FROM raw.company_aliases WHERE normalized_input = %s",
        ("acme",),
    ).fetchone()
    assert row is not None
    assert row[0] == "acme1"  # original slug preserved
    assert row[1] == "needs_review"


# ---------------------------------------------------------------------------
# resolve_and_cache — miss path calls resolver
# ---------------------------------------------------------------------------


def test_resolve_and_cache_calls_resolver_on_miss(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    expected = ResolveResult(board="linkedin", slug="testco", status="resolved")

    with patch("pipeline.alias_cache.resolve", return_value=expected):
        result = AliasCache.resolve_and_cache(conn, "TestCo")

    assert result == expected
    # Alias row was written
    cached = AliasCache.lookup(conn, "testco")
    assert cached is not None
    assert cached.status == "resolved"


# ---------------------------------------------------------------------------
# resolve_and_cache — hit path skips resolver
# ---------------------------------------------------------------------------


def test_resolve_and_cache_uses_cache_on_hit(migrated_pg: str) -> None:
    conn = psycopg.connect(migrated_pg)
    # Pre-seed a resolved row
    seed = ResolveResult(board="linkedin", slug="cachedco", status="resolved")
    AliasCache.write(conn, "cachedco", seed)

    with patch("pipeline.alias_cache.resolve") as mock_resolve:
        result = AliasCache.resolve_and_cache(conn, "CachedCo")

    mock_resolve.assert_not_called()
    assert result.board == "linkedin"
    assert result.slug == "cachedco"
    assert result.status == "resolved"


# ---------------------------------------------------------------------------
# resolve_and_cache — CSE golden pairs
# ---------------------------------------------------------------------------


def test_resolve_and_cache_golden_cse_pairs(migrated_pg: str) -> None:
    """Golden pairs that require CSE search fallback resolve correctly."""
    conn = psycopg.connect(migrated_pg)

    # Mock CSE to return the correct slug for each golden pair
    cse_responses = {
        "commonwealth fusion systems": ResolveResult(
            board="lever", slug="cfsenergy", status="resolved"
        ),
        "avalanche energy": ResolveResult(
            board="ashby", slug="avalanchefusion", status="resolved"
        ),
    }

    def fake_cse_search(name: str):
        return cse_responses.get(name.lower())

    with patch("pipeline.alias_cache._cse_search", side_effect=fake_cse_search):
        with patch("pipeline.resolver.probe_company", return_value=[]):
            # All heuristic candidates miss (probe returns []), so search_fn fires
            for name, expected in cse_responses.items():
                result = AliasCache.resolve_and_cache(conn, name)
                assert result.status == "resolved"
                assert result.board == expected.board
                assert result.slug == expected.slug

                # Alias row was written
                cached = AliasCache.lookup(conn, name.lower())
                assert cached is not None
                assert cached.status == "resolved"
                assert cached.slug == expected.slug
