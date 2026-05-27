"""Tests for compute_ordinal_metrics() — pure functions, no I/O."""

import pytest

from agent_eval.metrics import compute_ordinal_metrics


# ---------------------------------------------------------------------------
# Shape and edge cases
# ---------------------------------------------------------------------------


def test_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        compute_ordinal_metrics([1, 2, 3], [1, 2])


def test_empty_inputs_return_zeros():
    m = compute_ordinal_metrics([], [], skipped=3)["metrics"]
    assert m["evaluated"] == 0
    assert m["skipped"] == 3
    assert m["total"] == 3
    assert m["spearman_rho"] == 0.0
    assert m["confusion_5x5"] == [[0] * 5 for _ in range(5)]


def test_output_contains_all_required_keys():
    m = compute_ordinal_metrics([3, 4, 5], [3, 4, 5])["metrics"]
    required = {
        "evaluated",
        "skipped",
        "total",
        "positive_threshold",
        "exact_match_acc",
        "off_by_one_acc",
        "mae",
        "bias",
        "spearman_rho",
        "confusion_5x5",
        "precision_at_5",
        "precision_at_10",
        "mean_gold_score_at_top_10",
        "top_bucket_purity",
    }
    assert required.issubset(m.keys())


# ---------------------------------------------------------------------------
# Ordinal agreement
# ---------------------------------------------------------------------------


def test_perfect_agreement():
    preds = [1, 2, 3, 4, 5]
    golds = [1, 2, 3, 4, 5]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["exact_match_acc"] == pytest.approx(1.0)
    assert m["off_by_one_acc"] == pytest.approx(1.0)
    assert m["mae"] == pytest.approx(0.0)
    assert m["bias"] == pytest.approx(0.0)
    assert m["spearman_rho"] == pytest.approx(1.0)


def test_all_off_by_one_high():
    # Model scores everything one band higher than human
    preds = [2, 3, 4, 5, 5]
    golds = [1, 2, 3, 4, 5]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["exact_match_acc"] == pytest.approx(1 / 5)  # the last pair (5,5)
    assert m["off_by_one_acc"] == pytest.approx(1.0)
    assert m["mae"] == pytest.approx(4 / 5)
    assert m["bias"] == pytest.approx(4 / 5)


def test_all_off_by_one_low():
    # Model scores everything one band lower than human → negative bias
    preds = [1, 2, 3, 4]
    golds = [2, 3, 4, 5]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["bias"] == pytest.approx(-1.0)
    assert m["mae"] == pytest.approx(1.0)
    assert m["off_by_one_acc"] == pytest.approx(1.0)


def test_reverse_rank_gives_negative_spearman():
    preds = [5, 4, 3, 2, 1]
    golds = [1, 2, 3, 4, 5]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["spearman_rho"] == pytest.approx(-1.0)


def test_zero_variance_preds_returns_zero_spearman():
    # All preds same value → no rank variance → no correlation
    preds = [3, 3, 3, 3]
    golds = [1, 2, 4, 5]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["spearman_rho"] == 0.0


# ---------------------------------------------------------------------------
# Confusion matrix
# ---------------------------------------------------------------------------


def test_confusion_5x5_diagonal_for_perfect_agreement():
    preds = [1, 2, 3, 4, 5]
    golds = [1, 2, 3, 4, 5]
    confusion = compute_ordinal_metrics(preds, golds)["metrics"]["confusion_5x5"]
    for i in range(5):
        for j in range(5):
            expected = 1 if i == j else 0
            assert confusion[i][j] == expected, (
                f"confusion[{i}][{j}] expected {expected}"
            )


def test_confusion_indexes_correctly():
    # pred=2, gold=4 → confusion[1][3] increments
    preds = [2, 2]
    golds = [4, 4]
    confusion = compute_ordinal_metrics(preds, golds)["metrics"]["confusion_5x5"]
    assert confusion[1][3] == 2
    # Everything else zero
    total = sum(sum(row) for row in confusion)
    assert total == 2


# ---------------------------------------------------------------------------
# Top-of-list metrics
# ---------------------------------------------------------------------------


def test_precision_at_5_perfect_when_top_5_all_gold_high():
    # Top-5 pred (all 5s) all have gold >= 4 → precision_at_5 = 1.0
    preds = [5, 5, 5, 5, 5, 2, 1, 1]
    golds = [5, 4, 4, 5, 4, 1, 1, 1]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["precision_at_5"] == pytest.approx(1.0)


def test_precision_at_5_when_top_5_has_one_dud():
    # One of top-5 is a gold=2 (a "deceptive 5")
    preds = [5, 5, 5, 5, 5, 2, 2]
    golds = [5, 4, 4, 5, 2, 1, 1]  # last pred-5 has gold=2
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["precision_at_5"] == pytest.approx(4 / 5)


def test_precision_at_5_handles_fewer_than_5_records():
    # Only 3 records — precision_at_5 uses what's available
    preds = [5, 5, 5]
    golds = [5, 5, 4]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["precision_at_5"] == pytest.approx(1.0)


def test_mean_gold_score_at_top_10_uses_pred_ranking():
    preds = [5, 4, 3, 2, 1, 5, 4]
    golds = [5, 4, 3, 2, 1, 3, 5]
    # Top-7 by pred: same as input. mean of golds = (5+4+3+2+1+3+5)/7
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["mean_gold_score_at_top_10"] == pytest.approx(23 / 7)


def test_top_bucket_purity_only_counts_pred_5s():
    # 3 pred=5: 2 have gold>=4, 1 has gold=2 → purity 2/3
    preds = [5, 5, 5, 4, 3]
    golds = [5, 4, 2, 4, 3]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["top_bucket_purity"] == pytest.approx(2 / 3)


def test_top_bucket_purity_zero_when_no_pred_5s():
    preds = [4, 4, 3, 2]
    golds = [5, 5, 5, 5]
    m = compute_ordinal_metrics(preds, golds)["metrics"]
    assert m["top_bucket_purity"] == 0.0


# ---------------------------------------------------------------------------
# Custom positive_threshold
# ---------------------------------------------------------------------------


def test_positive_threshold_is_configurable():
    preds = [5, 5, 5]
    golds = [3, 3, 5]  # gold=5 passes any threshold; gold=3 passes only at 3
    m_at_4 = compute_ordinal_metrics(preds, golds, positive_threshold=4)["metrics"]
    m_at_3 = compute_ordinal_metrics(preds, golds, positive_threshold=3)["metrics"]
    assert m_at_4["precision_at_5"] == pytest.approx(1 / 3)
    assert m_at_3["precision_at_5"] == pytest.approx(1.0)
    assert m_at_4["positive_threshold"] == 4
    assert m_at_3["positive_threshold"] == 3
