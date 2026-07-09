"""skills_fit scoring phase (Phase 13 spec §8 steps 5–6; produce-only per
Phase 15 §5/§6 D1).

The closing fan-out of the pipeline. After classification has labelled the
consolidated union (profile-free), this phase splits back out per user:

1. :func:`score_run` — for each user that requested at least one posting,
   gate the union by *that user's*
   ``policies.remote.acceptable_classifications`` (the per-user remote
   policy, applied post-classification per spec §3) and their
   ``policies.remote.max_travel_days`` travel ceiling (numeric gate on
   ``_remote_analysis.estimated_travel_days_per_year``; None = no gate),
   then run skills_fit
   over the survivors as **one batch per user** (prompt-cache warmth is per
   ``(user, profile_version)`` — a cross-user batch would carry the wrong
   candidate profile in its system prompt), writing the scored JSONL to
   ``data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl``.

This phase is **produce-only** (Phase 15 D1): it never writes
``raw.job_scores``. Ingest is a separate downstream concern — the blob → ACA
Job path in the cloud, a standalone local-dev recipe locally — so the
pipeline and ingest are fully decoupled. Each scored record is stamped with
its owning ``user_email`` (Phase 15 G2) so the file self-routes on ingest;
:func:`iter_run_user_outputs` is the shared walk both downstream paths use to
find a run's per-user scored files.

Each user scores against their own materialized
``data/pipeline_runs/<run_id>/<slug>/candidate_profile.yml`` (written by the
planner), so the score embeds the right profile and records the right
``profile_version``.

``score_fn`` is injectable to keep tests off the LLM and off the network —
mirroring the worker's ``scrape_fn`` and consolidation's ``classify_fn``.
Production wires in :func:`default_score_fn`.

Per-user failure isolation (capturing an exception from one user without
sinking the run) is slice 7 (#201); this slice fails loud.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable, NamedTuple

import psycopg
from psycopg.rows import dict_row

from pipeline.consolidation import (
    PASS_NAME,
    TRASH_NAME,
    consolidated_dir,
)
from pipeline.worker import run_user_dir
from user_config import UserPolicies
from user_config.models import Location

log = logging.getLogger(__name__)

SKILLS_FIT_DIRNAME = "skills_fit"
INPUT_NAME = "input.jsonl"
SCORED_NAME = "scored.jsonl"

ScoreFn = Callable[..., dict[str, Any]]
"""``(input_path=, output_path=, profile_file=, run_date=, parent_run_id=) -> summary``."""

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _location_matches(job_location: str | None, acceptable: list[Location]) -> bool:
    """True if the scraped posting location matches any acceptable location
    (specs/relocation_policy.md §8.4). City = casefolded substring; region =
    exact casefolded token (so 'WA' matches 'Seattle, WA' but not 'seattle');
    the token guard keeps 'Portland, OR' from matching 'Portland, ME'. Empty/None
    job_location never matches. Country is not required to appear."""
    if not job_location or not job_location.strip():
        return False
    hay = job_location.casefold()
    tokens = set(_TOKEN_RE.findall(hay))
    for loc in acceptable:
        city = loc.city.casefold().strip()
        region = loc.region.casefold().strip()
        if not city or city not in hay:
            continue
        # Spec §8.4: require BOTH city and region. Location.region is a required
        # field, so an empty region is malformed data — never match on city alone
        # (that would let 'Portland' match any Portland).
        if region and region in tokens:
            return True
    return False


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
    return run_user_dir(runs_dir, run_id, email) / SKILLS_FIT_DIRNAME


class RunUserOutput(NamedTuple):
    """One user's scored output within a run (Phase 15 §5)."""

    user_email: str
    slug: str
    scored_path: Path


def _stamp_user_email(scored_path: Path, user_email: str) -> None:
    """Stamp ``user_email`` into every scored record so the file self-routes
    on ingest (Phase 15 G2). ``ingest.core.resolve_user_ids`` reads a
    per-record ``user_email``; the consolidated postings are profile-free and
    carry none, so the producer — the only place that knows which user a
    scored file belongs to — stamps it here at write time.

    Idempotent and authoritative: the owning user overwrites any existing
    value. Fails loud (the file is small, fully rewritten) per the repo's
    fail-fast rule.
    """
    records = [
        json.loads(line)
        for line in scored_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with scored_path.open("w", encoding="utf-8") as f:
        for rec in records:
            rec["user_email"] = user_email
            f.write(json.dumps(rec) + "\n")


def iter_run_user_outputs(runs_dir: Path, run_id: str) -> Iterator[RunUserOutput]:
    """Yield one :class:`RunUserOutput` per user with a scored file in a run.

    The single definition of where a run's per-user outputs live (Phase 15
    §5), shared by the blob uploader (slice 3) and the local-dev ingest recipe
    (slice 4) so they can't drift. Walks the run-first tree
    ``data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl`` — the
    ``_consolidated`` stage dir has no ``skills_fit/`` child and is naturally
    skipped. ``user_email`` is read back from the file's first stamped record
    (:func:`_stamp_user_email` guarantees every record carries it), so the
    walk needs no DB. Sorted by path for a deterministic order.
    """
    run_dir = runs_dir / run_id
    pattern = f"*/{SKILLS_FIT_DIRNAME}/{SCORED_NAME}"
    for scored_path in sorted(run_dir.glob(pattern)):
        slug = scored_path.parent.parent.name
        yield RunUserOutput(
            user_email=_first_record_user_email(scored_path),
            slug=slug,
            scored_path=scored_path,
        )


def _first_record_user_email(scored_path: Path) -> str:
    """``user_email`` from the first record of a scored file. Fails loud if the
    file is empty or the field is missing — a stamped file must have it, and a
    silent skip would orphan a user's scores downstream."""
    with scored_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            email = json.loads(line).get("user_email")
            if not email:
                raise ValueError(
                    f"{scored_path} first record has no user_email — "
                    "score_run should have stamped it"
                )
            return email
    raise ValueError(f"{scored_path} is empty — cannot determine user_email")


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


def _travel_days_of(record: dict[str, Any]) -> int | None:
    """Numeric travel estimate from the stored remote analysis.

    ``estimated_travel_days_per_year`` is ``int | None`` on RemoteAnalysis;
    a stored value of any other type is corrupt data and must not be
    silently coerced or skipped — fail loud so the per-user isolation handler
    records it (CLAUDE.md: fail fast, log well). ``bool`` is rejected too:
    ``isinstance(True, int)`` is True, so a stored ``true`` would otherwise
    sneak through as 1 day.
    """
    analysis = record.get("_remote_analysis") or {}
    days = analysis.get("estimated_travel_days_per_year")
    if days is not None and type(days) is not int:
        raise TypeError(
            f"estimated_travel_days_per_year is {type(days).__name__}, "
            f"expected int|None: {days!r}"
        )
    return days


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


def batch_score_fn(
    *,
    input_path: Path,
    output_path: Path,
    profile_file: Path,
    run_date: str | None,
    parent_run_id: str,
) -> dict[str, Any]:
    """Batch-API twin of :func:`default_score_fn` (``overnight --batch``).

    Same cache, telemetry, and scored-record shape — but cache-miss rows go
    through the OpenAI Batch API (~50% cheaper). Note :func:`score_run` loops
    users serially, so each user's batch is submitted and polled to completion
    before the next user starts; the waits stack with user count. OpenAI-only;
    the batch runner fails fast on any other provider.
    """
    from agents.skills_fit.batch import run_skills_fit_batch

    return run_skills_fit_batch(
        run_date=run_date,
        remote_input=input_path,
        output=output_path,
        profile_file=profile_file,
        parent_run_id=parent_run_id,
    )


def score_run(
    conn: psycopg.Connection,
    *,
    run_id: str,
    run_date: str | None,
    runs_dir: Path,
    score_fn: ScoreFn = default_score_fn,
) -> dict[str, Any]:
    """Per-user skills_fit over the classified union — **produce-only**.

    Writes each user's scored survivors to
    ``data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl`` and never
    touches ``raw.job_scores`` (Phase 15 D1); ingest is a separate downstream
    concern. ``conn`` is read-only here — it serves the per-user postings +
    policy query only.

    Returns a summary: ``{"users_scored": N, "users_skipped_no_postings": M,
    "users_failed": F, "postings_scored": K, "postings_unclassified": …,
    "per_user": [...]}``. The end-of-run summary (:mod:`pipeline.summary`)
    builds on it.

    Per-user failure isolation (spec §7): a user whose skills_fit step raises
    is logged with its full traceback, recorded ``failed`` in the summary,
    and skipped — the loop carries on for everyone else.
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
        "postings_unclassified": 0,
        "per_user": [],
    }

    for row in user_rows:
        email = row["email"]
        try:
            policies = UserPolicies.model_validate(row["policies"] or {})
            remote_policy = policies.remote
            relocation_policy = policies.relocation
            acceptable = set(remote_policy.acceptable_classifications)
            max_travel_days = remote_policy.max_travel_days

            survivors: list[dict[str, Any]] = []
            unclassified = 0
            travel_filtered = 0
            relocation_filtered = 0
            for dedup_hash in row["dedup_hashes"]:
                rec = classified.get(dedup_hash)
                if rec is None:
                    unclassified += 1
                    continue
                if _classification_of(rec) not in acceptable:
                    continue
                # Per-user travel gate (spec remote_filter_simplification.md
                # §7). None = no gate; a posting with no numeric estimate is
                # never dropped here (the classification gate above already
                # decided remote-ness).
                days = _travel_days_of(rec)
                if (
                    max_travel_days is not None
                    and days is not None
                    and days > max_travel_days
                ):
                    travel_filtered += 1
                    continue
                # Per-user relocation gate. Missing or None flags treated as
                # False (not flagged → never dropped).
                analysis = rec.get("_remote_analysis") or {}
                if not relocation_policy.allow_required_relocation and analysis.get(
                    "requires_relocation"
                ):
                    relocation_filtered += 1
                    continue
                if not relocation_policy.allow_local_presence_required and analysis.get(
                    "requires_local_presence"
                ):
                    relocation_filtered += 1
                    continue
                survivors.append(rec)
            summary["postings_unclassified"] += unclassified
            if travel_filtered:
                log.info(
                    "%s — %d posting(s) dropped: travel exceeds max_travel_days=%d",
                    email,
                    travel_filtered,
                    max_travel_days,
                )
            if relocation_filtered:
                log.info(
                    "%s — %d posting(s) dropped: relocation not allowed",
                    email,
                    relocation_filtered,
                )

            if not survivors:
                log.info(
                    "%s — no postings survived remote policy "
                    "(%d requested, %d unclassified, %d travel-filtered, "
                    "%d relocation-filtered); skipping skills_fit",
                    email,
                    len(row["dedup_hashes"]),
                    unclassified,
                    travel_filtered,
                    relocation_filtered,
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

            profile_file = (
                run_user_dir(runs_dir, run_id, email) / "candidate_profile.yml"
            )
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
            _stamp_user_email(scored_path, email)

            summary["users_scored"] += 1
            summary["postings_scored"] += len(survivors)
            summary["per_user"].append(
                {
                    "email": email,
                    "postings_scored": len(survivors),
                    "skipped": False,
                }
            )
            log.info(
                "%s — scored %d posting(s) → %s",
                email,
                len(survivors),
                scored_path,
            )
        except Exception:
            # Per-user isolation (spec §7): one user's failure must not sink
            # everyone else's scores. Full traceback to the log now; the
            # end-of-run summary surfaces the one-liner for the morning admin.
            tb = traceback.format_exc()
            log.error("%s — skills_fit failed; isolating:\n%s", email, tb)
            summary["users_failed"] += 1
            summary["per_user"].append(
                {"email": email, "postings_scored": 0, "failed": True, "error": tb}
            )

    log.info(
        "skills_fit phase done for run_id=%s: %d scored, %d skipped "
        "(no postings), %d failed, %d posting(s) scored",
        run_id,
        summary["users_scored"],
        summary["users_skipped_no_postings"],
        summary["users_failed"],
        summary["postings_scored"],
    )
    return summary
