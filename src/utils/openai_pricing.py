"""OpenAI per-model list pricing in USD per 1M tokens.

Used to estimate cost from observed token counts at the time of a run.
Update as OpenAI pricing changes. Authoritative source:
https://openai.com/api/pricing/

Note: Batch API gets 50% off both input and output. Pricing here is the
standard non-batch rate; callers pass ``batch=True`` to apply the discount.
"""

from __future__ import annotations

# (input_per_1m, cached_input_per_1m, output_per_1m)
PRICING_USD_PER_1M: dict[str, tuple[float, float, float]] = {
    # gpt-4o family
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o-2024-08-06": (2.50, 1.25, 10.00),
}


BATCH_DISCOUNT = 0.5  # 50% off both sides when using OpenAI Batch API


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    batch: bool = False,
) -> dict[str, float] | None:
    """Estimate USD cost from token counts.

    Returns a dict with keys ``input_uncached``, ``input_cached``, ``output``,
    and ``total``. Returns ``None`` if the model is not in the pricing table —
    callers should treat that as "estimated cost unknown" rather than $0.
    """
    if model not in PRICING_USD_PER_1M:
        return None
    in_rate, in_cached_rate, out_rate = PRICING_USD_PER_1M[model]
    if batch:
        in_rate *= BATCH_DISCOUNT
        in_cached_rate *= BATCH_DISCOUNT
        out_rate *= BATCH_DISCOUNT

    uncached_input = max(input_tokens - cached_input_tokens, 0)
    breakdown = {
        "input_uncached": round(uncached_input * in_rate / 1_000_000, 8),
        "input_cached": round(cached_input_tokens * in_cached_rate / 1_000_000, 8),
        "output": round(output_tokens * out_rate / 1_000_000, 8),
    }
    breakdown["total"] = round(sum(breakdown.values()), 8)
    return breakdown
