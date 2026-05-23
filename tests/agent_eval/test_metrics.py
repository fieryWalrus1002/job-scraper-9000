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
    required = {
        "evaluated",
        "skipped",
        "total",
        "prevalence",
        "tp",
        "fp",
        "tn",
        "fn",
        "accuracy",
        "precision",
        "recall",
        "f1",
    }
    assert required.issubset(m["metrics"].keys())


# ---------------------------------------------------------------------------
# Ordinal metrics — tie-breaking stability (issue #40)
# ---------------------------------------------------------------------------


def test_precision_at_5_is_input_order_invariant_with_more_ties_than_k():
    """precision@5 must be stable across input orderings when >k records tie on pred.

    Without tie-breaking, Python's stable sort preserves input order, so top-5
    of a reversed input contains different records than top-5 of the forward
    input — and the metric changes.
    """
    from agent_eval.metrics import compute_ordinal_metrics

    # 6 records all pred=4. Goods (gold>=4) at "a", "b", "c"; rest are 2s.
    # Without tie-break:
    #   forward top-5 = {a,b,c,d,e} → 3 goods → 0.6
    #   reverse top-5 = {f,e,d,c,b} → 2 goods (c,b) → 0.4
    # With ID-sort tie-break: top-5 is always {a..e} → 3 goods → 0.6 either way.
    preds = [4, 4, 4, 4, 4, 4]
    golds = [4, 4, 4, 2, 2, 2]
    ids = ["a", "b", "c", "d", "e", "f"]

    m_forward = compute_ordinal_metrics(preds, golds, record_ids=ids)
    m_reverse = compute_ordinal_metrics(preds[::-1], golds[::-1], record_ids=ids[::-1])

    assert (
        m_forward["metrics"]["precision_at_5"] == m_reverse["metrics"]["precision_at_5"]
    )
    assert m_forward["metrics"]["precision_at_5"] == pytest.approx(3 / 5)


def test_precision_at_10_is_input_order_invariant_with_more_ties_than_k():
    """Same property for k=10 — needs >10 tied records to exercise."""
    from agent_eval.metrics import compute_ordinal_metrics

    # 12 records all pred=4. Goods at ids "a"–"e" (5 of the first 10).
    # Without tie-break:
    #   forward top-10 = {a..j} → 5 goods → 0.5
    #   reverse top-10 = {l..c} → 3 goods (e,d,c) → 0.3
    # With ID-sort: top-10 = {a..j} regardless → 0.5 either way.
    n = 12
    preds = [4] * n
    ids = [chr(ord("a") + i) for i in range(n)]  # a..l
    golds = [4, 4, 4, 4, 4, 2, 2, 2, 2, 2, 2, 2]

    m_forward = compute_ordinal_metrics(preds, golds, record_ids=ids)
    m_reverse = compute_ordinal_metrics(preds[::-1], golds[::-1], record_ids=ids[::-1])

    assert (
        m_forward["metrics"]["precision_at_10"]
        == m_reverse["metrics"]["precision_at_10"]
    )
    assert m_forward["metrics"]["precision_at_10"] == pytest.approx(5 / 10)


def test_mean_gold_at_top_10_is_input_order_invariant_with_more_ties_than_k():
    """mean_gold_at_top_10 also depends on which records land in top-10."""
    from agent_eval.metrics import compute_ordinal_metrics

    # 12 records all pred=4. Last two (k, l) have higher gold than the rest.
    # Without tie-break:
    #   forward top-10 = {a..j} all gold=3 → mean = 3.0
    #   reverse top-10 = {l..c} includes k,l with gold=5 → mean = (5+5+8*3)/10 = 3.4
    # With ID-sort: top-10 = {a..j} regardless → mean = 3.0 either way.
    n = 12
    preds = [4] * n
    ids = [chr(ord("a") + i) for i in range(n)]
    golds = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 5, 5]

    m_forward = compute_ordinal_metrics(preds, golds, record_ids=ids)
    m_reverse = compute_ordinal_metrics(preds[::-1], golds[::-1], record_ids=ids[::-1])
    assert (
        m_forward["metrics"]["mean_gold_score_at_top_10"]
        == m_reverse["metrics"]["mean_gold_score_at_top_10"]
    )
    assert m_forward["metrics"]["mean_gold_score_at_top_10"] == pytest.approx(3.0)
