"""Eval metrics — binary confusion for remote_filter, ordinal + top-k for skills_fit."""


def compute_metrics(tp: int, fp: int, tn: int, fn: int, skipped: int) -> dict:
    evaluated = tp + fp + tn + fn
    total = evaluated + skipped
    prevalence = (tp + fn) / evaluated if evaluated else 0.0
    accuracy = (tp + tn) / evaluated if evaluated else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "metrics": {
            "evaluated": evaluated,
            "skipped": skipped,
            "total": total,
            "prevalence": prevalence,
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    }


# ---------------------------------------------------------------------------
# Categorical metrics (generic labeled confusion)
# ---------------------------------------------------------------------------


def compute_categorical_metrics(
    preds: list[str],
    golds: list[str],
    labels: list[str],
    *,
    skipped: int = 0,
) -> dict:
    """Labeled categorical confusion + per-class metrics.

    The confusion matrix is indexed as ``confusion[pred_idx][gold_idx]``, where
    indexes correspond to the caller-provided ``labels`` list. Predictions and
    gold labels must be members of that closed label set; unknown values raise
    ``ValueError`` instead of being dropped because they indicate upstream schema
    drift or bad eval data.
    """
    if len(preds) != len(golds):
        raise ValueError(f"preds ({len(preds)}) and golds ({len(golds)}) must align")

    if len(set(labels)) != len(labels):
        raise ValueError("labels must be unique")

    n = len(preds)
    label_indexes = {label: i for i, label in enumerate(labels)}
    confusion = [[0] * len(labels) for _ in labels]

    for row_num, (pred, gold) in enumerate(zip(preds, golds), start=1):
        try:
            pred_idx = label_indexes[pred]
        except KeyError as exc:
            raise ValueError(
                f"pred at position {row_num} has unknown label {pred!r}"
            ) from exc
        try:
            gold_idx = label_indexes[gold]
        except KeyError as exc:
            raise ValueError(
                f"gold at position {row_num} has unknown label {gold!r}"
            ) from exc
        confusion[pred_idx][gold_idx] += 1

    per_class = {}
    for idx, label in enumerate(labels):
        true_positive = confusion[idx][idx]
        predicted_count = sum(confusion[idx])
        support = sum(row[idx] for row in confusion)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    label_count = len(labels)
    macro_precision = (
        sum(metrics["precision"] for metrics in per_class.values()) / label_count
        if label_count
        else 0.0
    )
    macro_recall = (
        sum(metrics["recall"] for metrics in per_class.values()) / label_count
        if label_count
        else 0.0
    )
    macro_f1 = (
        sum(metrics["f1"] for metrics in per_class.values()) / label_count
        if label_count
        else 0.0
    )
    micro_accuracy = sum(confusion[i][i] for i in range(label_count)) / n if n else 0.0

    return {
        "metrics": {
            "labels": list(labels),
            "evaluated": n,
            "skipped": skipped,
            "total": n + skipped,
            "confusion": confusion,
            "per_class": per_class,
            "macro_precision": macro_precision,
            "macro_recall": macro_recall,
            "macro_f1": macro_f1,
            "micro_accuracy": micro_accuracy,
        }
    }


# ---------------------------------------------------------------------------
# Ordinal metrics (skills_fit)
# ---------------------------------------------------------------------------


def compute_ordinal_metrics(
    preds: list[int],
    golds: list[int],
    *,
    skipped: int = 0,
    positive_threshold: int = 4,
    record_ids: list[str] | None = None,
) -> dict:
    """Ordinal-agreement + top-of-list metrics for skills_fit eval.

    Both metric families matter: ordinal agreement (Spearman, MAE) measures
    per-record rank fidelity; top-of-list metrics (precision_at_k) measure
    whether the dispatcher's actual shortlist would be worth applying to.
    See specs/skills_fit_agent_plan.md "Metrics" section.

    Args:
        preds: Predicted fit scores 1-5, one per evaluated record.
        golds: Gold/human fit scores 1-5, aligned with preds.
        skipped: Records dropped before scoring (parse errors, missing inputs).
        positive_threshold: Min gold score considered "good" for precision_at_k.
    """
    if len(preds) != len(golds):
        raise ValueError(f"preds ({len(preds)}) and golds ({len(golds)}) must align")

    n = len(preds)
    evaluated = n
    total = evaluated + skipped

    if n == 0:
        return {
            "metrics": {
                "evaluated": 0,
                "skipped": skipped,
                "total": total,
                "positive_threshold": positive_threshold,
                "exact_match_acc": 0.0,
                "off_by_one_acc": 0.0,
                "mae": 0.0,
                "bias": 0.0,
                "spearman_rho": 0.0,
                "confusion_5x5": _empty_confusion_5x5(),
                "precision_at_5": 0.0,
                "precision_at_10": 0.0,
                "mean_gold_score_at_top_10": 0.0,
                "top_bucket_purity": 0.0,
            }
        }

    deltas = [p - g for p, g in zip(preds, golds)]
    exact = sum(1 for d in deltas if d == 0) / n
    off_by_one = sum(1 for d in deltas if abs(d) <= 1) / n
    mae = sum(abs(d) for d in deltas) / n
    bias = sum(deltas) / n
    rho = _spearman(preds, golds)
    confusion = _build_confusion_5x5(preds, golds)

    ids = record_ids if record_ids is not None else [str(i) for i in range(n)]
    ranked = sorted(zip(preds, golds, ids), key=lambda t: (-t[0], t[2]))
    precision_at_5 = _precision_at_k(ranked, 5, positive_threshold)
    precision_at_10 = _precision_at_k(ranked, 10, positive_threshold)
    mean_gold_at_10 = _mean_gold_at_k(ranked, 10)

    pred_5s = [(p, g) for p, g in zip(preds, golds) if p == 5]
    top_bucket_purity = (
        sum(1 for _, g in pred_5s if g >= positive_threshold) / len(pred_5s)
        if pred_5s
        else 0.0
    )

    return {
        "metrics": {
            "evaluated": evaluated,
            "skipped": skipped,
            "total": total,
            "positive_threshold": positive_threshold,
            "exact_match_acc": exact,
            "off_by_one_acc": off_by_one,
            "mae": mae,
            "bias": bias,
            "spearman_rho": rho,
            "confusion_5x5": confusion,
            "precision_at_5": precision_at_5,
            "precision_at_10": precision_at_10,
            "mean_gold_score_at_top_10": mean_gold_at_10,
            "top_bucket_purity": top_bucket_purity,
        }
    }


def _precision_at_k(
    ranked: list[tuple[int, int, str]], k: int, positive_threshold: int
) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for _, g, _ in top if g >= positive_threshold) / len(top)


def _mean_gold_at_k(ranked: list[tuple[int, int, str]], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(g for _, g, _ in top) / len(top)


def _spearman(preds: list[int], golds: list[int]) -> float:
    """Spearman rank correlation. Tied values get average rank.

    Returns 0.0 when either input has zero rank variance (e.g., all preds equal).
    """
    if len(preds) < 2:
        return 0.0
    pred_ranks = _average_ranks(preds)
    gold_ranks = _average_ranks(golds)
    n = len(preds)
    mean_p = sum(pred_ranks) / n
    mean_g = sum(gold_ranks) / n
    cov = sum((p - mean_p) * (g - mean_g) for p, g in zip(pred_ranks, gold_ranks))
    var_p = sum((p - mean_p) ** 2 for p in pred_ranks)
    var_g = sum((g - mean_g) ** 2 for g in gold_ranks)
    denom = (var_p * var_g) ** 0.5
    if denom == 0:
        return 0.0
    return cov / denom


def _average_ranks(values: list[int]) -> list[float]:
    """1-indexed ranks; tied values share the mean of their positions."""
    indexed = sorted(enumerate(values), key=lambda iv: iv[1])
    ranks: list[float] = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + j) / 2 + 1  # mean of 1-indexed ranks (i+1)..(j+1)
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def _build_confusion_5x5(preds: list[int], golds: list[int]) -> list[list[int]]:
    """confusion[pred_idx][gold_idx] where idx 0-4 = scores 1-5."""
    confusion = _empty_confusion_5x5()
    for p, g in zip(preds, golds):
        if 1 <= p <= 5 and 1 <= g <= 5:
            confusion[p - 1][g - 1] += 1
    return confusion


def _empty_confusion_5x5() -> list[list[int]]:
    return [[0] * 5 for _ in range(5)]
