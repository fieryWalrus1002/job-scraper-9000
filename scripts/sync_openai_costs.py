#!/usr/bin/env python3
"""Reconcile estimated run costs against OpenAI's authoritative numbers.

Walks ``data/runs/runs.jsonl``, finds OpenAI-provider runs whose
``cost.actual_provider_total`` is not yet populated (and that ended at least
SETTLING_DELAY_SECONDS ago), queries the OpenAI Costs API per-day for the
project, and attributes the day's total spend back to each run.

Caveat: the OpenAI Costs API only supports 1d buckets, so if multiple runs
happen in the same day they share the day's total proportionally by their
estimated cost. That's good enough for drift detection vs the local estimates.

Usage:
    uv run scripts/sync_openai_costs.py
    uv run scripts/sync_openai_costs.py --project-id proj_xxxx
    uv run scripts/sync_openai_costs.py --force   # re-query even if populated
"""

import argparse
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from utils.openai_costs import query_costs, sum_cost_amounts

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_RUNS_PATH = Path("data/runs/runs.jsonl")
SETTLING_DELAY_SECONDS = 600  # 10 min; usage often shows up sooner but not guaranteed


def parse_iso(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def day_start_ts(iso_ts: str) -> int:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    return int(day.timestamp())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runs-path", default=str(DEFAULT_RUNS_PATH))
    parser.add_argument(
        "--project-id", default=None, help="Filter OpenAI Costs by project_id"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-query even for runs already populated",
    )
    args = parser.parse_args()

    runs_path = Path(args.runs_path)
    if not runs_path.exists():
        log.error("No runs file at %s", runs_path)
        return

    now = time.time()
    records = []
    for line in runs_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))

    # Group eligible OpenAI runs by day
    by_day: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        llm = record.get("llm") or {}
        cost = record.get("cost") or {}
        if llm.get("provider") != "openai":
            continue
        ended_iso = (record.get("timing") or {}).get("ended_at")
        if not ended_iso:
            continue
        if cost.get("actual_provider_total") is not None and not args.force:
            continue
        if now - parse_iso(ended_iso) < SETTLING_DELAY_SECONDS:
            log.info(
                "Skipping %s — ended %ds ago, settling delay is %ds",
                record.get("run_id"),
                int(now - parse_iso(ended_iso)),
                SETTLING_DELAY_SECONDS,
            )
            continue
        by_day[day_start_ts(ended_iso)].append(record)

    if not by_day:
        log.info("No runs needing cost backfill.")
        return

    queried_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0

    for day_ts, day_runs in by_day.items():
        day_end_ts = day_ts + 86400
        try:
            response = query_costs(
                start_time=day_ts,
                end_time=day_end_ts,
                project_ids=[args.project_id] if args.project_id else None,
            )
        except Exception as exc:
            log.warning(
                "Costs API query failed for day starting %d: %s", day_ts, exc
            )
            continue

        day_total = sum_cost_amounts(response)
        if day_total <= 0:
            log.info(
                "Day starting %s returned $0 from Costs API — likely still settling, skipping",
                datetime.fromtimestamp(day_ts, tz=timezone.utc).date().isoformat(),
            )
            continue

        # Allocate day total by estimated share
        sum_estimated = sum(
            float((r.get("cost") or {}).get("estimated_total") or 0)
            for r in day_runs
        )
        for run in day_runs:
            est = float((run.get("cost") or {}).get("estimated_total") or 0)
            if sum_estimated > 0:
                share = est / sum_estimated
            else:
                share = 1.0 / len(day_runs)
            allocated = round(day_total * share, 8)
            cost = run.setdefault("cost", {"currency": "USD"})
            cost["actual_provider_total"] = allocated
            cost["actual_queried_at"] = queried_at
            updated += 1
            log.info(
                "Updated %s: estimated=$%.4f, allocated_actual=$%.4f (day_total=$%.4f, share=%.2f%%)",
                run.get("run_id"),
                est,
                allocated,
                day_total,
                share * 100,
            )

    if updated:
        tmp_path = runs_path.with_suffix(".jsonl.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        tmp_path.replace(runs_path)
        log.info("Rewrote %s — %d records updated", runs_path, updated)
    else:
        log.info("No updates written.")


if __name__ == "__main__":
    main()
