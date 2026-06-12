"""skills_fit + ingest phase (Phase 13 spec §8 steps 5–6, slice 6).

The closing fan-out of the pipeline. After classification has labelled the
consolidated union (profile-free), this phase splits back out per user:

1. :func:`score_and_ingest_run` — for each user that requested at least one
   posting, gate the union by *that user's*
   ``policies.remote.acceptable_classifications`` (the per-user remote
   policy, applied post-classification per spec §3), run skills_fit over the
   survivors as **one batch per user** (prompt-cache warmth is per
   ``(user, profile_version)`` — a cross-user batch would carry the wrong
   candidate profile in its system prompt), then ingest the scored JSONL
   into that user's ``raw.job_scores`` rows.

Each user scores against their own materialized
``runs/<slug>/<run_id>/candidate_profile.yml`` (written by the planner), so
the score embeds the right profile and records the right ``profile_version``.

``score_fn`` / ``ingest_fn`` are injectable to keep tests off the LLM and,
for ``score_fn``, off the network — mirroring the worker's ``scrape_fn`` and
consolidation's ``classify_fn``. Production wires in :func:`default_score_fn`
and :func:`default_ingest_fn`.

Per-user failure isolation (capturing an exception from one user without
sinking the run) is slice 7 (#201); this slice fails loud.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from pipeline.consolidation import (
    PASS_NAME,
    TRASH_NAME,
    consolidated_dir,
)
from pipeline.planner import _slug
from user_config import UserPolicies

log = logging.getLogger(__name__)

SKILLS_FIT_DIRNAME = "skills_fit"
INPUT_NAME = "input.jsonl"
SCORED_NAME = "scored.jsonl"

ScoreFn = Callable[..., dict[str, Any]]
"""``(input_path=, output_path=, profile_file=, run_date=, parent_run_id=) -> summary``."""

IngestFn = Callable[..., dict[str, Any]]
"""``(scored_path=, user_email=, conn=) -> summary``."""

# Per-user query: invert consolidated_postings.requested_by into one row per
# user with the dedup_hashes they want, plus their stored policies. A user
# with no search config (only reachable if requested_by were stale) yields
# NULL policies → the permissive default below.
_SELECT_USER_POSTINGS = """
    SELECT
        u.id::text                  AS user_id,
        u.email                     AS email,
        sc.policies                 AS policies,
        array_agg(cp.dedup_hash)    AS dedup_hashes
    FROM pipe.consolidated_postings cp
    JOIN app.users u ON u.id = ANY(cp.requested_by)
    LEFT JOIN app.user_search_configs sc ON sc.user_id = u.id
    WHERE cp.run_id = %s
    GROUP BY u.id, u.email, sc.policies
    ORDER BY u.email
"""


def skills_fit_dir(runs_dir: Path, email: str, run_id: str) -> Path:
    return runs_dir / _slug(email) / run_id / SKILLS_FIT_DIRNAME


def _load_classified(runs_dir: Path, run_id: str) -> dict[str, dict[str, Any]]:
    """``{dedup_hash: classified_record}`` from the pass + trash JSONLs.

    Both files are read: the global pass/trash split the classifier applied is
    advisory (spec §8 step 4 note); each user's own
    ``acceptable_classifications`` decides over the *union* of the two. A
    posting present in neither file simply has no score basis and is dropped
    from every user's input with the count surfaced in the summary.
    """
    out_dir = consolidated_dir(runs_dir, run_id)
    classified: dict[str, dict[str, Any]] = {}
    for name in (PASS_NAME, TRASH_NAME):
        path = out_dir / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                key = rec.get("dedup_hash")
                if key is None:
                    continue
                classified[key] = rec
    return classified


def _classification_of(record: dict[str, Any]) -> str | None:
    analysis = record.get("_remote_analysis") or {}
    return analysis.get("remote_classification")


def default_score_fn(
    *,
    input_path: Path,
    output_path: Path,
    profile_file: Path,
    run_date: str | None,
    parent_run_id: str,
) -> dict[str, Any]:
    """Production scoring: skills_fit over one user's policy-gated postings.

    Reuses the runner wholesale — shared RunTracker telemetry, the
    profile_version-keyed AnalysisCache, config from
    ``config/agent/skills_fit.yml`` — but points ``profile_file`` at this
    user's materialized profile so the scoring contract is theirs.
    """
    from agents.skills_fit.runner import run_skills_fit

    return run_skills_fit(
        run_date=run_date,
        remote_input=input_path,
        output=output_path,
        profile_file=profile_file,
        parent_run_id=parent_run_id,
    )


def default_ingest_fn(
    *,
    scored_path: Path,
    user_email: str,
    conn: psycopg.Connection,
) -> dict[str, Any]:
    """Production ingest: route one user's scored JSONL to their job_scores.

    ``default_user_email`` is the owning user — the consolidated postings are
    profile-free and carry no ``user_email`` field, so the rows route by this
    argument alone.
    """
    from ingest.core import ingest, read_jsonl

    records = read_jsonl(scored_path)
    if not records:
        return {
            "total": 0,
            "postings_inserted": 0,
            "scores_inserted": 0,
            "scores_updated": 0,
        }
    return ingest(records, conn=conn, default_user_email=user_email)


def score_and_ingest_run(
    conn: psycopg.Connection,
    *,
    run_id: str,
    run_date: str | None,
    runs_dir: Path,
    score_fn: ScoreFn = default_score_fn,
    ingest_fn: IngestFn = default_ingest_fn,
) -> dict[str, Any]:
    """Per-user skills_fit + ingest over the classified union.

    Returns a summary: ``{"users_scored": N, "users_skipped_no_postings": M,
    "users_failed": F, "postings_scored": K, "scores_inserted": …,
    "scores_updated": …, "postings_unclassified": …, "per_user": [...]}``.
    The end-of-run summary (:mod:`pipeline.summary`) builds on it.

    Per-user failure isolation (spec §7): a user whose skills_fit or ingest
    step raises is logged with its full traceback, recorded ``failed`` in the
    summary, and skipped — the loop carries on for everyone else. ``ingest``
    runs each user inside its own DB transaction, so a mid-batch raise leaves
    no partial scores for that user.
    """
    classified = _load_classified(runs_dir, run_id)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SELECT_USER_POSTINGS, (run_id,))
        user_rows = cur.fetchall()

    summary: dict[str, Any] = {
        "users_scored": 0,
        "users_skipped_no_postings": 0,
        "users_failed": 0,
        "postings_scored": 0,
        "scores_inserted": 0,
        "scores_updated": 0,
        "postings_unclassified": 0,
        "per_user": [],
    }

    for row in user_rows:
        email = row["email"]
        try:
            acceptable = set(
                UserPolicies.model_validate(
                    row["policies"] or {}
                ).remote.acceptable_classifications
            )

            survivors: list[dict[str, Any]] = []
            unclassified = 0
            for dedup_hash in row["dedup_hashes"]:
                rec = classified.get(dedup_hash)
                if rec is None:
                    unclassified += 1
                    continue
                if _classification_of(rec) in acceptable:
                    survivors.append(rec)
            summary["postings_unclassified"] += unclassified

            if not survivors:
                log.info(
                    "%s — no postings survived remote policy "
                    "(%d requested, %d unclassified); skipping skills_fit",
                    email,
                    len(row["dedup_hashes"]),
                    unclassified,
                )
                summary["users_skipped_no_postings"] += 1
                summary["per_user"].append(
                    {"email": email, "postings_scored": 0, "skipped": True}
                )
                continue

            out_dir = skills_fit_dir(runs_dir, email, run_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            input_path = out_dir / INPUT_NAME
            with input_path.open("w", encoding="utf-8") as f:
                for rec in survivors:
                    f.write(json.dumps(rec) + "\n")
            scored_path = out_dir / SCORED_NAME

            profile_file = runs_dir / _slug(email) / run_id / "candidate_profile.yml"
            if not profile_file.exists():
                raise FileNotFoundError(
                    f"Materialized profile for {email} (run_id={run_id}) is missing: "
                    f"{profile_file} — the planner should have written it"
                )

            score_fn(
                input_path=input_path,
                output_path=scored_path,
                profile_file=profile_file,
                run_date=run_date,
                parent_run_id=run_id,
            )
            ingest_summary = ingest_fn(
                scored_path=scored_path, user_email=email, conn=conn
            )

            scores_inserted = ingest_summary.get("scores_inserted", 0)
            scores_updated = ingest_summary.get("scores_updated", 0)
            summary["users_scored"] += 1
            summary["postings_scored"] += len(survivors)
            summary["scores_inserted"] += scores_inserted
            summary["scores_updated"] += scores_updated
            summary["per_user"].append(
                {
                    "email": email,
                    "postings_scored": len(survivors),
                    "scores_inserted": scores_inserted,
                    "scores_updated": scores_updated,
                    "skipped": False,
                }
            )
            log.info(
                "%s — scored %d posting(s) → %d new, %d re-scored",
                email,
                len(survivors),
                scores_inserted,
                scores_updated,
            )
        except Exception:
            # Per-user isolation (spec §7): one user's failure must not sink
            # everyone else's scores. Full traceback to the log now; the
            # end-of-run summary surfaces the one-liner for the morning admin.
            tb = traceback.format_exc()
            log.error("%s — skills_fit/ingest failed; isolating:\n%s", email, tb)
            summary["users_failed"] += 1
            summary["per_user"].append(
                {"email": email, "postings_scored": 0, "failed": True, "error": tb}
            )

    log.info(
        "skills_fit + ingest phase done for run_id=%s: %d scored, %d skipped "
        "(no postings), %d failed, %d posting(s) scored",
        run_id,
        summary["users_scored"],
        summary["users_skipped_no_postings"],
        summary["users_failed"],
        summary["postings_scored"],
    )
    return summary
