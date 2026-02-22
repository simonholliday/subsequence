"""Tests for EasedValue — the stateful interpolation helper in subsequence.easing.

Covers:
- Initial state (prev == current == initial, delta == 0)
- update() — prev/current/delta transitions
- get() — interpolated output at progress 0, 0.5, 1.0
- get() with custom shape string and callable
- delta — sign and magnitude
- multiple sequential update() calls
- thread safety is not tested here (EasedValue is not designed for concurrent update+get)
"""

import math
import pytest

from subsequence.easing import EasedValue, ease_in_out, EASING_FUNCTIONS


# ---------------------------------------------------------------------------
# Construction and initial state
# ---------------------------------------------------------------------------

class TestEasedValueInit:

	def test_default_initial (self) -> None:
		ev = EasedValue()
		assert ev.current  == 0.0
		assert ev.previous == 0.0
		assert ev.delta    == 0.0

	def test_custom_initial (self) -> None:
		ev = EasedValue(initial=0.7)
		assert ev.current  == pytest.approx(0.7)
		assert ev.previous == pytest.approx(0.7)
		assert ev.delta    == pytest.approx(0.0)

	def test_get_before_update_returns_initial (self) -> None:
		ev = EasedValue(initial=0.6)
		# prev == current == 0.6, so interpolation always yields 0.6
		assert ev.get(0.0) == pytest.approx(0.6)
		assert ev.get(0.5) == pytest.approx(0.6)
		assert ev.get(1.0) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------

class TestEasedValueUpdate:

	def test_update_without_initial_sets_both (self) -> None:
		"""If no initial value was provided, the first update sets both prev and current."""
		ev = EasedValue()
		ev.update(0.8)
		assert ev.current  == pytest.approx(0.8)
		assert ev.previous == pytest.approx(0.8)

	def test_update_with_initial_shifts_previous (self) -> None:
		"""If an initial value was provided, the first update eases from it."""
		ev = EasedValue(initial=0.2)
		ev.update(0.8)
		assert ev.current  == pytest.approx(0.8)
		assert ev.previous == pytest.approx(0.2)

	def test_sequential_updates (self) -> None:
		ev = EasedValue()
		ev.update(0.2)   # First update sets both to 0.2
		ev.update(1.0)   # Second update sets prev=0.2, current=1.0
		assert ev.previous == pytest.approx(0.2)
		assert ev.current  == pytest.approx(1.0)

	def test_update_to_same_value (self) -> None:
		ev = EasedValue(initial=0.4)
		ev.update(0.4)
		assert ev.delta == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# get() — interpolation correctness
# ---------------------------------------------------------------------------

class TestEasedValueGet:

	def setup_method (self) -> None:
		self.ev = EasedValue(initial=0.0)
		self.ev.update(1.0)   # prev=0.0, current=1.0

	def test_get_at_zero_returns_previous (self) -> None:
		assert self.ev.get(0.0) == pytest.approx(0.0)

	def test_get_at_one_returns_current (self) -> None:
		assert self.ev.get(1.0) == pytest.approx(1.0)

	def test_get_at_midpoint_uses_easing (self) -> None:
		# Default shape is ease_in_out (Hermite smoothstep).
		# ease_in_out(0.5) = 0.5^2 * (3 - 2*0.5) = 0.25 * 2.0 = 0.5
		result = self.ev.get(0.5)
		expected = ease_in_out(0.5)   # = 0.5 for smoothstep at midpoint
		assert result == pytest.approx(expected)

	def test_get_interpolates_range (self) -> None:
		prev_result    = self.ev.get(0.0)
		mid_result     = self.ev.get(0.5)
		current_result = self.ev.get(1.0)
		# Values must be monotonically non-decreasing for a rising transition.
		assert prev_result <= mid_result <= current_result

	def test_get_downward_transition (self) -> None:
		ev = EasedValue(initial=1.0)
		ev.update(0.0)    # prev=1.0, current=0.0
		assert ev.get(0.0) == pytest.approx(1.0)
		assert ev.get(1.0) == pytest.approx(0.0)
		assert ev.get(0.5) < ev.get(0.0)   # monotone decrease


# ---------------------------------------------------------------------------
# get() — custom shapes
# ---------------------------------------------------------------------------

class TestEasedValueGetShape:

	def setup_method (self) -> None:
		self.ev = EasedValue(initial=0.0)
		self.ev.update(1.0)

	def test_linear_shape (self) -> None:
		assert self.ev.get(0.25, shape="linear") == pytest.approx(0.25)
		assert self.ev.get(0.75, shape="linear") == pytest.approx(0.75)

	def test_callable_shape (self) -> None:
		# Custom shape: square root (faster early)
		result = self.ev.get(0.25, shape=lambda t: t ** 0.5)
		assert result == pytest.approx(0.5)   # sqrt(0.25) = 0.5

	def test_unknown_shape_raises (self) -> None:
		with pytest.raises(ValueError, match="Unknown easing shape"):
			self.ev.get(0.5, shape="not_a_shape")

	def test_all_named_shapes_work (self) -> None:
		for name in EASING_FUNCTIONS:
			result = self.ev.get(0.5, shape=name)
			assert 0.0 <= result <= 1.0, f"Shape {name!r} out of [0,1] range at t=0.5"


# ---------------------------------------------------------------------------
# delta
# ---------------------------------------------------------------------------

class TestEasedValueDelta:

	def test_delta_zero_initially (self) -> None:
		ev = EasedValue(initial=0.3)
		assert ev.delta == pytest.approx(0.0)

	def test_delta_positive_when_rising (self) -> None:
		ev = EasedValue(initial=0.2)
		ev.update(0.7)
		assert ev.delta == pytest.approx(0.5)

	def test_delta_negative_when_falling (self) -> None:
		ev = EasedValue(initial=0.9)
		ev.update(0.4)
		assert ev.delta == pytest.approx(-0.5)

	def test_delta_equals_current_minus_previous (self) -> None:
		ev = EasedValue(initial=0.1)
		ev.update(0.6)
		assert ev.delta == pytest.approx(ev.current - ev.previous)

	def test_delta_stable_across_gets (self) -> None:
		"""delta must not change between calls to get() within one cycle."""
		ev = EasedValue(initial=0.0)
		ev.update(0.8)
		d1 = ev.delta
		ev.get(0.25)
		ev.get(0.5)
		ev.get(0.75)
		assert ev.delta == pytest.approx(d1)

	def test_delta_updates_after_second_update (self) -> None:
		ev = EasedValue(initial=0.0)
		ev.update(0.6)   # delta = 0.6
		ev.update(0.4)   # prev=0.6, current=0.4, delta=-0.2
		assert ev.delta == pytest.approx(-0.2)

	def test_delta_direction_sign (self) -> None:
		ev = EasedValue(initial=0.5)
		ev.update(0.9)
		assert ev.delta > 0

		ev2 = EasedValue(initial=0.5)
		ev2.update(0.1)
		assert ev2.delta < 0
