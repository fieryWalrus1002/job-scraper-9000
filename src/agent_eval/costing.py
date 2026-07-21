"""Generic token-costing helpers for eval runs."""

from __future__ import annotations

from typing import Any

from utils.openai_pricing import estimate_cost

TOKEN_TOTAL_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")


def empty_token_totals() -> dict[str, int]:
    """Return the canonical zero/default token totals shape."""
    return {key: 0 for key in TOKEN_TOTAL_KEYS}


def add_token_totals(target: dict[str, int], usage: dict[str, int]) -> None:
    """Add one token-usage payload into ``target`` in-place.

    Missing/falsey values count as zero so provider-specific partial payloads can
    still aggregate into the canonical shape.
    """
    for key in TOKEN_TOTAL_KEYS:
        target[key] = target.get(key, 0) + int(usage.get(key, 0) or 0)


def aggregate_token_totals(usages: list[dict[str, int]]) -> dict[str, int]:
    """Aggregate many token-usage payloads into the canonical totals shape."""
    totals = empty_token_totals()
    for usage in usages:
        add_token_totals(totals, usage)
    return totals


def correct_count(metrics: dict[str, Any]) -> int:
    """Count exact matches from categorical confusion metrics."""
    confusion = metrics.get("confusion") or []
    if not isinstance(confusion, list):
        return int((metrics.get("micro_accuracy") or 0.0) * metrics.get("evaluated", 0))
    return sum(
        int(row[i])
        for i, row in enumerate(confusion)
        if isinstance(row, list) and i < len(row)
    )


def build_cost_summary(
    provider: str | None,
    model: str | None,
    metrics: dict[str, Any],
    token_totals: dict[str, int],
) -> dict[str, Any]:
    """Build an eval cost block from observed token usage and list pricing.

    ``provider``/``model`` must be the *resolved* values the run actually used
    (case-normalized here defensively), not raw config — otherwise a run that
    resolved provider/model from env or a default could be priced against the
    wrong string, or a real OpenAI run mislabeled as local zero-cost.
    """
    provider = (provider or "").lower()
    evaluated = int(metrics.get("evaluated") or 0)
    correct = correct_count(metrics)
    canonical_token_totals = aggregate_token_totals([token_totals])

    estimated_total: float | None
    breakdown: dict[str, float] | None
    pricing_note: str
    if provider == "openai" and model:
        breakdown = estimate_cost(model, batch=False, **canonical_token_totals)
        if breakdown is None:
            estimated_total = None
            pricing_note = "missing_openai_pricing_entry"
        else:
            estimated_total = breakdown["total"]
            pricing_note = "openai_list_price_estimate"
    else:
        # Local/ollama-compatible runs have no API invoice. Tokens may still be
        # present for observability, but estimated dollar cost is intentionally $0.
        breakdown = None
        estimated_total = 0.0
        pricing_note = "local_provider_zero_api_cost"

    return {
        "token_totals": canonical_token_totals,
        "estimated_cost_usd": estimated_total,
        "estimated_cost_per_record_usd": (
            estimated_total / evaluated
            if estimated_total is not None and evaluated
            else None
        ),
        "estimated_cost_per_correct_usd": (
            estimated_total / correct
            if estimated_total is not None and correct
            else None
        ),
        "correct": correct,
        "breakdown": breakdown,
        "pricing_note": pricing_note,
    }
