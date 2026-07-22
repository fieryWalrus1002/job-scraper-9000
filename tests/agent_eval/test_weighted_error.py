"""Tests for the remote_filter weighted-error metric (#545)."""

import pytest

from agent_eval.weighted_error import (
    DEFAULT_COST_MATRIX_PATH,
    CostMatrix,
    compute_weighted_error,
    load_cost_matrix,
    weighted_error_for_run,
)

LABELS = ["remote", "hybrid", "onsite"]


def _matrix() -> CostMatrix:
    return CostMatrix(
        {
            "remote": {"remote": 0.0, "hybrid": 2.0, "onsite": 3.0},
            "hybrid": {"remote": 1.0, "hybrid": 0.0, "onsite": 0.1},
            "onsite": {"remote": 1.0, "hybrid": 0.1, "onsite": 0.0},
        },
        version=1,
    )


def test_perfect_confusion_scores_zero() -> None:
    confusion = [[5, 0, 0], [0, 3, 0], [0, 0, 4]]
    assert compute_weighted_error(confusion, LABELS, _matrix()) == 0.0


def test_weighted_error_uses_gold_pred_orientation() -> None:
    # confusion[pred][gold]: 1 hybrid-gold predicted remote (cost[hybrid][remote]=1)
    # and 2 remote-gold predicted onsite (cost[remote][onsite]=3, the worst cell).
    confusion = [
        [5, 1, 0],  # pred=remote
        [0, 3, 0],  # pred=hybrid
        [2, 0, 4],  # pred=onsite
    ]
    # 1*1 (hybrid->remote) + 2*3 (remote->onsite) = 7.0
    assert compute_weighted_error(confusion, LABELS, _matrix()) == pytest.approx(7.0)


def test_remote_miss_costs_more_than_hybrid_onsite_swap() -> None:
    matrix = _matrix()
    remote_to_onsite = compute_weighted_error(
        [[0, 0, 0], [0, 0, 0], [1, 0, 0]], LABELS, matrix
    )
    hybrid_to_onsite = compute_weighted_error(
        [[0, 0, 0], [0, 0, 0], [0, 1, 0]], LABELS, matrix
    )
    assert remote_to_onsite > hybrid_to_onsite


def test_compute_fails_loud_on_non_square_confusion() -> None:
    with pytest.raises(ValueError, match="matching labels"):
        compute_weighted_error([[1, 0, 0], [0, 1, 0]], LABELS, _matrix())


def test_compute_fails_loud_on_unpriced_label() -> None:
    with pytest.raises(ValueError, match="does not price"):
        compute_weighted_error([[1]], ["unclear"], _matrix())


def test_cost_matrix_hash_is_order_independent() -> None:
    a = CostMatrix({"remote": {"remote": 0.0}, "onsite": {"onsite": 0.0}}, version=1)
    b = CostMatrix({"onsite": {"onsite": 0.0}, "remote": {"remote": 0.0}}, version=1)
    assert a.hash == b.hash


def test_cost_matrix_hash_changes_with_weights() -> None:
    base = _matrix()
    bumped = CostMatrix(
        {**base.costs, "remote": {"remote": 0.0, "hybrid": 2.0, "onsite": 99.0}}, 1
    )
    assert base.hash != bumped.hash


def test_shipped_config_loads_and_prices_active_axis() -> None:
    matrix = load_cost_matrix(DEFAULT_COST_MATRIX_PATH)
    assert set(matrix.costs) == set(LABELS)
    # The remote-miss cells are the most expensive; diagonal is free.
    assert matrix.cost("remote", "onsite") > matrix.cost("hybrid", "onsite")
    assert matrix.cost("remote", "remote") == 0.0
    assert matrix.hash.startswith("sha256:")


def test_load_rejects_non_square_matrix(tmp_path) -> None:
    path = tmp_path / "costs.yml"
    path.write_text("costs:\n  remote: {remote: 0, onsite: 1}\n  onsite: {onsite: 0}\n")
    with pytest.raises(ValueError, match="square matrix required"):
        load_cost_matrix(path)


def test_load_rejects_non_numeric_cell(tmp_path) -> None:
    path = tmp_path / "costs.yml"
    path.write_text("costs:\n  remote: {remote: free}\n")
    with pytest.raises(ValueError, match="must be numeric"):
        load_cost_matrix(path)


def test_run_from_stored_confusion() -> None:
    run = {
        "run_id": "r1",
        "metrics": {
            "labels": LABELS,
            "confusion": [[5, 0, 0], [0, 3, 0], [1, 0, 2]],
        },
    }
    # Sole error: 1 remote-gold predicted onsite -> cost[remote][onsite] = 3.0.
    assert weighted_error_for_run(run, _matrix()) == pytest.approx(3.0)


def test_run_fails_loud_on_unpriced_label() -> None:
    run = {
        "run_id": "legacy",
        "metrics": {
            "labels": ["remote", "hybrid", "onsite", "unclear"],
            "confusion": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        },
    }
    with pytest.raises(ValueError, match="does not price"):
        weighted_error_for_run(run, _matrix())


def test_run_fails_loud_on_missing_confusion() -> None:
    run = {"run_id": "broken", "metrics": {"labels": LABELS}}
    with pytest.raises(ValueError, match="confusion/labels block"):
        weighted_error_for_run(run, _matrix())
