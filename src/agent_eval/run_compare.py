"""Run detection and flattening helpers for eval run comparison."""

from typing import Any


def flatten_remote_filter(run: dict[str, Any]) -> dict[str, Any]:
    """Flatten legacy binary remote-filter eval run metrics for tabular display."""
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


def flatten_skills_fit(run: dict[str, Any]) -> dict[str, Any]:
    """Flatten skills-fit ordinal eval run metrics for tabular display."""
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


def _require(mapping: object, key: str, path: str, run_id: str) -> Any:
    # Headline metrics are load-bearing for champion/challenger decisions — a
    # missing field is schema drift, not a legitimate 0.0. Fail loud.
    if not isinstance(mapping, dict) or key not in mapping:
        raise ValueError(
            f"categorical run {run_id!r} is missing required metric {path!r}"
        )
    return mapping[key]


def extract_remote_error_counts(
    metrics: dict[str, Any], run_id: str = ""
) -> tuple[int, int]:
    """Return remote false-negative and false-positive counts from a confusion matrix.

    ``compute_categorical_metrics`` records ``confusion[pred_idx][gold_idx]``.
    For the ``remote`` class, false negatives are non-remote prediction rows in
    the remote gold column; false positives are the non-remote gold columns in
    the remote prediction row.
    """
    labels = _require(metrics, "labels", "labels", run_id)
    confusion = _require(metrics, "confusion", "confusion", run_id)
    if not isinstance(labels, list) or "remote" not in labels:
        raise ValueError(f"categorical run {run_id!r} has invalid labels")
    if not isinstance(confusion, list):
        raise ValueError(f"categorical run {run_id!r} has invalid confusion")
    # Fail loud on a non-square matrix rather than IndexError-ing while indexing
    # confusion[remote_idx] / row[remote_idx] below.
    if len(confusion) != len(labels) or any(
        not isinstance(row, list) or len(row) != len(labels) for row in confusion
    ):
        raise ValueError(
            f"categorical run {run_id!r} confusion is not a {len(labels)}x"
            f"{len(labels)} matrix matching labels"
        )

    remote_idx = labels.index("remote")
    remote_fn = sum(
        int(row[remote_idx])
        for i, row in enumerate(confusion)
        if i != remote_idx and isinstance(row, list) and remote_idx < len(row)
    )
    remote_row = confusion[remote_idx]
    if not isinstance(remote_row, list):
        raise ValueError(f"categorical run {run_id!r} has invalid remote row")
    remote_fp = sum(int(count) for i, count in enumerate(remote_row) if i != remote_idx)
    return remote_fn, remote_fp


def flatten_remote_filter_categorical(run: dict[str, Any]) -> dict[str, Any]:
    """Flatten classifier-native remote-filter eval metrics for tabular display."""
    m = run.get("metrics", {})
    cfg = run.get("config") or {}
    cost = run.get("cost") or {}
    run_id = run.get("run_id", "")

    per_class = m.get("per_class")
    remote = _require(
        per_class if isinstance(per_class, dict) else {},
        "remote",
        "per_class.remote",
        run_id,
    )
    remote_fn, remote_fp = extract_remote_error_counts(m, run_id)
    skipped = _require(m, "skipped", "skipped", run_id)
    agent_failed = int(m.get("agent_failed", 0) or 0)
    return {
        "run_id": run_id,
        "timestamp": run.get("timestamp", ""),
        "date": run.get("timestamp", "")[:10],
        "model": cfg.get("model", ""),
        "temperature": cfg.get("temperature", ""),
        "total": _require(m, "total", "total", run_id),
        "skipped": skipped,
        "micro_acc": _require(m, "micro_accuracy", "micro_accuracy", run_id),
        "remote_recall": _require(remote, "recall", "per_class.remote.recall", run_id),
        "remote_fn": remote_fn,
        "remote_fp": remote_fp,
        "macro_f1": _require(m, "macro_f1", "macro_f1", run_id),
        "travel_mae": m.get("travel_mae"),  # intentional nullable
        "agent_failed": agent_failed,
        "skipped_failed": f"{skipped}/{agent_failed}",
        "est_cost": cost.get("estimated_cost_usd"),
        "cost_per_correct": cost.get("estimated_cost_per_correct_usd"),
    }


ScorerSpec = dict[str, Any]


SCORER_REGISTRY: dict[str, ScorerSpec] = {
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
        "flatten": flatten_remote_filter,
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
            "remote_fn",
            "remote_fp",
            "macro_f1",
            "travel_mae",
        ],
        "metric_cols": {
            "micro_acc",
            "remote_recall",
            "macro_f1",
            "travel_mae",
            "est_cost",
            "cost_per_correct",
        },
        "int_cols": {"total", "skipped", "remote_fn", "remote_fp", "agent_failed"},
        "diff_metrics": [
            "micro_acc",
            "remote_recall",
            "remote_fn",
            "remote_fp",
            "macro_f1",
            "travel_mae",
            "total",
            "skipped",
            "agent_failed",
        ],
        "sort_choices": ["timestamp", "micro_acc", "remote_recall", "macro_f1"],
        "flatten": flatten_remote_filter_categorical,
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
        "flatten": flatten_skills_fit,
    },
}

ALL_SORT_CHOICES = sorted(
    {c for spec in SCORER_REGISTRY.values() for c in spec["sort_choices"]}
)


def detect_eval_type(run: dict[str, Any]) -> str:
    """Detect the eval family for a run record.

    Return the family only when exactly one detector matches. Zero matches or an
    ambiguous multi-match resolves to ``"unknown"`` rather than silently letting
    registry order pick a winner.
    """
    m = run.get("metrics", {})
    matches = [name for name, spec in SCORER_REGISTRY.items() if spec["detect"](m)]
    if len(matches) == 1:
        return matches[0]
    return "unknown"


def format_cell(col: str, val: Any, spec: ScorerSpec) -> str:
    """Format a flattened run value using the scorer's display column metadata."""
    if col in spec["metric_cols"]:
        if val is None:
            return "—"
        return f"{val:.4f}"
    if col in spec["int_cols"]:
        return str(val)
    return str(val)
