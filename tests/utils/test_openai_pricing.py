import pytest

from utils.openai_pricing import estimate_cost


def test_gpt_4o_mini_no_cache() -> None:
    # 1000 input @ $0.15/M = $0.00015
    # 200 output @ $0.60/M = $0.00012
    result = estimate_cost(
        "gpt-4o-mini",
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=200,
    )
    assert result is not None
    assert result["input_uncached"] == pytest.approx(0.00015, rel=1e-4)
    assert result["input_cached"] == 0.0
    assert result["output"] == pytest.approx(0.00012, rel=1e-4)
    assert result["total"] == pytest.approx(0.00027, rel=1e-4)


def test_cached_input_discounted_50_percent() -> None:
    # 500 cached @ $0.075/M = $0.0000375
    # 500 uncached @ $0.15/M = $0.000075
    result = estimate_cost(
        "gpt-4o-mini",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=0,
    )
    assert result is not None
    assert result["input_uncached"] == pytest.approx(0.000075, rel=1e-4)
    assert result["input_cached"] == pytest.approx(0.0000375, rel=1e-4)


def test_batch_applies_50_percent_discount() -> None:
    standard = estimate_cost(
        "gpt-4o-mini",
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=200,
        batch=False,
    )
    batch = estimate_cost(
        "gpt-4o-mini",
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=200,
        batch=True,
    )
    assert standard is not None and batch is not None
    assert batch["total"] == pytest.approx(standard["total"] * 0.5, rel=1e-4)


def test_unknown_model_returns_none() -> None:
    assert (
        estimate_cost(
            "gpt-imaginary",
            input_tokens=100,
            cached_input_tokens=0,
            output_tokens=10,
        )
        is None
    )


def test_today_remote_filter_run_approximation() -> None:
    """Sanity check: 1.13M input (533K cached) + 133K output ≈ $0.21."""
    result = estimate_cost(
        "gpt-4o-mini",
        input_tokens=1_130_000,
        cached_input_tokens=533_000,
        output_tokens=133_000,
    )
    assert result is not None
    # Allow ~5% tolerance for rounding
    assert result["total"] == pytest.approx(0.21, rel=0.1)
