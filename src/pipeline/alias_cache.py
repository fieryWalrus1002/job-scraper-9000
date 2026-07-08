"""DB persistence for name→slug resolution results.

Wraps pipeline.resolver with read/write against raw.company_aliases and
raw.company_boards.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import psycopg

from pipeline.cse_search import cse_search as _cse_search
from pipeline.resolver import normalize, resolve, ResolveResult, RESOLVER_VERSION

log = logging.getLogger(__name__)

_UNRESOLVED_TTL = timedelta(days=90)  # 3 months — spec §4.2 step 4


class AliasCache:
    @staticmethod
    def lookup(conn: psycopg.Connection, normalized_input: str) -> ResolveResult | None:
        """Return cached result or None on miss.

        An 'unresolved' row past 3-month TTL is treated as a miss so the
        resolver re-probes it. A current 'unresolved' row returns a result
        with status='unresolved' (inert — caller treats it as "no board").
        """
        row = conn.execute(
            """
            SELECT board, slug, status, resolved_at
            FROM raw.company_aliases
            WHERE normalized_input = %s
            """,
            (normalized_input,),
        ).fetchone()

        if row is None:
            return None

        board, slug, status, resolved_at = row

        if status == "unresolved":
            age = datetime.now(tz=timezone.utc) - resolved_at
            if age > _UNRESOLVED_TTL:
                log.debug("cache miss (TTL expired): %r", normalized_input)
                return None  # treat as miss → re-probe

        return ResolveResult(board=board, slug=slug, status=status)

    @staticmethod
    def write(
        conn: psycopg.Connection,
        normalized_input: str,
        result: ResolveResult,
    ) -> None:
        """Upsert alias row; for resolved results, also upsert company_boards.

        Collision detection: if an existing 'resolved' row has a *different*
        slug than the new result, mark needs_review instead of overwriting.
        """
        existing = conn.execute(
            "SELECT slug, status FROM raw.company_aliases WHERE normalized_input = %s",
            (normalized_input,),
        ).fetchone()

        if (
            existing is not None
            and existing[1] == "resolved"
            and result.status == "resolved"
            and existing[0] != result.slug
        ):
            log.warning(
                "AliasCache collision: %r was %r, new result is %r — marking needs_review",
                normalized_input,
                existing[0],
                result.slug,
            )
            conn.execute(
                """
                UPDATE raw.company_aliases
                SET status = 'needs_review', resolver_version = %s, resolved_at = NOW()
                WHERE normalized_input = %s
                """,
                (RESOLVER_VERSION, normalized_input),
            )
            return

        conn.execute(
            """
            INSERT INTO raw.company_aliases
                (normalized_input, board, slug, status, resolver_version, resolved_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (normalized_input) DO UPDATE SET
                board = EXCLUDED.board,
                slug = EXCLUDED.slug,
                status = EXCLUDED.status,
                resolver_version = EXCLUDED.resolver_version,
                resolved_at = EXCLUDED.resolved_at
            """,
            (
                normalized_input,
                result.board,
                result.slug,
                result.status,
                RESOLVER_VERSION,
            ),
        )

        if result.status == "resolved" and result.board and result.slug:
            conn.execute(
                """
                INSERT INTO raw.company_boards (board, slug, last_verified_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (board, slug) DO UPDATE SET last_verified_at = NOW()
                """,
                (result.board, result.slug),
            )

    @staticmethod
    def resolve_and_cache(conn: psycopg.Connection, name: str) -> ResolveResult:
        """Normalize → lookup cache → on miss: resolve → write back → return.

        This is the primary entry point for the planner pre-pass (#455).
        The search-fallback path (#454) will extend the miss branch here.
        """
        norm = normalize(name)
        cached = AliasCache.lookup(conn, norm)
        if cached is not None:
            log.debug("cache hit for %r → %s", norm, cached.status)
            return cached

        result = resolve(name, search_fn=_cse_search)
        AliasCache.write(conn, norm, result)
        return result
