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
