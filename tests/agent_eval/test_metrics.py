"""Tests for compute_metrics() — all pure functions, no I/O."""

import pytest


# ---------------------------------------------------------------------------
# Accuracy — must use `evaluated`, not `total` (SC-2)
# ---------------------------------------------------------------------------


def test_accuracy_denominator_is_evaluated_not_total():
    # Skipped records must not deflate accuracy
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=9, fp=1, tn=36, fn=2, skipped=2)
    # evaluated = 48, total = 50 — accuracy over evaluated only
    assert m["metrics"]["evaluated"] == 48
    assert m["metrics"]["total"] == 50
    assert m["metrics"]["accuracy"] == pytest.approx(45 / 48)



def test_perfect_classifier():
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=10, fp=0, tn=40, fn=0, skipped=0)
    assert m["metrics"]["accuracy"] == pytest.approx(1.0)
    assert m["metrics"]["precision"] == pytest.approx(1.0)
    assert m["metrics"]["recall"] == pytest.approx(1.0)
    assert m["metrics"]["f1"] == pytest.approx(1.0)



def test_all_negative_correct():
    # No positive examples in set — tp=fn=0
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=0, fp=0, tn=50, fn=0, skipped=0)
    assert m["metrics"]["accuracy"] == pytest.approx(1.0)
    assert m["metrics"]["prevalence"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Zero-denominator guards
# ---------------------------------------------------------------------------



def test_precision_zero_denominator_returns_zero():
    # tp=0, fp=0 → precision denominator is zero
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=0, fp=0, tn=10, fn=5, skipped=0)
    assert m["metrics"]["precision"] == 0.0



def test_recall_zero_denominator_returns_zero():
    # tp=0, fn=0 → no positive examples
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=0, fp=2, tn=10, fn=0, skipped=0)
    assert m["metrics"]["recall"] == 0.0



def test_f1_zero_denominator_returns_zero():
    # precision=0 and recall=0 → f1 denominator is zero
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=0, fp=0, tn=10, fn=0, skipped=0)
    assert m["metrics"]["f1"] == 0.0



def test_evaluated_zero_raises_or_returns_zero():
    # No evaluated records at all — should not divide by zero
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=0, fp=0, tn=0, fn=0, skipped=5)
    assert m["metrics"]["evaluated"] == 0
    assert m["metrics"]["accuracy"] == 0.0


# ---------------------------------------------------------------------------
# Prevalence
# ---------------------------------------------------------------------------



def test_prevalence_is_positive_class_rate():
    # prevalence = (tp + fn) / evaluated
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=6, fp=2, tn=39, fn=1, skipped=2)
    assert m["metrics"]["prevalence"] == pytest.approx(7 / 48)


# ---------------------------------------------------------------------------
# Output schema — all required keys present
# ---------------------------------------------------------------------------



def test_output_contains_all_required_metric_keys():
    from agent_eval.metrics import compute_metrics
    m = compute_metrics(tp=5, fp=1, tn=40, fn=4, skipped=0)
    required = {"evaluated", "skipped", "total", "prevalence",
                "tp", "fp", "tn", "fn", "accuracy", "precision", "recall", "f1"}
    assert required.issubset(m["metrics"].keys())
