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

import yaml

RUNS_FILE = "data/eval/runs.jsonl"
CHAMPIONS_FILE = "config/eval/champions.yml"
TITLE_WIDTH = 28


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


def _flatten_remote_filter_categorical(run: dict) -> dict:
    m = run.get("metrics", {})
    cfg = run.get("config") or {}
    per_class = m.get("per_class") or {}
    remote = per_class.get("remote") or {}
    return {
        "run_id": run.get("run_id", ""),
        "timestamp": run.get("timestamp", ""),
        "date": run.get("timestamp", "")[:10],
        "model": cfg.get("model", ""),
        "temperature": cfg.get("temperature", ""),
        "total": m.get("total", 0),
        "skipped": m.get("skipped", 0),
        "micro_acc": m.get("micro_accuracy", 0.0),
        "remote_recall": remote.get("recall", 0.0),
        "macro_f1": m.get("macro_f1", 0.0),
        "travel_mae": m.get("travel_mae"),
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
    "remote_filter_categorical": {
        "detect": lambda m: "micro_accuracy" in m,
        "table_cols": [
            "run_id",
            "date",
            "model",
            "temperature",
            "total",
            "skipped",
            "micro_acc",
            "remote_recall",
            "macro_f1",
            "travel_mae",
        ],
        "metric_cols": {"micro_acc", "remote_recall", "macro_f1", "travel_mae"},
        "int_cols": {"total", "skipped"},
        "diff_metrics": ["micro_acc", "remote_recall", "macro_f1", "total", "skipped"],
        "sort_choices": ["timestamp", "micro_acc", "remote_recall", "macro_f1"],
        "flatten": _flatten_remote_filter_categorical,
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


def die(message: str) -> None:
    print(message)
    sys.exit(1)


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def detect_eval_type(run: dict) -> str:
    m = run.get("metrics", {})
    for name, spec in SCORER_REGISTRY.items():
        if spec["detect"](m):
            return name
    return "unknown"


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_runs(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"No runs file found at {path}. Run the eval first.")
        sys.exit(0)
    runs = load_jsonl(p)
    if not runs:
        print(f"No runs recorded yet in {path}.")
        sys.exit(0)
    return runs


def load_champions(path: str = CHAMPIONS_FILE) -> dict:
    p = Path(path)
    if not p.exists():
        die(f"Champions file not found: {path}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        die(f"Champions file must contain a YAML mapping: {path}")
    return data


def format_cell(col: str, val, spec: dict) -> str:
    if col in spec["metric_cols"]:
        if val is None:
            return "—"
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


def ensure_same_gold(run_a: dict, run_b: dict, id_a: str, id_b: str) -> None:
    hash_a = run_a.get("gold_hash")
    hash_b = run_b.get("gold_hash")
    same_gold = bool(hash_a and hash_b and hash_a == hash_b)
    if not same_gold:
        if run_a.get("gold_file") != run_b.get("gold_file") or hash_a != hash_b:
            die(
                f"Run {id_a} uses gold {run_a.get('gold_file')}, "
                f"Run {id_b} uses gold {run_b.get('gold_file')} — not comparable"
            )


def ensure_no_skips(run: dict, run_id: str) -> None:
    skipped = (run.get("metrics") or {}).get("skipped", 0)
    if skipped > 0:
        die(
            f"Per-record diff requires skipped=0 for both runs; "
            f"{run_id} has skipped={skipped}"
        )


def reconstruct_skills_fit_predictions(
    run_record: dict,
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
    run_a: dict, run_b: dict, id_a: str, id_b: str
) -> list[dict]:
    ensure_same_gold(run_a, run_b, id_a, id_b)
    ensure_no_skips(run_a, id_a)
    ensure_no_skips(run_b, id_b)

    preds_a, gold_a, titles_a = reconstruct_skills_fit_predictions(run_a)
    preds_b, gold_b, _titles_b = reconstruct_skills_fit_predictions(run_b)

    if set(gold_a) != set(gold_b):
        die("Gold record sets differ between runs — not comparable")

    rows: list[dict] = []
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


def print_skills_fit_per_record_diff(rows: list[dict]) -> None:
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


def main() -> None:
    args = parse_args()
    raw_runs = load_runs(args.runs_file)

    # Tag every run with its eval type and flatten it.
    tagged: list[tuple[str, dict]] = []
    by_id: dict[str, tuple[str, dict, dict]] = {}
    for run in raw_runs:
        etype = detect_eval_type(run)
        if etype == "unknown":
            continue
        spec = SCORER_REGISTRY[etype]
        flat = spec["flatten"](run)
        tagged.append((etype, flat))
        by_id[flat["run_id"]] = (etype, run, flat)

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
