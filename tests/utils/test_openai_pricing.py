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


def test_gpt_5_4_mini_priced() -> None:
    # Primary scoring model (#475): a null estimate is the bug — assert a
    # concrete non-null breakdown at the documented standard rates.
    # 1000 uncached input @ $0.75/M = $0.00075
    # 500 cached input   @ $0.075/M = $0.0000375
    # 200 output         @ $4.50/M  = $0.0009
    result = estimate_cost(
        "gpt-5.4-mini",
        input_tokens=1500,
        cached_input_tokens=500,
        output_tokens=200,
    )
    assert result is not None
    assert result["input_uncached"] == pytest.approx(0.00075, rel=1e-4)
    assert result["input_cached"] == pytest.approx(0.0000375, rel=1e-4)
    assert result["output"] == pytest.approx(0.0009, rel=1e-4)
    assert result["total"] == pytest.approx(0.0016875, rel=1e-4)


def test_gpt_5_4_mini_batch_is_half_standard() -> None:
    # The issue relies on batch == 50% of standard (no batch-specific entry).
    standard = estimate_cost(
        "gpt-5.4-mini",
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=200,
        batch=False,
    )
    batch = estimate_cost(
        "gpt-5.4-mini",
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=200,
        batch=True,
    )
    assert standard is not None and batch is not None
    assert batch["total"] == pytest.approx(standard["total"] * 0.5, rel=1e-4)


@pytest.mark.parametrize(
    ("model", "expected_total"),
    [
        ("gpt-4.1-nano", 0.0001425),
        ("gpt-5.4-nano", 0.00036),
        ("gpt-5.6-luna", 0.00175),
        ("gpt-5.6-terra", 0.004375),
    ],
)
def test_bakeoff_candidate_models_are_priced(model: str, expected_total: float) -> None:
    # 1000 input with 500 cached + 200 output at standard short-context rates.
    result = estimate_cost(
        model,
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
    )
    assert result is not None
    assert result["total"] == pytest.approx(expected_total, rel=1e-4)


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
