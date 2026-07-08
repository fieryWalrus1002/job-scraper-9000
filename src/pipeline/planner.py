"""Planner: DB users → per-(user, source) queue rows (Phase 13 spec §8 step 1).

Reads :mod:`app.users` joined with :mod:`app.candidate_profiles` and
:mod:`app.user_search_configs`. For every user with both a profile and a
search config:

1. Materializes ``runs/<slug>/<run_id>/`` containing the same three artifacts
   as ``scripts/pull_user_configs.py`` (``search.yml``,
   ``candidate_profile.yml``, ``policies.yml``) — the spec §12 open question
   #2 lean: keep the materialized debugging artifact under each run's dir.
2. Inspects the materialized ``search.yml`` and enqueues one ``pipe.scrape_jobs``
   row per top-level scraper section it touches (``linkedin``, ``jobspy``,
   ``companies``). The section name becomes the queue ``source``.

Idempotent: re-running the planner against the same ``run_id`` is a no-op —
the UNIQUE ``(run_id, user_id, source)`` constraint catches the inserts, and
the YAML files just get overwritten with the same content.

Users with only a profile or only a search config are *skipped with a
warning*; the spec §12 open question #3 lean is "skip, don't include
silently." Same for users whose search config produces no scraper sections.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from pipeline.alias_cache import AliasCache
from pipeline.queue import enqueue
from pipeline.worker import run_user_dir
from user_config import (
    CandidateProfileInput,
    SearchConfigInput,
    candidate_profile_to_pipeline_yaml,
    dump_yaml,
    search_config_to_pipeline_yaml,
)

log = logging.getLogger(__name__)

# Top-level keys in the materialized search.yml that correspond to a queue
# ``source``. ``global`` is per-run defaults (not a source); other keys are
# scraper sections.
_SCRAPER_SOURCE_KEYS: tuple[str, ...] = ("linkedin", "jobspy", "companies")

_SELECT_USERS = """
    SELECT
        u.id::text               AS user_id,
        u.email                  AS email,
        cp.payload               AS profile_payload,
        cp.profile_version       AS profile_version,
        sc.payload               AS search_payload,
        sc.policies              AS policies,
        sc.pipeline_enabled      AS pipeline_enabled
    FROM app.users u
    LEFT JOIN app.candidate_profiles  cp ON cp.user_id = u.id
    LEFT JOIN app.user_search_configs sc ON sc.user_id = u.id
    ORDER BY u.email
"""


def _slug(email: str) -> str:
    """Same slug rule scripts/pull_user_configs.py uses, so the on-disk dir
    name is stable across the two entry points."""
    return re.sub(r"[^a-z0-9._-]", "_", email.strip().lower()).replace(".", "_")


def _materialize_user(
    *,
    run_dir: Path,
    profile_payload: dict,
    profile_version: str,
    search_payload: dict,
    policies: dict | None,
) -> dict:
    """Write the three artifacts to ``run_dir`` and return the materialized
    search-yaml mapping (the planner's enqueue loop reads it back)."""
    run_dir.mkdir(parents=True, exist_ok=True)

    search = SearchConfigInput.model_validate(search_payload)
    pipeline_search = search_config_to_pipeline_yaml(search)
    (run_dir / "search.yml").write_text(dump_yaml(pipeline_search))
    (run_dir / "policies.yml").write_text(dump_yaml(policies or {}))

    profile = CandidateProfileInput.model_validate(profile_payload)
    (run_dir / "candidate_profile.yml").write_text(
        dump_yaml(
            candidate_profile_to_pipeline_yaml(profile, profile_version=profile_version)
        )
    )

    return pipeline_search


def _gather_companies(rows: list[dict]) -> list[str]:
    """Collect deduped union of all company names across eligible user rows.

    Returns normalized names (lowercase, stripped). Only includes users who
    have both profile and search config (same eligibility as the enqueue loop).
    """
    seen: set[str] = set()
    names: list[str] = []
    for row in rows:
        if row["profile_payload"] is None or row["search_payload"] is None:
            continue
        if row["pipeline_enabled"] is False:
            continue
        # Read target_companies directly from the raw search_payload
        # (the DB dict), not the materialized pipeline_search.
        orgs = (
            (row["search_payload"] or {})
            .get("organizations", {})
            .get("target_companies", [])
        )
        for name in orgs:
            norm = name.strip().lower()
            if norm and norm not in seen:
                seen.add(norm)
                names.append(norm)
    return names


def _sources_for(pipeline_search: dict) -> list[str]:
    """Which queue ``source`` names this user's search.yml touches."""
    return [k for k in _SCRAPER_SOURCE_KEYS if pipeline_search.get(k)]


def plan_run(
    conn: psycopg.Connection,
    *,
    run_id: str,
    runs_dir: Path,
) -> dict[str, Any]:
    """Materialize every eligible user's run-dir and enqueue per-source jobs.

    Returns a small summary dict: ``{"users_planned": N, "users_skipped": M,
    "rows_enqueued": K, "skipped_emails": [...]}``. The CLI prints this; the
    tests assert against it.
    """
    summary: dict[str, Any] = {
        "users_planned": 0,
        "users_skipped": 0,
        "rows_enqueued": 0,
        "skipped_emails": [],
        "companies_resolved": 0,
    }

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SELECT_USERS)
        rows = cur.fetchall()

    # --- Resolution pre-pass ---
    all_companies = _gather_companies(rows)
    if all_companies:
        log.info(
            "Resolving %d distinct company name(s) before enqueue...",
            len(all_companies),
        )
        for name in all_companies:
            result = AliasCache.resolve_and_cache(conn, name)
            log.info(
                "  %r → %s (board=%s, slug=%s)",
                name,
                result.status,
                result.board,
                result.slug,
            )
        summary["companies_resolved"] = len(all_companies)
        log.info(
            "Company resolution pre-pass complete: %d name(s) processed",
            summary["companies_resolved"],
        )
    # --- End resolution pre-pass ---

    for row in rows:
        email = row["email"]
        if row["profile_payload"] is None or row["search_payload"] is None:
            missing = [
                name
                for name, payload in (
                    ("profile", row["profile_payload"]),
                    ("search config", row["search_payload"]),
                )
                if payload is None
            ]
            log.warning("%s — missing %s; skipping", email, " and ".join(missing))
            summary["users_skipped"] += 1
            summary["skipped_emails"].append(email)
            continue

        # #245: deactivated users keep their config but are gated out of the
        # overnight run (cost saver). Skip in the loop — not the SQL WHERE — so
        # the deactivation surfaces in skipped_emails / the run summary rather
        # than vanishing silently. Gate on explicit False, not falsiness: a
        # missing search config leaves this column NULL, but that case is
        # already handled by the missing-config skip above.
        if row["pipeline_enabled"] is False:
            log.warning("%s — pipeline_enabled=false; skipping", email)
            summary["users_skipped"] += 1
            summary["skipped_emails"].append(email)
            continue

        run_dir = run_user_dir(runs_dir, run_id, email)
        pipeline_search = _materialize_user(
            run_dir=run_dir,
            profile_payload=row["profile_payload"],
            profile_version=row["profile_version"],
            search_payload=row["search_payload"],
            policies=row["policies"],
        )

        sources = _sources_for(pipeline_search)
        if not sources:
            log.warning(
                "%s — search config produced no scraper sections; skipping",
                email,
            )
            summary["users_skipped"] += 1
            summary["skipped_emails"].append(email)
            continue

        for source in sources:
            # query_payload captures the source's slice of the materialized
            # search.yml. The worker uses it to invoke the right scrapers
            # without re-reading the YAML — and the row carries enough state
            # to be debuggable after the fact.
            payload = {source: pipeline_search[source]}
            if "global" in pipeline_search:
                payload["global"] = pipeline_search["global"]
            enqueued_id = enqueue(
                conn,
                run_id=run_id,
                user_id=row["user_id"],
                source=source,
                query_payload=payload,
            )
            if enqueued_id is not None:
                summary["rows_enqueued"] += 1

        summary["users_planned"] += 1
        log.info("%s → %d source(s) enqueued: %s", email, len(sources), sources)

    log.info(
        "Planned %d user(s), skipped %d, enqueued %d new row(s) for run_id=%s",
        summary["users_planned"],
        summary["users_skipped"],
        summary["rows_enqueued"],
        run_id,
    )
    return summary
