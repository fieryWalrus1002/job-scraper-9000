#!/usr/bin/env python3
"""Compare eval runs recorded in runs.jsonl.

Usage:
    uv run scripts/compare_evals.py
    uv run scripts/compare_evals.py --last 5
    uv run scripts/compare_evals.py --type skills_fit
    uv run scripts/compare_evals.py --sort-by spearman
    uv run scripts/compare_evals.py --diff <run_id_a> <run_id_b>
    uv run scripts/compare_evals.py --against-champion skills_fit --diff <run_id_b>
    uv run scripts/compare_evals.py --against-champion skills_fit --diff <run_id_b> --per-record
    uv run scripts/compare_evals.py --runs-file path/to/runs.jsonl
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from agent_eval.bakeoff import (
    BAKEOFF_COLUMNS,
    build_bakeoff_render_rows,
    ensure_bakeoff_comparable,
)
from agent_eval.run_compare import (
    ALL_SORT_CHOICES,
    SCORER_REGISTRY,
    detect_eval_type,
    format_cell,
)

RUNS_FILE = "data/eval/runs.jsonl"
CHAMPIONS_FILE = "config/eval/champions.yml"
TITLE_WIDTH = 28


# ---------------------------------------------------------------------------
# CLI / I/O helpers
# ---------------------------------------------------------------------------


def die(message: str) -> None:
    print(message)
    sys.exit(1)


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_runs(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        print(f"No runs file found at {path}. Run the eval first.")
        sys.exit(0)
    runs = load_jsonl(p)
    if not runs:
        print(f"No runs recorded yet in {path}.")
        sys.exit(0)
    return runs


def load_champions(path: str = CHAMPIONS_FILE) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        die(f"Champions file not found: {path}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        die(f"Champions file must contain a YAML mapping: {path}")
    return data


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def print_table(rows: list[dict[str, Any]], spec: dict[str, Any], label: str) -> None:
    if not rows:
        return
    cols = spec["table_cols"]
    col_widths = {col: len(col) for col in cols}
    cells: list[dict[str, str]] = []
    for row in rows:
        c = {col: format_cell(col, row.get(col, ""), spec) for col in cols}
        cells.append(c)
        for col in cols:
            col_widths[col] = max(col_widths[col], len(c[col]))

    sep = "  "
    header = sep.join(col.ljust(col_widths[col]) for col in cols)
    divider = sep.join("-" * col_widths[col] for col in cols)
    print(f"\n[{label}]")
    print(header)
    print(divider)
    for c in cells:
        print(sep.join(c[col].ljust(col_widths[col]) for col in cols))


def _champion_run_id_for_eval_type(eval_type: str) -> str | None:
    champion_key = (
        "remote_filter" if eval_type == "remote_filter_categorical" else eval_type
    )
    champions = load_champions()
    return champions.get(champion_key)


def print_bakeoff(rows: list[dict[str, Any]], champion_run_id: str | None) -> None:
    if not rows:
        print("No remote_filter categorical runs found for bake-off.")
        return

    rendered_rows = build_bakeoff_render_rows(rows, champion_run_id)
    col_widths = {
        col: max(len(col), *(len(str(row[col])) for row in rendered_rows))
        for col in BAKEOFF_COLUMNS
    }
    sep = "  "
    print("\n[remote_filter_bakeoff]")
    print(sep.join(col.ljust(col_widths[col]) for col in BAKEOFF_COLUMNS))
    print(sep.join("-" * col_widths[col] for col in BAKEOFF_COLUMNS))
    for row in rendered_rows:
        print(sep.join(str(row[col]).ljust(col_widths[col]) for col in BAKEOFF_COLUMNS))


def print_diff(a: dict[str, Any], b: dict[str, Any], spec: dict[str, Any]) -> None:
    id_a, id_b = a["run_id"], b["run_id"]
    col_w = max(len(id_a), len(id_b), 20)
    print(f"\n  {'Metric':<14}  {id_a:<{col_w}}  {id_b:<{col_w}}  {'Δ':>10}")
    print("  " + "-" * (14 + col_w * 2 + 18))
    for metric in spec["diff_metrics"]:
        va, vb = a.get(metric), b.get(metric)
        fa = format_cell(metric, va, spec)
        fb = format_cell(metric, vb, spec)
        if isinstance(va, float) and isinstance(vb, float):
            delta = vb - va
            arrow = "↑" if delta > 1e-9 else ("↓" if delta < -1e-9 else "=")
            diff_str = f"{arrow} {delta:+.4f}"
        elif isinstance(va, int) and isinstance(vb, int):
            diff_str = "=" if va == vb else f"{vb - va:+d}"
        else:
            diff_str = "=" if va == vb else f"{vb} (was {va})"
        print(f"  {metric:<14}  {fa:<{col_w}}  {fb:<{col_w}}  {diff_str:>10}")
    print()


# ---------------------------------------------------------------------------
# Skills-fit per-record diff helpers
# ---------------------------------------------------------------------------


def truncate_text(text: str, width: int = TITLE_WIDTH) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= width:
        return clean
    return clean[: width - 3] + "..."


def escape_md(text: str) -> str:
    return text.replace("|", "\\|")


def resolve_diff_ids(args: argparse.Namespace) -> tuple[str, str]:
    if not args.diff:
        die("Internal error: resolve_diff_ids called without --diff")

    if args.against_champion:
        champions = load_champions()
        champion_run_id = champions.get(args.against_champion)
        if not champion_run_id:
            die(
                f"No champion configured for {args.against_champion!r} in {CHAMPIONS_FILE}"
            )
        return champion_run_id, args.diff[0]

    return args.diff[0], args.diff[1]


def ensure_same_gold(
    run_a: dict[str, Any], run_b: dict[str, Any], id_a: str, id_b: str
) -> None:
    hash_a = run_a.get("gold_hash")
    hash_b = run_b.get("gold_hash")
    same_gold = bool(hash_a and hash_b and hash_a == hash_b)
    if not same_gold:
        if run_a.get("gold_file") != run_b.get("gold_file") or hash_a != hash_b:
            die(
                f"Run {id_a} uses gold {run_a.get('gold_file')}, "
                f"Run {id_b} uses gold {run_b.get('gold_file')} — not comparable"
            )


def ensure_no_skips(run: dict[str, Any], run_id: str) -> None:
    skipped = (run.get("metrics") or {}).get("skipped", 0)
    if skipped > 0:
        die(
            f"Per-record diff requires skipped=0 for both runs; "
            f"{run_id} has skipped={skipped}"
        )


def reconstruct_skills_fit_predictions(
    run_record: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    gold_rows = load_jsonl(run_record["gold_file"])
    gold: dict[str, int] = {}
    preds: dict[str, int] = {}
    titles: dict[str, str] = {}
    short_to_full: dict[str, list[str]] = {}

    for row in gold_rows:
        full_id = row.get("dedup_hash")
        gold_score = row.get("_human_fit_score")
        if not full_id:
            die(f"Gold row missing dedup_hash in {run_record['gold_file']}")
        if not isinstance(gold_score, int):
            die(
                f"Gold row for dedup_hash {full_id} has invalid _human_fit_score "
                f"in {run_record['gold_file']}: {gold_score!r}"
            )
        gold[full_id] = gold_score
        preds[full_id] = gold_score
        titles[full_id] = row.get("title", "")
        short_to_full.setdefault(full_id[:8], []).append(full_id)

    mismatch_path = run_record.get("mismatch_file")
    if not mismatch_path:
        return preds, gold, titles

    mismatch_file = Path(mismatch_path)
    if not mismatch_file.exists():
        warn(f"mismatch file not found: {mismatch_file} — treating as no mismatches")
        return preds, gold, titles

    for mismatch in load_jsonl(mismatch_file):
        short_id = mismatch.get("record_id")
        matches = short_to_full.get(short_id, [])
        if len(matches) != 1:
            if not matches:
                die(
                    f"Mismatch record_id {short_id!r} from {mismatch_file} does not match any "
                    f"gold dedup_hash prefix"
                )
            die(
                f"Mismatch record_id {short_id!r} from {mismatch_file} is ambiguous across "
                f"multiple gold records"
            )
        pred_score = mismatch.get("pred_score")
        if not isinstance(pred_score, int):
            die(
                f"Mismatch row for record_id {short_id!r} has invalid pred_score in "
                f"{mismatch_file}: {pred_score!r}"
            )
        preds[matches[0]] = pred_score

    return preds, gold, titles


def build_skills_fit_per_record_rows(
    run_a: dict[str, Any], run_b: dict[str, Any], id_a: str, id_b: str
) -> list[dict[str, Any]]:
    ensure_same_gold(run_a, run_b, id_a, id_b)
    ensure_no_skips(run_a, id_a)
    ensure_no_skips(run_b, id_b)

    preds_a, gold_a, titles_a = reconstruct_skills_fit_predictions(run_a)
    preds_b, gold_b, _titles_b = reconstruct_skills_fit_predictions(run_b)

    if set(gold_a) != set(gold_b):
        die("Gold record sets differ between runs — not comparable")

    rows: list[dict[str, Any]] = []
    for full_id in gold_a:
        gold_score_a = gold_a[full_id]
        gold_score_b = gold_b[full_id]
        if gold_score_a != gold_score_b:
            die(
                f"Gold score differs for record {full_id[:8]} between runs — not comparable"
            )
        pred_a = preds_a[full_id]
        pred_b = preds_b[full_id]
        delta_a = pred_a - gold_score_a
        delta_b = pred_b - gold_score_a
        rows.append(
            {
                "record_id": full_id[:8],
                "title": truncate_text(titles_a.get(full_id, "")),
                "gold": gold_score_a,
                "pred_a": pred_a,
                "pred_b": pred_b,
                "delta_a": delta_a,
                "delta_b": delta_b,
                "flipped": "yes" if pred_a != pred_b else "no",
                "sort_score": abs(delta_a) + abs(delta_b),
            }
        )

    rows.sort(key=lambda r: (-r["sort_score"], r["record_id"]))
    return rows


def print_skills_fit_per_record_diff(rows: list[dict[str, Any]]) -> None:
    print(f"  Per-record diff (n={len(rows)}, sorted by |Δ_A| + |Δ_B| desc)")
    print()
    print("| record_id | title | gold | A.pred | B.pred | Δ_A | Δ_B | flipped |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in rows:
        print(
            "| "
            + " | ".join(
                [
                    row["record_id"],
                    escape_md(row["title"]),
                    str(row["gold"]),
                    str(row["pred_a"]),
                    str(row["pred_b"]),
                    f"{row['delta_a']:+d}",
                    f"{row['delta_b']:+d}",
                    row["flipped"],
                ]
            )
            + " |"
        )
    print()

    flipped = sum(1 for row in rows if row["flipped"] == "yes")
    if flipped == 0:
        summary = f"Summary: {len(rows)} records | 0 flipped | identical predictions on all {len(rows)}"
    else:
        summary = f"Summary: {len(rows)} records | {flipped} flipped"
    print(f"  {summary}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--runs-file", default=RUNS_FILE, help=f"Run log JSONL (default: {RUNS_FILE})"
    )
    p.add_argument(
        "--last",
        type=int,
        metavar="N",
        help="Show only the N most recent runs (per type)",
    )
    p.add_argument(
        "--type",
        choices=list(SCORER_REGISTRY),
        dest="eval_type",
        help="Filter to one eval type",
    )
    p.add_argument(
        "--sort-by",
        default="timestamp",
        choices=ALL_SORT_CHOICES,
        help="Sort column (default: timestamp)",
    )
    p.add_argument(
        "--diff",
        nargs="+",
        metavar="RUN_ID",
        help=(
            "Side-by-side diff. Use '--diff <run_a> <run_b>' or "
            "'--against-champion <scorer> --diff <run_b>'"
        ),
    )
    p.add_argument(
        "--bakeoff",
        action="store_true",
        help=(
            "Print an N-way remote_filter categorical quality x cost table. "
            "Combine with --last N to select candidate runs."
        ),
    )
    p.add_argument(
        "--against-champion",
        choices=list(SCORER_REGISTRY),
        help=f"Resolve the left-hand diff run from {CHAMPIONS_FILE}",
    )
    p.add_argument(
        "--per-record",
        action="store_true",
        help="After aggregate diff, print a per-record table (skills_fit only)",
    )
    args = p.parse_args()

    if args.bakeoff and args.diff:
        p.error("--bakeoff cannot be combined with --diff")
    if args.per_record and not args.diff:
        p.error("--per-record requires --diff")
    if args.against_champion and not args.diff:
        p.error("--against-champion requires --diff")
    if args.against_champion:
        if len(args.diff) != 1:
            p.error("--against-champion requires exactly one run ID with --diff")
    elif args.diff and len(args.diff) != 2:
        p.error("--diff requires two run IDs unless --against-champion is set")

    return args


def _tag_runs(
    raw_runs: list[dict[str, Any]],
) -> tuple[
    list[tuple[str, dict[str, Any], dict[str, Any]]],
    dict[str, tuple[str, dict[str, Any], dict[str, Any]]],
]:
    tagged: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    by_id: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for run in raw_runs:
        etype = detect_eval_type(run)
        if etype == "unknown":
            continue
        spec = SCORER_REGISTRY[etype]
        flat = spec["flatten"](run)
        tagged.append((etype, run, flat))
        by_id[flat["run_id"]] = (etype, run, flat)
    return tagged, by_id


def main() -> None:
    args = parse_args()
    raw_runs = load_runs(args.runs_file)
    tagged, by_id = _tag_runs(raw_runs)

    if args.diff:
        id_a, id_b = resolve_diff_ids(args)
        missing = [rid for rid in (id_a, id_b) if rid not in by_id]
        if missing:
            die(f"Run IDs not found: {', '.join(missing)}")
        type_a, raw_a, row_a = by_id[id_a]
        type_b, raw_b, row_b = by_id[id_b]
        if type_a != type_b:
            die(f"Cannot diff runs of different types: {type_a} vs {type_b}")
        print_diff(row_a, row_b, SCORER_REGISTRY[type_a])
        if args.per_record:
            if type_a != "skills_fit":
                die("--per-record is currently supported only for skills_fit runs")
            rows = build_skills_fit_per_record_rows(raw_a, raw_b, id_a, id_b)
            print_skills_fit_per_record_diff(rows)
        return

    if args.bakeoff:
        if args.eval_type and args.eval_type != "remote_filter_categorical":
            die("--bakeoff is only supported for remote_filter_categorical runs")
        candidate_runs = [
            (raw, row)
            for etype, raw, row in tagged
            if etype == "remote_filter_categorical"
        ]
        candidate_runs.sort(key=lambda pair: pair[1].get("timestamp", ""))
        if args.last:
            candidate_runs = candidate_runs[-args.last :]
        try:
            ensure_bakeoff_comparable([raw for raw, _row in candidate_runs])
        except ValueError as exc:
            die(str(exc))
        print_bakeoff(
            [row for _raw, row in candidate_runs],
            _champion_run_id_for_eval_type("remote_filter_categorical"),
        )
        return

    groups: dict[str, list[dict[str, Any]]] = {}
    for etype, _raw, row in tagged:
        if args.eval_type and etype != args.eval_type:
            continue
        groups.setdefault(etype, []).append(row)

    if not groups:
        print("No matching runs found.")
        return

    for etype, rows in groups.items():
        spec = SCORER_REGISTRY[etype]
        sort_key = args.sort_by if args.sort_by in spec["sort_choices"] else "timestamp"
        rows.sort(key=lambda r: r.get(sort_key, ""))
        if args.last:
            rows = rows[-args.last :]
        print_table(rows, spec, etype)


if __name__ == "__main__":
    main()
