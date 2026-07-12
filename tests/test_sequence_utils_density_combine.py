import math
import random

import pytest

import subsequence.sequence_utils


C = subsequence.sequence_utils.combine_densities
S = subsequence.sequence_utils.warp_stack
W = subsequence.sequence_utils.density_warp
TOL = 1e-9


# --- combine_densities ---
# Reference layer set [0.2, 0.5, 0.8]: product 0.08, geomean 0.08**(1/3),
# mean 0.5, min 0.2.


def test_combine_default_is_geomean() -> None:
    """No strategy given uses the geometric mean."""

    assert abs(C([0.2, 0.5, 0.8]) - (0.08 ** (1.0 / 3.0))) < TOL


def test_combine_product() -> None:
    """product multiplies all layers."""

    assert abs(C([0.2, 0.5, 0.8], "product") - 0.08) < TOL


def test_combine_mean() -> None:
    """mean is the arithmetic average."""

    assert abs(C([0.2, 0.5, 0.8], "mean") - 0.5) < TOL


def test_combine_min() -> None:
    """min takes the most restrictive layer."""

    assert abs(C([0.2, 0.5, 0.8], "min") - 0.2) < TOL


def test_combine_scalar_only_returns_float() -> None:
    """All-scalar layers reduce to a float."""

    assert isinstance(C([0.3, 0.6]), float)


def test_combine_single_layer_identity() -> None:
    """Combining one layer returns that layer."""

    for strategy in ["geomean", "min", "mean", "product"]:
        assert abs(C([0.42], strategy) - 0.42) < TOL

    out = C([[0.1, 0.9]], "mean")
    assert len(out) == 2
    assert abs(out[0] - 0.1) < TOL
    assert abs(out[1] - 0.9) < TOL


def test_combine_mixed_scalar_and_list() -> None:
    """A scalar layer broadcasts against a list layer."""

    out = C([[0.2, 0.8], 0.5], "mean")
    assert len(out) == 2
    assert abs(out[0] - (0.2 + 0.5) / 2) < TOL
    assert abs(out[1] - (0.8 + 0.5) / 2) < TOL


def test_combine_length_mismatch_repeats_last() -> None:
    """The shorter list layer repeats its last value."""

    out = C([[0.2, 0.4, 0.6], [0.9]], "min")
    assert len(out) == 3
    assert abs(out[0] - 0.2) < TOL  # min(0.2, 0.9)
    assert abs(out[1] - 0.4) < TOL  # min(0.4, 0.9) — 0.9 repeated
    assert abs(out[2] - 0.6) < TOL  # min(0.6, 0.9) — 0.9 repeated


def test_combine_list_geomean_per_step() -> None:
    """geomean of equal per-step layers returns those values."""

    out = C([[0.25, 0.5], [0.25, 0.5]], "geomean")
    assert abs(out[0] - 0.25) < TOL
    assert abs(out[1] - 0.5) < TOL


def test_combine_empty_layers_raises() -> None:
    """An empty layer list is an error."""

    with pytest.raises(ValueError) as exc:
        C([])
    assert "empty" in str(exc.value).lower()


def test_combine_empty_list_layer_yields_empty() -> None:
    """An empty list operand collapses the result to []."""

    assert C([[], 0.5]) == []
    assert C([[]]) == []


def test_combine_unknown_strategy_raises() -> None:
    """An unknown strategy lists the valid names."""

    with pytest.raises(ValueError) as exc:
        C([0.5], "nope")
    assert "geomean" in str(exc.value)


def test_combine_bounds_scalar_sweep() -> None:
    """Scalar combinations stay in [0, 1] and never NaN."""

    rng = random.Random(0)

    for _ in range(2000):
        layers = [rng.random() for _ in range(rng.randint(1, 4))]
        for strategy in ["geomean", "min", "mean", "product"]:
            out = C(layers, strategy)
            assert 0.0 <= out <= 1.0
            assert out == out


def test_combine_bounds_list_sweep() -> None:
    """List combinations stay in [0, 1] at every step."""

    rng = random.Random(2)

    for _ in range(500):
        layers = [
            [rng.random() for _ in range(rng.randint(1, 8))]
            for _ in range(rng.randint(1, 4))
        ]
        for strategy in ["geomean", "min", "mean", "product"]:
            for v in C(layers, strategy):
                assert 0.0 <= v <= 1.0
                assert v == v


# --- warp_stack ---


def _logit(x: float) -> float:
    return math.log(x / (1.0 - x))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def test_stack_empty_amounts_identity() -> None:
    """Warping by no knobs returns the value unchanged."""

    for v in [0.0, 0.3, 0.5, 1.0]:
        assert S(v, []) == v

    assert S([0.2, 0.8], []) == [0.2, 0.8]


def test_stack_single_amount_equals_warp() -> None:
    """One knob equals a single density_warp."""

    for v, a in [(0.3, 0.7), (0.5, 0.2), (0.9, 0.6)]:
        assert abs(S(v, [a]) - W(v, a)) < TOL


def test_stack_two_amounts_log_odds_sum() -> None:
    """Two knobs equal one warp whose knobs sum in log-odds."""

    p, a1, a2 = 0.3, 0.6, 0.8
    combined = _sigmoid(_logit(a1) + _logit(a2))
    assert abs(S(p, [a1, a2]) - W(p, combined)) < TOL


def test_stack_compose_equals_nested() -> None:
    """Stacking equals nested warps."""

    p, a1, a2, a3 = 0.3, 0.6, 0.8, 0.4
    assert abs(S(p, [a1, a2, a3]) - W(W(W(p, a1), a2), a3)) < TOL


def test_stack_order_independent() -> None:
    """Knob order does not matter."""

    assert abs(S(0.3, [0.6, 0.8, 0.4]) - S(0.3, [0.4, 0.6, 0.8])) < TOL


def test_stack_neutral_half_no_op() -> None:
    """A 0.5 knob changes nothing."""

    assert abs(S(0.37, [0.5, 0.5, 0.5]) - 0.37) < TOL
    assert abs(S(0.3, [0.7, 0.5, 0.8]) - S(0.3, [0.7, 0.8])) < TOL


def test_stack_scalar_returns_float() -> None:
    """All-scalar input returns a float."""

    assert isinstance(S(0.4, [0.6, 0.7]), float)


def test_stack_list_value_list_knobs() -> None:
    """A list value with list knobs warps per step."""

    out = S([0.2, 0.8], [[0.7, 0.3], 0.6])
    expected = W(W([0.2, 0.8], [0.7, 0.3]), 0.6)
    assert len(out) == 2
    for o, e in zip(out, expected):
        assert abs(o - e) < TOL


def test_stack_scalar_value_list_knob_widens() -> None:
    """A scalar value with a per-step knob widens to a list."""

    out = S(0.5, [[0.2, 0.5, 0.8]])
    assert len(out) == 3
    for o, a in zip(out, [0.2, 0.5, 0.8]):
        assert abs(o - a) < TOL  # W(0.5, a) == a


def test_stack_saturates_denser() -> None:
    """More knobs above 0.5 only increase density."""

    vals = [S(0.5, [0.7] * k) for k in range(1, 6)]
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
    assert vals[-1] > vals[0]


def test_stack_saturates_sparser() -> None:
    """More knobs below 0.5 only decrease density."""

    vals = [S(0.5, [0.3] * k) for k in range(1, 6)]
    assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    assert vals[-1] < vals[0]


def test_stack_bounds_sweep() -> None:
    """Stacked warps stay in [0, 1] and never NaN."""

    rng = random.Random(1)

    for _ in range(2000):
        knobs = [rng.random() for _ in range(rng.randint(1, 5))]
        out = S(rng.random(), knobs)
        assert 0.0 <= out <= 1.0
        assert out == out
