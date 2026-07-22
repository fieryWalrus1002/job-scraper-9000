"""Weighted-error metric for remote_filter eval (#545).

Micro accuracy and macro-F1 treat every misclassification equally, but for a
remote-focused job search the error costs are strongly asymmetric (losing a real
remote job is unrecoverable; a hybrid/onsite mix-up is nearly free). This module
turns a per-confusion-cell cost matrix into a single scalar ``weighted_error``
(lower is better), computed at compare-time from each run's already-persisted
confusion matrix — so re-weighting historical runs never requires a re-run.

    weighted_error = Σ confusion[pred][gold] * cost[gold][pred]

The metric is an *additive lens*: it never replaces micro/macro or the champion
metric pair, and raw ``remote_fn`` / ``remote_fp`` stay visible alongside it. The
cost matrix is a value judgment kept in ``config/eval/remote_filter_error_costs.yml``
and hashed so a weighted comparison is only valid across rows sharing one matrix.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from agent_eval.provenance import hash_string

_REPO_ROOT = Path(__file__).parents[2]
DEFAULT_COST_MATRIX_PATH = (
    _REPO_ROOT / "config" / "eval" / "remote_filter_error_costs.yml"
)


class CostMatrix:
    """A validated ``cost[gold][pred]`` matrix plus a stable content hash."""

    def __init__(self, costs: dict[str, dict[str, float]], version: int) -> None:
        self.costs = costs
        self.version = version
        self.labels = list(costs)

    @property
    def hash(self) -> str:
        """Content hash over the canonicalized cost cells (order-independent)."""
        canonical = json.dumps(
            {"version": self.version, "costs": self.costs},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hash_string(canonical)

    def cost(self, gold: str, pred: str) -> float:
        return self.costs[gold][pred]


def load_cost_matrix(
    path: Path = DEFAULT_COST_MATRIX_PATH,
    *,
    expected_labels: Iterable[str] | None = None,
) -> CostMatrix:
    """Load and validate the weighted-error cost matrix from YAML.

    Fails loud (per CLAUDE.md) on a missing file, missing ``costs`` block, a
    non-square matrix, or non-numeric cells — a silent default would let a broken
    config quietly produce a meaningless scalar. When ``expected_labels`` is given
    (the fixed remote_filter axis at the call site), the matrix must price exactly
    that label set, so a mislabeled-but-square matrix fails at load rather than
    surfacing later as an unpriced-run-label error.
    """
    if not path.exists():
        raise FileNotFoundError(f"cost matrix config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_costs = data.get("costs")
    if not isinstance(raw_costs, dict) or not raw_costs:
        raise ValueError(f"{path}: expected a non-empty 'costs' mapping")

    labels = list(raw_costs)
    costs: dict[str, dict[str, float]] = {}
    for gold, row in raw_costs.items():
        if not isinstance(row, dict):
            raise ValueError(
                f"{path}: costs[{gold!r}] must be a mapping of pred -> cost"
            )
        if set(row) != set(labels):
            raise ValueError(
                f"{path}: costs[{gold!r}] columns {sorted(row)} must match the "
                f"gold labels {sorted(labels)} (square matrix required)"
            )
        parsed_row: dict[str, float] = {}
        for pred, value in row.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{path}: costs[{gold!r}][{pred!r}] must be numeric, got {value!r}"
                )
            parsed_row[pred] = float(value)
        costs[gold] = parsed_row

    if expected_labels is not None:
        expected = set(expected_labels)
        if set(costs) != expected:
            raise ValueError(
                f"{path}: cost matrix labels {sorted(costs)} must match the active "
                f"axis {sorted(expected)}"
            )

    version = data.get("version", 0)
    if not isinstance(version, int):
        raise ValueError(f"{path}: 'version' must be an integer, got {version!r}")
    return CostMatrix(costs, version)


def compute_weighted_error(
    confusion: list[list[int]], labels: list[str], matrix: CostMatrix
) -> float:
    """Return Σ confusion[pred][gold] * cost[gold][pred] for one run.

    ``confusion`` is indexed ``confusion[pred_idx][gold_idx]`` against ``labels``
    (the orientation ``compute_categorical_metrics`` records). Every label the run
    scored must be priced by the matrix; a missing cell is schema drift, not a
    free zero, so it raises rather than silently under-counting the penalty.
    """
    if not isinstance(labels, list) or not labels:
        raise ValueError("weighted_error requires a non-empty labels list")
    missing = [label for label in labels if label not in matrix.costs]
    if missing:
        raise ValueError(
            f"cost matrix does not price run labels {missing}; "
            f"matrix covers {sorted(matrix.costs)}"
        )
    if len(confusion) != len(labels) or any(
        not isinstance(row, list) or len(row) != len(labels) for row in confusion
    ):
        raise ValueError(
            f"confusion must be a {len(labels)}x{len(labels)} matrix matching labels"
        )

    total = 0.0
    for pred_idx, pred_label in enumerate(labels):
        for gold_idx, gold_label in enumerate(labels):
            count = confusion[pred_idx][gold_idx]
            if count:
                total += count * matrix.cost(gold_label, pred_label)
    return total


def weighted_error_for_run(run: dict[str, Any], matrix: CostMatrix) -> float:
    """Compute weighted_error from a run's stored confusion + labels.

    Fails loud on a missing confusion/labels block (schema drift) and — via
    ``compute_weighted_error`` — on any run label the matrix doesn't price. The
    active axis is a fixed 3-way (remote/hybrid/onsite), so an unpriced label is a
    real mismatch to surface, not a case to silently skip.
    """
    metrics = run.get("metrics") or {}
    confusion = metrics.get("confusion")
    labels = metrics.get("labels")
    if not isinstance(confusion, list) or not isinstance(labels, list):
        raise ValueError(
            f"run {run.get('run_id', '')!r} lacks a confusion/labels block required "
            "for weighted_error"
        )
    return compute_weighted_error(confusion, labels, matrix)
