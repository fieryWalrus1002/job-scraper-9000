"""Generic simple-stat helpers for eval runs."""

from __future__ import annotations


P95_PERCENTILE = 95


def percentile(values: list[float], percentile_value: float) -> float | None:
    """Return the nearest-rank percentile value used by eval summaries."""
    if not values:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError(f"percentile must be between 0 and 100: {percentile_value}")
    sorted_values = sorted(values)
    index = round((percentile_value / 100) * (len(sorted_values) - 1))
    return sorted_values[index]


def latency_summary(elapsed_seconds: list[float]) -> dict[str, float | int | None]:
    """Summarize latency observations for eval run metrics."""
    n = len(elapsed_seconds)
    return {
        "latency_n": n,
        "latency_avg_s": sum(elapsed_seconds) / n if n else None,
        "latency_p95_s": percentile(elapsed_seconds, P95_PERCENTILE),
    }
