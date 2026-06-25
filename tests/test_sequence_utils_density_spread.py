import math
import random

import pytest

import subsequence.sequence_utils


SP = subsequence.sequence_utils.density_spread
TOL = 1e-9


def _odds (x: float) -> float:
	return x / (1.0 - x)


def _logit (x: float) -> float:
	return math.log(x / (1.0 - x))


def _sigmoid (z: float) -> float:
	return 1.0 / (1.0 + math.exp(-z))


def _k (amount: float) -> float:
	return amount / (1.0 - amount)


# --- identity, fixed point, and the saturating corners ---

def test_identity_at_half_exact () -> None:

	"""amount=0.5 returns the value unchanged, bit-exactly, for any anchor."""

	for p in [0.0, 0.1, 0.25, 0.5, 0.9, 1.0]:
		for m in [0.001, 0.3, 0.5, 0.999]:
			assert SP(p, 0.5, m) == p


def test_fixed_point_at_midpoint () -> None:

	"""A value equal to the anchor never moves, for any amount."""

	for m in [0.001, 0.1, 0.3, 0.5, 0.7, 0.9, 0.999]:
		for amount in [0.0, 0.1, 0.5, 0.9, 1.0]:
			assert abs(SP(m, amount, m) - m) < TOL


def test_amount_one_rails_by_side () -> None:

	"""amount=1 drives each interior value to the rail on its side of m."""

	assert SP(0.3, 1.0, 0.5) == 0.0
	assert SP(0.7, 1.0, 0.5) == 1.0
	assert SP(0.5, 1.0, 0.5) == 0.5

	for p in [0.01, 0.2, 0.45]:
		assert SP(p, 1.0, 0.6) == 0.0                          # p < m -> 0
	for p in [0.65, 0.8, 0.99]:
		assert SP(p, 1.0, 0.6) == 1.0                          # p > m -> 1


def test_amount_zero_collapses_to_midpoint () -> None:

	"""amount=0 collapses every interior value onto the anchor."""

	for p in [0.05, 0.3, 0.7, 0.95]:
		assert SP(p, 0.0, 0.42) == 0.42


def test_midpoint_half_reduces_to_odds_power () -> None:

	"""At m=0.5 the odds are raised to the power k = amount/(1-amount)."""

	# odds(0.8)=4, k=3 -> 4**3 = 64 -> 64/65.
	assert abs(SP(0.8, 0.75, 0.5) - 64.0 / 65.0) < TOL
	# odds(0.75)=3, k=3 -> 3**3 = 27 -> 27/28.
	assert abs(SP(0.75, 0.75, 0.5) - 27.0 / 28.0) < TOL
	# The reciprocal knob (k=1/3) is the cube root in odds space.
	cube_root = 4.0 ** (1.0 / 3.0)
	assert abs(SP(0.8, 0.25, 0.5) - cube_root / (1.0 + cube_root)) < TOL


def test_odds_ratio_identity () -> None:

	"""odds(out)/odds(m) == (odds(p)/odds(m))**k over moderate amounts."""

	for p in [0.2, 0.45, 0.6, 0.85]:
		for m in [0.3, 0.5, 0.7]:
			for amount in [0.35, 0.45, 0.6, 0.65]:
				k = _k(amount)
				out = SP(p, amount, m)
				lhs = _odds(out) / _odds(m)
				rhs = (_odds(p) / _odds(m)) ** k
				assert abs(lhs - rhs) < 1e-6


# --- the two compositional laws (interior intermediates only) ---

def test_composition_multiplies_gains () -> None:

	"""Two spreads about the same anchor compound by multiplying their gains."""

	p, a1, a2, m = 0.6, 0.6, 0.65, 0.4
	kc = _k(a1) * _k(a2)
	ac = kc / (1.0 + kc)
	assert abs(SP(SP(p, a1, m), a2, m) - SP(p, ac, m)) < TOL


def test_inverse_law_returns_value () -> None:

	"""Spreading by amount then by its complement is the identity."""

	p, amount, m = 0.6, 0.65, 0.4
	assert abs(SP(SP(p, amount, m), 1.0 - amount, m) - p) < TOL


def test_saturation_is_irreversible () -> None:

	"""Once a strong expand pins a value to a rail, a later contract cannot recover it."""

	pinned = SP(0.99, 0.95, 0.5)
	assert pinned == 1.0
	assert SP(pinned, 0.05, 0.5) == 1.0                        # stays on the rail, not back to 0.99


# --- direction, ordering, and bounds ---

def test_expand_pushes_away_contract_pulls_toward () -> None:

	"""Above 0.5 widens the gap to the anchor; below 0.5 narrows it."""

	rng = random.Random(0)

	for _ in range(2000):
		p = rng.random() * 0.9 + 0.05
		m = rng.random() * 0.8 + 0.1
		if abs(p - m) <= 0.01:
			continue
		assert abs(SP(p, 0.75, m) - m) >= abs(p - m)            # expand
		assert abs(SP(p, 0.25, m) - m) <= abs(p - m)            # contract


def test_never_crosses_midpoint () -> None:

	"""A value stays on its own side of the anchor for any interior amount."""

	rng = random.Random(1)

	for _ in range(2000):
		p = rng.random() * 0.98 + 0.01
		m = rng.random() * 0.8 + 0.1
		for amount in [0.1, 0.3, 0.7, 0.9]:
			out = SP(p, amount, m)
			if p < m:
				assert out <= m
			elif p > m:
				assert out >= m


def test_monotonic_in_value () -> None:

	"""Increasing the value never decreases the output."""

	out = [SP(p, 0.7, 0.4) for p in [0.05, 0.2, 0.4, 0.6, 0.8, 0.95]]
	assert all(out[i] <= out[i + 1] for i in range(len(out) - 1))


def test_monotonic_in_amount () -> None:

	"""More expand drives a value further toward its own rail."""

	above = [SP(0.7, a, 0.5) for a in [0.1, 0.3, 0.5, 0.7, 0.9]]
	assert all(above[i] <= above[i + 1] for i in range(len(above) - 1))      # p > m climbs

	below = [SP(0.3, a, 0.5) for a in [0.1, 0.3, 0.5, 0.7, 0.9]]
	assert all(below[i] >= below[i + 1] for i in range(len(below) - 1))      # p < m falls


def test_value_zero_stays_zero () -> None:

	"""A zero value stays at zero for any amount and anchor."""

	for amount in [0.0, 0.3, 0.7, 1.0]:
		for m in [0.2, 0.5, 0.8]:
			assert SP(0.0, amount, m) == 0.0


def test_value_one_stays_one () -> None:

	"""A one value stays at one for any amount and anchor."""

	for amount in [0.0, 0.3, 0.7, 1.0]:
		for m in [0.2, 0.5, 0.8]:
			assert SP(1.0, amount, m) == 1.0


def test_bounds_over_random_sweep () -> None:

	"""Output stays in [0, 1] and is never NaN."""

	rng = random.Random(2)

	for _ in range(2000):
		out = SP(rng.random(), rng.random(), rng.random() * 0.98 + 0.01)
		assert 0.0 <= out <= 1.0
		assert out == out                                       # not NaN


# --- shape and broadcasting (mirrors the density_warp tests) ---

def test_scalar_returns_float () -> None:

	"""Scalar value and amount return a float."""

	assert isinstance(SP(0.4, 0.6, 0.5), float)


def test_list_value_scalar_amount () -> None:

	"""A list value with a scalar amount returns a same-length list."""

	out = SP([0.2, 0.5, 0.8], 0.7, 0.5)
	assert isinstance(out, list)
	assert len(out) == 3
	assert out[1] == 0.5                                        # middle equals the anchor -> fixed
	for v, o in zip([0.2, 0.5, 0.8], out):
		assert abs(o - SP(v, 0.7, 0.5)) < TOL


def test_scalar_value_list_amount () -> None:

	"""A scalar value with a per-step amount returns a list."""

	out = SP(0.7, [0.3, 0.7], 0.5)
	assert isinstance(out, list)
	assert len(out) == 2
	assert abs(out[0] - SP(0.7, 0.3, 0.5)) < TOL
	assert abs(out[1] - SP(0.7, 0.7, 0.5)) < TOL


def test_list_value_list_amount () -> None:

	"""Equal-length lists spread element-wise."""

	out = SP([0.2, 0.8], [0.7, 0.3], 0.5)
	assert abs(out[0] - SP(0.2, 0.7, 0.5)) < TOL
	assert abs(out[1] - SP(0.8, 0.3, 0.5)) < TOL


def test_length_mismatch_repeats_last () -> None:

	"""On unequal lengths the shorter operand repeats its last value."""

	out = SP([0.2, 0.5, 0.8], [0.7], 0.5)
	assert len(out) == 3
	for v, o in zip([0.2, 0.5, 0.8], out):
		assert abs(o - SP(v, 0.7, 0.5)) < TOL

	out = SP([0.3], [0.2, 0.4, 0.6], 0.5)
	assert len(out) == 3
	for a, o in zip([0.2, 0.4, 0.6], out):
		assert abs(o - SP(0.3, a, 0.5)) < TOL


def test_empty_list_edges () -> None:

	"""An empty list operand yields an empty list."""

	assert SP([], 0.5) == []
	assert SP(0.5, []) == []
	assert SP([], []) == []
	assert SP([], [0.5]) == []


# --- the midpoint anchor ---

def test_midpoint_default_is_half () -> None:

	"""The default anchor is 0.5."""

	assert SP(0.3, 0.7) == SP(0.3, 0.7, 0.5)


def test_midpoint_out_of_range_raises () -> None:

	"""An anchor on or beyond a rail is an error."""

	for bad in [0.0, 1.0, -0.1, 1.2]:
		with pytest.raises(ValueError) as exc:
			SP(0.5, 0.7, bad)
		assert "midpoint" in str(exc.value)


def test_midpoint_validated_before_shape () -> None:

	"""A bad anchor raises even when the payload would short-circuit to []."""

	with pytest.raises(ValueError):
		SP([], 0.5, midpoint=1.0)
