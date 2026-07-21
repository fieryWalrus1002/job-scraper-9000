"""OpenAI per-model list pricing in USD per 1M tokens.

Used to estimate cost from observed token counts at the time of a run. Pricing is
non-secret reference data that changes on OpenAI's cadence, not ours, so it lives
in ``config/pricing/openai.yml`` (per CLAUDE.md: non-secret config in YAML) rather
than hardcoded here. Update the YAML when pricing changes; authoritative source:
https://developers.openai.com/api/docs/pricing

Note: Batch API gets 50% off both input and output. The YAML holds the standard
non-batch rate; callers pass ``batch=True`` to apply the discount.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_PRICING_PATH = Path(__file__).parents[2] / "config" / "pricing" / "openai.yml"

BATCH_DISCOUNT = 0.5  # 50% off both sides when using OpenAI Batch API


class ModelPrice(BaseModel):
    """Per-model list rates, USD per 1M tokens (standard, non-batch tier)."""

    model_config = ConfigDict(extra="forbid")

    input: float = Field(ge=0)
    cached_input: float = Field(ge=0)
    output: float = Field(ge=0)


class PricingConfig(BaseModel):
    """Validated shape of config/pricing/openai.yml."""

    model_config = ConfigDict(extra="forbid")

    source: str
    fetched_at: str
    models: dict[str, ModelPrice]


@lru_cache(maxsize=1)
def _load_pricing() -> PricingConfig:
    """Load + validate the pricing table once. Fail fast on malformed config."""
    raw = yaml.safe_load(_PRICING_PATH.read_text())
    return PricingConfig.model_validate(raw)


def load_prices() -> dict[str, ModelPrice]:
    """All known model prices, keyed by model id (as used in config/agent/*.yml)."""
    return _load_pricing().models


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
    callers should treat that as "estimated cost unknown" rather than $0. (The
    pricing guard test keeps configured OpenAI models from reaching this path
    unpriced; runtime stays fail-safe so a pricing gap never crashes a run.)
    """
    prices = load_prices()
    if model not in prices:
        return None
    price = prices[model]
    in_rate, in_cached_rate, out_rate = price.input, price.cached_input, price.output
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
