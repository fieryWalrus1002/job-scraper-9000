#!/usr/bin/env python3
"""Compare eval runs recorded in runs.jsonl.

Usage:
    uv run scripts/compare_evals.py
    uv run scripts/compare_evals.py --last 5
    uv run scripts/compare_evals.py --type skills_fit
    uv run scripts/compare_evals.py --sort-by spearman
    uv run scripts/compare_evals.py --diff <run_id_a> <run_id_b>
    uv run scripts/compare_evals.py --runs-file path/to/runs.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

RUNS_FILE = "data/eval/runs.jsonl"


# ---------------------------------------------------------------------------
# Scorer registry
# Each entry owns one eval type.  Keys:
#   detect(metrics_dict) -> bool   True if this type owns the run
#   table_cols                     ordered column list for the summary table
#   metric_cols                    set of float columns (4-decimal formatting)
#   int_cols                       set of int columns
#   diff_metrics                   ordered list for --diff view
#   sort_choices                   valid --sort-by values
#   flatten(run) -> dict           extract flat row from raw run record
# ---------------------------------------------------------------------------


def _flatten_remote_filter(run: dict) -> dict:
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


def _flatten_skills_fit(run: dict) -> dict:
    m = run.get("metrics", {})
    cfg = run.get("config") or {}
    return {
        "run_id": run.get("run_id", ""),
        "timestamp": run.get("timestamp", ""),
        "date": run.get("timestamp", "")[:10],
        "scorer": run.get("scorer", ""),
        "model": cfg.get("model", ""),
        "total": m.get("total", 0),
        "exact_match": m.get("exact_match_acc", 0.0),
        "off_by_one": m.get("off_by_one_acc", 0.0),
        "mae": m.get("mae", 0.0),
        "bias": m.get("bias", 0.0),
        "spearman": m.get("spearman_rho", 0.0),
        "p5": m.get("precision_at_5", 0.0),
    }


SCORER_REGISTRY: dict[str, dict] = {
    "remote_filter": {
        "detect": lambda m: "accuracy" in m and "exact_match_acc" not in m,
        "table_cols": [
            "run_id",
            "date",
            "model",
            "temperature",
            "total",
            "skipped",
            "accuracy",
            "precision",
            "recall",
            "f1",
        ],
        "metric_cols": {"accuracy", "precision", "recall", "f1"},
        "int_cols": {"total", "skipped"},
        "diff_metrics": ["accuracy", "precision", "recall", "f1", "total", "skipped"],
        "sort_choices": ["timestamp", "accuracy", "precision", "recall", "f1"],
        "flatten": _flatten_remote_filter,
    },
    "skills_fit": {
        "detect": lambda m: "exact_match_acc" in m,
        "table_cols": [
            "run_id",
            "date",
            "scorer",
            "model",
            "total",
            "exact_match",
            "off_by_one",
            "mae",
            "bias",
            "spearman",
            "p5",
        ],
        "metric_cols": {"exact_match", "off_by_one", "mae", "bias", "spearman", "p5"},
        "int_cols": {"total"},
        "diff_metrics": [
            "exact_match",
            "off_by_one",
            "mae",
            "bias",
            "spearman",
            "p5",
            "total",
        ],
        "sort_choices": [
            "timestamp",
            "exact_match",
            "off_by_one",
            "mae",
            "bias",
            "spearman",
            "p5",
        ],
        "flatten": _flatten_skills_fit,
    },
}

ALL_SORT_CHOICES = sorted(
    {c for spec in SCORER_REGISTRY.values() for c in spec["sort_choices"]}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def detect_eval_type(run: dict) -> str:
    m = run.get("metrics", {})
    for name, spec in SCORER_REGISTRY.items():
        if spec["detect"](m):
            return name
    return "unknown"


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


def format_cell(col: str, val, spec: dict) -> str:
    if col in spec["metric_cols"]:
        return f"{val:.4f}"
    if col in spec["int_cols"]:
        return str(val)
    return str(val)


def print_table(rows: list[dict], spec: dict, label: str) -> None:
    if not rows:
        return
    cols = spec["table_cols"]
    col_widths = {col: len(col) for col in cols}
    cells: list[dict] = []
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


def print_diff(a: dict, b: dict, spec: dict) -> None:
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
        nargs=2,
        metavar=("RUN_ID_A", "RUN_ID_B"),
        help="Side-by-side diff of two runs",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raw_runs = load_runs(args.runs_file)

    # Tag every run with its eval type and flatten it.
    tagged: list[tuple[str, dict]] = []
    for run in raw_runs:
        etype = detect_eval_type(run)
        if etype == "unknown":
            continue
        spec = SCORER_REGISTRY[etype]
        tagged.append((etype, spec["flatten"](run)))

    if args.diff:
        id_a, id_b = args.diff
        by_id = {row["run_id"]: (etype, row) for etype, row in tagged}
        missing = [rid for rid in (id_a, id_b) if rid not in by_id]
        if missing:
            print(f"Run IDs not found: {', '.join(missing)}")
            sys.exit(1)
        type_a, row_a = by_id[id_a]
        type_b, row_b = by_id[id_b]
        if type_a != type_b:
            print(f"Cannot diff runs of different types: {type_a} vs {type_b}")
            sys.exit(1)
        print_diff(row_a, row_b, SCORER_REGISTRY[type_a])
        return

    # Group by type, optionally filter.
    groups: dict[str, list[dict]] = {}
    for etype, row in tagged:
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
