"""End-of-run summary + exit-code verdict (Phase 13 spec §7, slice 7).

The admin reads one stderr block every morning. It rolls up the two failure
surfaces of an overnight run into a per-user verdict:

- **scrape jobs** — ``pipe.scrape_jobs`` rows the worker marked ``failed``
  (full traceback already captured in ``error`` and logged at failure time).
- **skills_fit** — per-user scoring steps that raised, isolated by
  :func:`pipeline.scoring.score_run` into its summary's ``per_user`` entries.

A user is **ok** when at least one of their scrapes succeeded *and* their
scoring step (if reached) did not raise — they may legitimately have scored
nothing on a quiet night. A user is **failed** when every scrape failed, or
scoring raised for them.

Exit-code rule (spec §7): non-zero iff *every* user failed; any partial
success exits zero, because the admin reads the summary and re-runs the
idempotent queue for the failed rows.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

log = logging.getLogger(__name__)

_SELECT_SCRAPE_OUTCOMES = """
    SELECT u.email, j.source, j.status, j.error
    FROM pipe.scrape_jobs j
    JOIN app.users u ON u.id = j.user_id
    WHERE j.run_id = %s
    ORDER BY u.email, j.source
"""


def _exception_line(error: str | None) -> str:
    """Last non-empty line of a captured traceback — the exception itself.

    The full traceback lives in ``pipe.scrape_jobs.error`` (and the run log);
    the summary shows the one-liner so a morning skim is useful."""
    if not error:
        return "(no error text captured)"
    lines = [ln for ln in error.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "(no error text captured)"


def build_overnight_summary(
    database_url: str,
    *,
    run_id: str,
    scrape: dict[str, Any],
    scoring: dict[str, Any] | None,
) -> dict[str, Any]:
    """Aggregate per-user outcomes into a stderr-ready summary + verdict.

    Opens its own short-lived connection (the phase work has closed its own).
    ``scoring`` is ``None`` for ``--scrape-only`` runs and quiet nights with
    nothing consolidated; the verdict is then scrape-based only.
    """
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(_SELECT_SCRAPE_OUTCOMES, (run_id,)).fetchall()

    # email -> {"scraped_ok": bool, "scrape_failed": [(source, exc_line)]}
    users: dict[str, dict[str, Any]] = {}
    for email, source, status, error in rows:
        u = users.setdefault(
            email, {"scraped_ok": False, "scrape_failed": [], "scoring_error": None}
        )
        if status == "succeeded":
            u["scraped_ok"] = True
        elif status == "failed":
            u["scrape_failed"].append((source, _exception_line(error)))

    scored_by_email: dict[str, dict[str, Any]] = {}
    if scoring is not None:
        for entry in scoring.get("per_user", []):
            scored_by_email[entry["email"]] = entry

    per_user: list[dict[str, Any]] = []
    for email in sorted(users):
        u = users[email]
        scored = scored_by_email.get(email)
        scoring_failed = bool(scored and scored.get("failed"))
        scoring_error = (scored or {}).get("error") if scoring_failed else None
        ok = u["scraped_ok"] and not scoring_failed
        per_user.append(
            {
                "email": email,
                "ok": ok,
                "scraped_ok": u["scraped_ok"],
                "scrape_failed": u["scrape_failed"],
                "scoring_failed": scoring_failed,
                "scoring_error": _exception_line(scoring_error)
                if scoring_error
                else None,
                "postings_scored": (scored or {}).get("postings_scored", 0),
            }
        )

    n_ok = sum(1 for u in per_user if u["ok"])
    n_failed = len(per_user) - n_ok
    all_failed = len(per_user) > 0 and n_ok == 0

    text = _format(run_id, per_user, n_ok, n_failed)
    return {
        "run_id": run_id,
        "per_user": per_user,
        "users_ok": n_ok,
        "users_failed": n_failed,
        "all_failed": all_failed,
        "text": text,
    }


def _format(
    run_id: str, per_user: list[dict[str, Any]], n_ok: int, n_failed: int
) -> str:
    lines = [
        f"Overnight run {run_id} summary: "
        f"{len(per_user)} user(s) — {n_ok} ok, {n_failed} failed"
    ]
    if not per_user:
        lines.append("  (no users planned this run)")
        return "\n".join(lines)

    for u in per_user:
        verdict = "OK" if u["ok"] else "FAILED"
        scored = f" ({u['postings_scored']} scored)" if u["ok"] else ""
        lines.append(f"  {u['email']} — {verdict}{scored}")
        if not u["scraped_ok"] and u["scrape_failed"]:
            lines.append("    ✗ all scrapes failed:")
        for source, exc in u["scrape_failed"]:
            lines.append(f"      ✗ {source}: {exc}")
        if u["scoring_failed"]:
            lines.append(f"    ✗ skills_fit: {u['scoring_error']}")
    return "\n".join(lines)
