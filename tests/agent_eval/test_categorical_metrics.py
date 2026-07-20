"""Tests for compute_categorical_metrics() — pure functions, no I/O."""

import pytest

from agents.remote_filter.models import REMOTE_CLASSIFICATIONS
from agent_eval.metrics import compute_categorical_metrics


LABELS = REMOTE_CLASSIFICATIONS

# Explicit 4-label fixture for the generic-arithmetic tests below. It exercises
# the N-label confusion/averaging math independently of the production axis
# (now 3-way) — compute_categorical_metrics is label-agnostic.
FOUR_LABELS = ["remote", "hybrid", "onsite", "unclear"]


# ---------------------------------------------------------------------------
# Shape and edge cases
# ---------------------------------------------------------------------------


def test_categorical_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        compute_categorical_metrics(["remote", "hybrid"], ["remote"], LABELS)


def test_categorical_unknown_pred_label_raises():
    with pytest.raises(ValueError, match="unknown label"):
        compute_categorical_metrics(["office_only"], ["onsite"], LABELS)


def test_categorical_unknown_gold_label_raises():
    with pytest.raises(ValueError, match="unknown label"):
        compute_categorical_metrics(["onsite"], ["office_only"], LABELS)


def test_categorical_empty_inputs_return_zeros():
    m = compute_categorical_metrics([], [], LABELS, skipped=3)["metrics"]

    assert m["labels"] == LABELS
    assert m["evaluated"] == 0
    assert m["skipped"] == 3
    assert m["total"] == 3
    assert m["confusion"] == [[0] * len(LABELS) for _ in LABELS]
    assert m["micro_accuracy"] == 0.0
    assert m["macro_precision"] == 0.0
    assert m["macro_recall"] == 0.0
    assert m["macro_f1"] == 0.0
    assert set(m["per_class"]) == set(LABELS)
    for per_class in m["per_class"].values():
        assert per_class == {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "support": 0,
        }


# ---------------------------------------------------------------------------
# Categorical agreement and confusion matrix
# ---------------------------------------------------------------------------


def test_categorical_perfect_classifier():
    preds = ["remote", "hybrid", "onsite", "unclear"]
    golds = ["remote", "hybrid", "onsite", "unclear"]

    m = compute_categorical_metrics(preds, golds, FOUR_LABELS)["metrics"]

    assert m["evaluated"] == 4
    assert m["skipped"] == 0
    assert m["total"] == 4
    assert m["micro_accuracy"] == pytest.approx(1.0)
    assert m["macro_precision"] == pytest.approx(1.0)
    assert m["macro_recall"] == pytest.approx(1.0)
    assert m["macro_f1"] == pytest.approx(1.0)
    assert m["confusion"] == [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]
    for per_class in m["per_class"].values():
        assert per_class["precision"] == pytest.approx(1.0)
        assert per_class["recall"] == pytest.approx(1.0)
        assert per_class["f1"] == pytest.approx(1.0)
        assert per_class["support"] == 1


def test_categorical_known_confusion_arithmetic():
    # confusion[pred_idx][gold_idx], using labels remote/hybrid/onsite/unclear.
    preds = ["remote", "onsite", "remote", "hybrid", "onsite", "unclear"]
    golds = ["remote", "remote", "hybrid", "hybrid", "onsite", "remote"]

    m = compute_categorical_metrics(preds, golds, FOUR_LABELS)["metrics"]

    assert m["confusion"] == [
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [1, 0, 1, 0],
        [1, 0, 0, 0],
    ]
    assert m["micro_accuracy"] == pytest.approx(3 / 6)

    assert m["per_class"]["remote"]["support"] == 3
    assert m["per_class"]["remote"]["precision"] == pytest.approx(1 / 2)
    assert m["per_class"]["remote"]["recall"] == pytest.approx(1 / 3)
    assert m["per_class"]["remote"]["f1"] == pytest.approx(2 / 5)

    assert m["per_class"]["hybrid"]["support"] == 2
    assert m["per_class"]["hybrid"]["precision"] == pytest.approx(1.0)
    assert m["per_class"]["hybrid"]["recall"] == pytest.approx(1 / 2)
    assert m["per_class"]["hybrid"]["f1"] == pytest.approx(2 / 3)

    assert m["per_class"]["onsite"]["support"] == 1
    assert m["per_class"]["onsite"]["precision"] == pytest.approx(1 / 2)
    assert m["per_class"]["onsite"]["recall"] == pytest.approx(1.0)
    assert m["per_class"]["onsite"]["f1"] == pytest.approx(2 / 3)

    assert m["per_class"]["unclear"]["support"] == 0
    assert m["per_class"]["unclear"]["precision"] == pytest.approx(0.0)
    assert m["per_class"]["unclear"]["recall"] == pytest.approx(0.0)
    assert m["per_class"]["unclear"]["f1"] == pytest.approx(0.0)

    assert m["macro_precision"] == pytest.approx((1 / 2 + 1 + 1 / 2 + 0) / 4)
    assert m["macro_recall"] == pytest.approx((1 / 3 + 1 / 2 + 1 + 0) / 4)
    assert m["macro_f1"] == pytest.approx((2 / 5 + 2 / 3 + 2 / 3 + 0) / 4)


def test_categorical_skipped_flows_to_total_not_evaluated():
    m = compute_categorical_metrics(
        ["remote", "onsite"],
        ["remote", "remote"],
        LABELS,
        skipped=5,
    )["metrics"]

    assert m["evaluated"] == 2
    assert m["skipped"] == 5
    assert m["total"] == 7
    assert m["micro_accuracy"] == pytest.approx(1 / 2)
