
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


def test_missing_signal ():

	"""Test querying a non-existent signal."""
	
	conductor = subsequence.conductor.Conductor()
	assert conductor.get("ghost", 0.0) == 0.0
