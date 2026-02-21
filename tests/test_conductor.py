
import pytest
import subsequence.conductor
import subsequence.pattern
import subsequence.pattern_builder


def test_lfo_sine ():

	"""Test sine wave LFO output."""
	
	conductor = subsequence.conductor.Conductor()
	conductor.lfo("sine", shape="sine", cycle_beats=4.0, min_val=0.0, max_val=1.0)
	
	# Start (phase 0) -> sin(0) = 0 -> mapped to 0.5
	assert conductor.get("sine", 0.0) == 0.5
	
	# 1 beat (0.25 cycle) -> sin(pi/2) = 1 -> mapped to 1.0
	assert conductor.get("sine", 1.0) == 1.0
	
	# 2 beats (0.5 cycle) -> sin(pi) = 0 -> mapped to 0.5
	assert conductor.get("sine", 2.0) == pytest.approx(0.5)
	
	# 3 beats (0.75 cycle) -> sin(3pi/2) = -1 -> mapped to 0.0
	assert conductor.get("sine", 3.0) == pytest.approx(0.0)
	
	# 4 beats (1.0 cycle) -> sin(2pi) = 0 -> mapped to 0.5
	assert conductor.get("sine", 4.0) == pytest.approx(0.5)


def test_lfo_triangle ():

	"""Test triangle wave LFO output."""
	
	conductor = subsequence.conductor.Conductor()
	conductor.lfo("tri", shape="triangle", cycle_beats=4.0)
	
	# 0.0 -> 0.0
	assert conductor.get("tri", 0.0) == 0.0
	
	# 1.0 (0.25 cycle) -> 0.5
	assert conductor.get("tri", 1.0) == 0.5
	
	# 2.0 (0.5 cycle) -> 1.0
	assert conductor.get("tri", 2.0) == 1.0
	
	# 3.0 (0.75 cycle) -> 0.5
	assert conductor.get("tri", 3.0) == 0.5


def test_line_ramp ():

	"""Test linear ramp."""
	
	conductor = subsequence.conductor.Conductor()
	conductor.line("ramp", start_val=0.0, end_val=1.0, duration_beats=4.0)
	
	# Start
	assert conductor.get("ramp", 0.0) == 0.0
	
	# Midpoint
	assert conductor.get("ramp", 2.0) == 0.5
	
	# End
	assert conductor.get("ramp", 4.0) == 1.0
	
	# Past end (clamped)
	assert conductor.get("ramp", 5.0) == 1.0


def test_line_loop ():

	"""Test looping ramp."""
	
	conductor = subsequence.conductor.Conductor()
	conductor.line("loop", start_val=0.0, end_val=1.0, duration_beats=4.0, loop=True)
	
	# Start
	assert conductor.get("loop", 0.0) == 0.0
	
	# End of first loop is start of second
	assert conductor.get("loop", 4.0) == 0.0
	
	# 1.5 loops
	assert conductor.get("loop", 6.0) == 0.5


def test_lfo_saw ():

	"""Test saw wave LFO output."""

	conductor = subsequence.conductor.Conductor()
	conductor.lfo("saw", shape="saw", cycle_beats=4.0)

	# Start of cycle -> 0.0
	assert conductor.get("saw", 0.0) == 0.0

	# Quarter cycle -> 0.25
	assert conductor.get("saw", 1.0) == 0.25

	# Half cycle -> 0.5
	assert conductor.get("saw", 2.0) == 0.5

	# Three-quarter cycle -> 0.75
	assert conductor.get("saw", 3.0) == 0.75


def test_lfo_square ():

	"""Test square wave LFO output."""

	conductor = subsequence.conductor.Conductor()
	conductor.lfo("sq", shape="square", cycle_beats=4.0)

	# First half of cycle -> 1.0
	assert conductor.get("sq", 0.0) == 1.0
	assert conductor.get("sq", 1.0) == 1.0

	# Second half of cycle -> 0.0
	assert conductor.get("sq", 2.0) == 0.0
	assert conductor.get("sq", 3.0) == 0.0


def test_lfo_phase_offset ():

	"""Test LFO with phase offset."""

	conductor = subsequence.conductor.Conductor()
	conductor.lfo("sine", shape="sine", cycle_beats=4.0, phase=0.25)

	# phase=0.25 shifts by quarter cycle, so beat 0 is at sin(pi/2) = 1 -> mapped to 1.0
	assert conductor.get("sine", 0.0) == pytest.approx(1.0)

	# beat 1 is at sin(pi) = 0 -> mapped to 0.5
	assert conductor.get("sine", 1.0) == pytest.approx(0.5)


def test_lfo_custom_range ():

	"""Test LFO with custom min/max values."""

	conductor = subsequence.conductor.Conductor()
	conductor.lfo("vel", shape="triangle", cycle_beats=4.0, min_val=50.0, max_val=100.0)

	# Triangle at 0.0 -> 0.0 -> mapped to 50.0
	assert conductor.get("vel", 0.0) == 50.0

	# Triangle peak at 2.0 -> 1.0 -> mapped to 100.0
	assert conductor.get("vel", 2.0) == 100.0

	# Triangle at 1.0 -> 0.5 -> mapped to 75.0
	assert conductor.get("vel", 1.0) == 75.0


def test_lfo_invalid_cycle_beats ():

	"""Test that zero or negative cycle_beats raises ValueError."""

	conductor = subsequence.conductor.Conductor()

	with pytest.raises(ValueError):
		conductor.lfo("bad", cycle_beats=0)

	with pytest.raises(ValueError):
		conductor.lfo("bad", cycle_beats=-1.0)


def test_line_invalid_duration ():

	"""Test that zero or negative duration_beats raises ValueError."""

	conductor = subsequence.conductor.Conductor()

	with pytest.raises(ValueError):
		conductor.line("bad", start_val=0, end_val=1, duration_beats=0)

	with pytest.raises(ValueError):
		conductor.line("bad", start_val=0, end_val=1, duration_beats=-4.0)


def test_missing_signal ():

	"""Test querying a non-existent signal."""

	conductor = subsequence.conductor.Conductor()
	assert conductor.get("ghost", 0.0) == 0.0


def test_signal_helper ():

	"""Test p.signal() reads the conductor at the current bar."""

	conductor = subsequence.conductor.Conductor()
	conductor.lfo("tri", shape="triangle", cycle_beats=16.0)

	pattern = subsequence.pattern.Pattern(channel=0, length=4.0)

	# bar=2 -> beat=8 -> progress 8/16=0.5 -> triangle peak = 1.0
	builder = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0, conductor=conductor, bar=2)

	assert builder.signal("tri") == 1.0

	# bar=0 -> beat=0 -> triangle start = 0.0
	builder_zero = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0, conductor=conductor, bar=0)

	assert builder_zero.signal("tri") == 0.0


def test_line_with_shape_ease_in ():

	"""Line with shape='ease_in' returns non-linear values."""

	conductor = subsequence.conductor.Conductor()
	conductor.line("ramp", start_val=0.0, end_val=1.0, duration_beats=4.0, shape="ease_in")

	# ease_in(0.5) = 0.25, so the midpoint value should be 0.25, not 0.5
	assert conductor.get("ramp", 2.0) == pytest.approx(0.25)

	# Endpoints should still clamp correctly
	assert conductor.get("ramp", 0.0) == pytest.approx(0.0)
	assert conductor.get("ramp", 4.0) == pytest.approx(1.0)


def test_line_with_shape_ease_in_out ():

	"""Line with shape='ease_in_out' is symmetric around the midpoint."""

	conductor = subsequence.conductor.Conductor()
	conductor.line("ramp", start_val=0.0, end_val=100.0, duration_beats=4.0, shape="ease_in_out")

	# ease_in_out is symmetric: midpoint value is the midpoint of start/end
	assert conductor.get("ramp", 2.0) == pytest.approx(50.0)

	# The value at 1/4 duration should be less than 25 (slow start)
	assert conductor.get("ramp", 1.0) < 25.0


def test_line_with_callable_shape ():

	"""Line accepts a raw callable as the shape parameter."""

	conductor = subsequence.conductor.Conductor()
	# Custom square-root easing
	conductor.line("ramp", start_val=0.0, end_val=1.0, duration_beats=4.0, shape=lambda t: t ** 0.5)

	# At midpoint, sqrt(0.5) ≈ 0.707
	assert conductor.get("ramp", 2.0) == pytest.approx(0.5 ** 0.5)


def test_line_default_shape_is_linear ():

	"""The default Line shape remains linear (regression test)."""

	conductor = subsequence.conductor.Conductor()
	conductor.line("ramp", start_val=0.0, end_val=1.0, duration_beats=4.0)

	assert conductor.get("ramp", 2.0) == pytest.approx(0.5)


def test_signal_helper_no_conductor ():

	"""Test p.signal() returns 0.0 when no conductor is attached."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0)

	assert builder.signal("anything") == 0.0
