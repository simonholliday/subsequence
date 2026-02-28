
import pytest
import subsequence.easing
import subsequence.sequencer


# ─── Core properties of all easing functions ─────────────────────────────────


def test_all_easings_zero_at_zero ():

	"""Every easing function returns 0.0 at t=0."""

	for name, fn in subsequence.easing.EASING_FUNCTIONS.items():
		assert fn(0.0) == pytest.approx(0.0), f"{name}(0) should be 0.0"


def test_all_easings_one_at_one ():

	"""Every easing function returns 1.0 at t=1."""

	for name, fn in subsequence.easing.EASING_FUNCTIONS.items():
		assert fn(1.0) == pytest.approx(1.0), f"{name}(1) should be 1.0"


def test_all_easings_monotonic ():

	"""Every easing function is non-decreasing over [0, 1]."""

	steps = 100
	for name, fn in subsequence.easing.EASING_FUNCTIONS.items():
		values = [fn(i / steps) for i in range(steps + 1)]
		for i in range(len(values) - 1):
			assert values[i] <= values[i + 1] + 1e-9, (
				f"{name} is not monotonic at t={i/steps:.2f}"
			)


# ─── Shape-specific characteristics ──────────────────────────────────────────


def test_linear_is_identity ():

	"""linear(t) == t for a range of values."""

	for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
		assert subsequence.easing.linear(t) == pytest.approx(t)


def test_ease_in_slow_start ():

	"""ease_in should be below the diagonal — slow start."""

	assert subsequence.easing.ease_in(0.5) < 0.5


def test_ease_out_fast_start ():

	"""ease_out should be above the diagonal — fast start."""

	assert subsequence.easing.ease_out(0.5) > 0.5


def test_ease_in_out_symmetric ():

	"""ease_in_out midpoint should equal 0.5."""

	assert subsequence.easing.ease_in_out(0.5) == pytest.approx(0.5)


def test_s_curve_symmetric ():

	"""s_curve midpoint should equal 0.5."""

	assert subsequence.easing.s_curve(0.5) == pytest.approx(0.5)


def test_exponential_slower_than_ease_in ():

	"""exponential (cubic) should be slower early than ease_in (quadratic)."""

	assert subsequence.easing.exponential(0.5) < subsequence.easing.ease_in(0.5)


def test_logarithmic_faster_than_ease_out ():

	"""logarithmic (cubic) should be faster early than ease_out (quadratic)."""

	assert subsequence.easing.logarithmic(0.5) > subsequence.easing.ease_out(0.5)


def test_s_curve_smoother_than_ease_in_out ():

	"""s_curve should have a flatter start than ease_in_out (derivative closer to 0 near t=0)."""

	# Near t=0, s_curve should be below ease_in_out (starts more slowly)
	assert subsequence.easing.s_curve(0.1) < subsequence.easing.ease_in_out(0.1)


# ─── get_easing ───────────────────────────────────────────────────────────────


def test_get_easing_by_string ():

	"""get_easing returns the correct function for a valid name."""

	fn = subsequence.easing.get_easing("linear")
	assert fn is subsequence.easing.linear


def test_get_easing_all_names ():

	"""get_easing works for every registered name."""

	for name, expected in subsequence.easing.EASING_FUNCTIONS.items():
		assert subsequence.easing.get_easing(name) is expected


def test_get_easing_callable_passthrough ():

	"""get_easing returns the callable unchanged when passed a function."""

	custom = lambda t: t ** 0.5
	assert subsequence.easing.get_easing(custom) is custom


def test_get_easing_unknown_raises ():

	"""get_easing raises ValueError for an unknown string name."""

	with pytest.raises(ValueError, match="Unknown easing shape"):
		subsequence.easing.get_easing("bogus_shape")


# ─── BpmTransition easing integration ────────────────────────────────────────


def test_bpm_transition_ease_in_out_midpoint_is_linear ():

	"""BpmTransition with ease_in_out: midpoint BPM equals the arithmetic midpoint."""

	transition = subsequence.sequencer.BpmTransition(
		start_bpm = 100.0,
		target_bpm = 140.0,
		total_pulses = 100,
		easing_fn = subsequence.easing.ease_in_out,
	)

	# At exactly the midpoint, ease_in_out(0.5) == 0.5, so BPM should be 120
	transition.elapsed_pulses = 50
	progress = transition.elapsed_pulses / transition.total_pulses
	eased = transition.easing_fn(progress)
	bpm = transition.start_bpm + (transition.target_bpm - transition.start_bpm) * eased

	assert bpm == pytest.approx(120.0)


def test_bpm_transition_ease_in_starts_slowly ():

	"""BpmTransition with ease_in: BPM at 25% of duration should be well below 25% of range."""

	transition = subsequence.sequencer.BpmTransition(
		start_bpm = 100.0,
		target_bpm = 140.0,
		total_pulses = 100,
		easing_fn = subsequence.easing.ease_in,
	)

	transition.elapsed_pulses = 25
	progress = transition.elapsed_pulses / transition.total_pulses  # 0.25
	eased = transition.easing_fn(progress)                          # ease_in(0.25) = 0.0625
	bpm = transition.start_bpm + (transition.target_bpm - transition.start_bpm) * eased

	# Linear at 25% would be 110; ease_in should be much lower
	assert bpm < 110.0


def test_bpm_transition_default_easing_is_linear ():

	"""BpmTransition default easing is linear (regression test)."""

	transition = subsequence.sequencer.BpmTransition(
		start_bpm = 100.0,
		target_bpm = 140.0,
		total_pulses = 100,
	)

	transition.elapsed_pulses = 50
	progress = transition.elapsed_pulses / transition.total_pulses
	eased = transition.easing_fn(progress)
	bpm = transition.start_bpm + (transition.target_bpm - transition.start_bpm) * eased

	assert bpm == pytest.approx(120.0)  # linear midpoint


# ─── map_value ────────────────────────────────────────────────────────────────


def test_map_value_linear ():

	"""map_value should interpolate linearly by default."""

	# Map 0.5 from [0, 1] to [0, 100] -> 50.0
	val = subsequence.easing.map_value(0.5, 0.0, 1.0, 0.0, 100.0)
	assert val == pytest.approx(50.0)

	# Map 5 from [0, 10] to [100, 200] -> 150.0
	val = subsequence.easing.map_value(5, 0, 10, 100, 200)
	assert val == pytest.approx(150.0)


def test_map_value_clamp ():

	"""map_value should clamp to output bounds when clamp=True."""

	# Value exceeds in_max (1.5 > 1.0)
	val = subsequence.easing.map_value(1.5, 0.0, 1.0, 0.0, 100.0)
	assert val == pytest.approx(100.0)

	# Value below in_min (-0.5 < 0.0)
	val = subsequence.easing.map_value(-0.5, 0.0, 1.0, 0.0, 100.0)
	assert val == pytest.approx(0.0)


def test_map_value_no_clamp ():

	"""map_value should extrapolate when clamp=False."""

	val = subsequence.easing.map_value(1.5, 0.0, 1.0, 0.0, 100.0, clamp=False)
	assert val == pytest.approx(150.0)


def test_map_value_easing_shape ():

	"""map_value should apply the requested easing curve."""

	# At 0.5 progress, ease_in is < 0.5.
	line_val = subsequence.easing.map_value(0.5, 0.0, 1.0, 0.0, 100.0, shape="linear")
	ease_val = subsequence.easing.map_value(0.5, 0.0, 1.0, 0.0, 100.0, shape="ease_in")

	assert line_val == pytest.approx(50.0)
	assert ease_val < 50.0


def test_map_value_reversed_range ():

	"""map_value should handle descending output ranges."""

	# Map 0.25 from [0, 1] to [100, 0] -> 75.0
	val = subsequence.easing.map_value(0.25, 0.0, 1.0, 100.0, 0.0)
	assert val == pytest.approx(75.0)


def test_map_value_zero_range_safeguard ():

	"""map_value should handle in_min == in_max safely."""

	val = subsequence.easing.map_value(0.5, 0.0, 0.0, 0.0, 100.0)
	assert val == pytest.approx(0.0)
