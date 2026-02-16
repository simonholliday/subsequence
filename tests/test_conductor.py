
import pytest
import subsequence.conductor


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
