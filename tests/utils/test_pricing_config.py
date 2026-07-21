"""Guard: every OpenAI model referenced in config must have a price.

This is the teeth behind #475/#476 — it turns "a model swap silently nulls
cost.estimated_total" into a red build. It scans the agent/CI configs, filters to
``provider: openai`` (local/ollama models have no list price and are skipped), and
asserts each model exists in config/pricing/openai.yml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from utils.openai_pricing import PricingConfig, load_prices

REPO_ROOT = Path(__file__).parents[2]
# Configs that carry an `llm.provider` / `llm.model` block.
_CONFIG_GLOBS = ("config/agent/*.yml", "config/ci/*.yml")


def _configured_openai_models() -> dict[str, list[str]]:
    """Map each OpenAI model referenced in config -> every file that declares it.

    A model can appear in several configs (gpt-5.4-mini is in skills_fit,
    remote_agent, and ai_code_review today), so collect all paths — a missing
    price should report every affected file, not just the last one seen.
    """
    found: dict[str, list[str]] = {}
    for pattern in _CONFIG_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            raw = yaml.safe_load(path.read_text()) or {}
            llm = raw.get("llm") or {}
            if llm.get("provider") == "openai" and (model := llm.get("model")):
                found.setdefault(model, []).append(str(path.relative_to(REPO_ROOT)))
    return found


def test_pricing_config_is_valid() -> None:
    # Fail fast + loud if the pricing YAML is malformed (extra keys, negative
    # rate, missing field) rather than at first estimate_cost() call in a run.
    raw = yaml.safe_load((REPO_ROOT / "config/pricing/openai.yml").read_text())
    PricingConfig.model_validate(raw)


def test_prices_are_immutable_and_copied() -> None:
    # The table is lru_cached; a caller must not be able to corrupt it. Rates are
    # frozen, and load_prices() hands back an independent dict each call.
    prices = load_prices()
    model = next(iter(prices))
    with pytest.raises(ValidationError):
        prices[model].input = 999.0  # frozen model
    del prices[model]
    assert model in load_prices()  # deletion didn't touch the cached table


def test_every_configured_openai_model_is_priced() -> None:
    priced = load_prices()
    configured = _configured_openai_models()
    assert configured, "expected at least one OpenAI-provider agent config"

    missing = {
        model: paths for model, paths in configured.items() if model not in priced
    }
    assert not missing, (
        "OpenAI models referenced in config but missing from "
        f"config/pricing/openai.yml: {missing}. Add their rates (see "
        "https://developers.openai.com/api/docs/pricing) or cost estimates "
        "will be null for those runs."
    )
