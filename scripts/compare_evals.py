#!/usr/bin/env python3
"""Compare eval runs recorded in runs.jsonl.

Usage:
    python scripts/compare_evals.py
    python scripts/compare_evals.py --last 5
    python scripts/compare_evals.py --sort-by f1
    python scripts/compare_evals.py --diff <run_id_a> <run_id_b>
    python scripts/compare_evals.py --runs-file path/to/runs.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

RUNS_FILE = "data/eval/runs.jsonl"
TABLE_COLS = ["run_id", "date", "model", "temperature", "total", "skipped",
              "accuracy", "precision", "recall", "f1"]
SORT_CHOICES = ["timestamp", "accuracy", "precision", "recall", "f1"]
METRIC_COLS = {"accuracy", "precision", "recall", "f1"}
INT_COLS = {"total", "skipped"}
DIFF_METRICS = ["accuracy", "precision", "recall", "f1", "total", "skipped"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--runs-file", default=RUNS_FILE,
        help=f"Run log JSONL (default: {RUNS_FILE})",
    )
    p.add_argument(
        "--last", type=int, metavar="N",
        help="Show only the N most recent runs",
    )
    p.add_argument(
        "--sort-by", default="timestamp", choices=SORT_CHOICES,
        help="Sort column (default: timestamp)",
    )
    p.add_argument(
        "--diff", nargs=2, metavar=("RUN_ID_A", "RUN_ID_B"),
        help="Side-by-side diff of two runs with directional indicators",
    )
    return p.parse_args()


def load_runs(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"No runs file found at {path}. Run the eval first.")
        sys.exit(0)
    runs = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    if not runs:
        print(f"No runs recorded yet in {path}.")
        sys.exit(0)
    return runs


def flatten(run: dict) -> dict:
    m = run.get("metrics", {})
    cfg = run.get("config") or {}
    return {
        "run_id": run.get("run_id", ""),
        "timestamp": run.get("timestamp", ""),
        "date": run.get("timestamp", "")[:10],
        "model": cfg.get("model", ""),
        "temperature": cfg.get("temperature", ""),
        "total": m.get("total", 0),
        "skipped": m.get("skipped", 0),
        "accuracy": m.get("accuracy", 0.0),
        "precision": m.get("precision", 0.0),
        "recall": m.get("recall", 0.0),
        "f1": m.get("f1", 0.0),
    }


def format_cell(col: str, val) -> str:
    if col in METRIC_COLS:
        return f"{val:.4f}"
    if col in INT_COLS:
        return str(val)
    return str(val)


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No runs to display.")
        return

    col_widths = {col: len(col) for col in TABLE_COLS}
    cells: list[dict] = []
    for row in rows:
        c = {col: format_cell(col, row[col]) for col in TABLE_COLS}
        cells.append(c)
        for col in TABLE_COLS:
            col_widths[col] = max(col_widths[col], len(c[col]))

    sep = "  "
    header = sep.join(col.ljust(col_widths[col]) for col in TABLE_COLS)
    divider = sep.join("-" * col_widths[col] for col in TABLE_COLS)
    print(header)
    print(divider)
    for c in cells:
        print(sep.join(c[col].ljust(col_widths[col]) for col in TABLE_COLS))


def print_diff(a: dict, b: dict) -> None:
    id_a = a["run_id"]
    id_b = b["run_id"]
    col_w = max(len(id_a), len(id_b), 20)

    print(f"\n  {'Metric':<14}  {id_a:<{col_w}}  {id_b:<{col_w}}  {'Δ':>10}")
    print("  " + "-" * (14 + col_w * 2 + 18))
    for metric in DIFF_METRICS:
        va = a[metric]
        vb = b[metric]
        fa = format_cell(metric, va)
        fb = format_cell(metric, vb)
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


def main() -> None:
    args = parse_args()
    runs = load_runs(args.runs_file)
    rows = [flatten(r) for r in runs]

    if args.diff:
        id_a, id_b = args.diff
        by_id = {r["run_id"]: r for r in rows}
        missing = [rid for rid in (id_a, id_b) if rid not in by_id]
        if missing:
            print(f"Run IDs not found: {', '.join(missing)}")
            sys.exit(1)
        print_diff(by_id[id_a], by_id[id_b])
        return

    if args.sort_by == "timestamp":
        rows.sort(key=lambda r: r["timestamp"])
    else:
        rows.sort(key=lambda r: r[args.sort_by])

    if args.last:
        rows = rows[-args.last:]

    print_table(rows)


if __name__ == "__main__":
    main()
