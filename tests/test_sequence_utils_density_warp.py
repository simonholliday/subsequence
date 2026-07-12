import math
import random

import subsequence.sequence_utils


W = subsequence.sequence_utils.density_warp
TOL = 1e-9


def test_identity_at_half() -> None:
    """amount=0.5 returns the value unchanged."""

    for p in [0.0, 0.1, 0.25, 0.5, 0.9, 1.0]:
        assert abs(W(p, 0.5) - p) < TOL


def test_half_step_equals_amount() -> None:
    """A neutral 0.5-weight step fires at exactly the knob value."""

    for a in [0.0, 0.1, 0.5, 0.9, 1.0]:
        assert abs(W(0.5, a) - a) < TOL


def test_all_on_at_amount_one() -> None:
    """amount=1 drives every interior value to exactly 1.0."""

    for p in [0.01, 0.3, 0.5, 0.7, 0.99]:
        assert W(p, 1.0) == 1.0


def test_all_off_at_amount_zero() -> None:
    """amount=0 drives every interior value to exactly 0.0."""

    for p in [0.01, 0.3, 0.5, 0.7, 0.99]:
        assert W(p, 0.0) == 0.0


def test_value_zero_stays_zero() -> None:
    """A zero-character step never fires, even at amount=1."""

    for a in [0.0, 0.3, 0.7, 1.0]:
        assert W(0.0, a) == 0.0


def test_value_one_stays_one() -> None:
    """A full-character step always fires, even at amount=0."""

    for a in [0.0, 0.3, 0.7, 1.0]:
        assert W(1.0, a) == 1.0


def test_asymmetric_corners() -> None:
    """At the opposing corners the value's extremity wins."""

    assert W(0.0, 1.0) == 0.0
    assert W(1.0, 0.0) == 1.0


def test_symmetry_law() -> None:
    """W(1-p, 1-a) == 1 - W(p, a) over the open square."""

    assert abs(W(0.2, 0.7) - (1.0 - W(0.8, 0.3))) < TOL

    rng = random.Random(1)

    for _ in range(2000):
        p = rng.random() * 0.98 + 0.01
        a = rng.random() * 0.98 + 0.01
        assert abs(W(1 - p, 1 - a) - (1.0 - W(p, a))) < TOL


def test_stacking_log_odds() -> None:
    """Two warps equal one warp whose knobs combine by summing log-odds."""

    def logit(x: float) -> float:
        return math.log(x / (1.0 - x))

    def sigmoid(z: float) -> float:
        return 1.0 / (1.0 + math.exp(-z))

    p, a1, a2 = 0.3, 0.6, 0.8
    combined = sigmoid(logit(a1) + logit(a2))
    assert abs(W(W(p, a1), a2) - W(p, combined)) < TOL


def test_anchored_values() -> None:
    """Hand-computed values guard against silent drift."""

    assert abs(W(0.25, 0.75) - 0.5) < TOL  # odds (1/3) * 3 = 1
    assert abs(W(0.2, 0.7) - 0.3684210526315789) < TOL


def test_scalar_returns_float() -> None:
    """A scalar value returns a float."""

    assert isinstance(W(0.4, 0.6), float)


def test_list_value_scalar_amount() -> None:
    """A list value with a scalar knob returns a same-length list."""

    out = W([0.2, 0.5, 0.8], 0.7)
    assert isinstance(out, list)
    assert len(out) == 3
    assert abs(out[1] - 0.7) < TOL  # middle is 0.5 -> amount
    for v, o in zip([0.2, 0.5, 0.8], out):
        assert abs(o - W(v, 0.7)) < TOL


def test_scalar_value_list_amount() -> None:
    """A scalar value with a per-step knob list returns a list."""

    out = W(0.5, [0.2, 0.5, 0.8])
    assert isinstance(out, list)
    assert len(out) == 3
    for a, o in zip([0.2, 0.5, 0.8], out):
        assert abs(o - a) < TOL  # W(0.5, a) == a


def test_list_value_list_amount() -> None:
    """Equal-length lists warp element-wise."""

    out = W([0.2, 0.8], [0.7, 0.3])
    assert abs(out[0] - W(0.2, 0.7)) < TOL
    assert abs(out[1] - W(0.8, 0.3)) < TOL


def test_length_mismatch_repeats_last() -> None:
    """On unequal lengths the shorter operand repeats its last value."""

    out = W([0.2, 0.5, 0.8], [0.6])
    assert len(out) == 3
    for v, o in zip([0.2, 0.5, 0.8], out):
        assert abs(o - W(v, 0.6)) < TOL

    out = W([0.5], [0.2, 0.4, 0.6])
    assert len(out) == 3
    for a, o in zip([0.2, 0.4, 0.6], out):
        assert abs(o - W(0.5, a)) < TOL


def test_empty_list_edges() -> None:
    """An empty list operand yields an empty list."""

    assert W([], 0.5) == []
    assert W(0.5, []) == []
    assert W([], []) == []
    assert W([], [0.5]) == []


def test_guards_clamp_out_of_range() -> None:
    """Out-of-range inputs are absorbed by the edge guards."""

    assert W(-0.1, 0.5) == 0.0
    assert W(1.2, 0.5) == 1.0
    assert W(0.5, -0.1) == 0.0
    assert W(0.5, 1.2) == 1.0


def test_bounds_over_random_sweep() -> None:
    """Output stays in [0, 1] and is never NaN."""

    rng = random.Random(0)

    for _ in range(2000):
        out = W(rng.random(), rng.random())
        assert 0.0 <= out <= 1.0
        assert out == out  # not NaN


def test_monotonic_in_amount_and_value() -> None:
    """Increasing amount (or value) never decreases the output."""

    by_amount = [W(0.4, a) for a in [0.1, 0.3, 0.5, 0.7, 0.9]]
    assert all(by_amount[i] <= by_amount[i + 1] for i in range(len(by_amount) - 1))

    by_value = [W(p, 0.7) for p in [0.1, 0.3, 0.5, 0.7, 0.9]]
    assert all(by_value[i] <= by_value[i + 1] for i in range(len(by_value) - 1))
