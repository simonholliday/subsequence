
import pytest
import subsequence.sequence_utils

def test_scale_clamp_basics ():
	"""Test standard scaling behavior."""
	# 0-10 -> 0-100
	assert subsequence.sequence_utils.scale_clamp(5, 0, 10, 0, 100) == 50.0
	assert subsequence.sequence_utils.scale_clamp(0, 0, 10, 0, 100) == 0.0
	assert subsequence.sequence_utils.scale_clamp(10, 0, 10, 0, 100) == 100.0

def test_scale_clamp_clamping ():
	"""Test values outside input range are clamped."""
	# Should be clamped to 0 or 100
	assert subsequence.sequence_utils.scale_clamp(-5, 0, 10, 0, 100) == 0.0
	assert subsequence.sequence_utils.scale_clamp(15, 0, 10, 0, 100) == 100.0

def test_scale_clamp_reversed_output ():
	"""Test output range min > max (inverted logic)."""
	# Input 0 should map to 100, Input 10 to 0
	# 0 -> 100
	assert subsequence.sequence_utils.scale_clamp(0, 0, 10, 100, 0) == 100.0
	# 10 -> 0
	assert subsequence.sequence_utils.scale_clamp(10, 0, 10, 100, 0) == 0.0
	# 5 -> 50
	assert subsequence.sequence_utils.scale_clamp(5, 0, 10, 100, 0) == 50.0
	
	# Clamping check: -5 (below input min) should map to output 'start' (100)
	assert subsequence.sequence_utils.scale_clamp(-5, 0, 10, 100, 0) == 100.0
	# Clamping check: 15 (above input max) should map to output 'end' (0)
	assert subsequence.sequence_utils.scale_clamp(15, 0, 10, 100, 0) == 0.0

def test_scale_clamp_reversed_input ():
	"""Test input range min > max."""
	# Input range 10 down to 0 mapping to 0-100
	# 10 -> 0, 0 -> 100
	assert subsequence.sequence_utils.scale_clamp(10, 10, 0, 0, 100) == 0.0
	assert subsequence.sequence_utils.scale_clamp(0, 10, 0, 0, 100) == 100.0
	
def test_scale_clamp_zero_width ():
	"""Test zero-width input range raises error."""
	with pytest.raises(ValueError):
		subsequence.sequence_utils.scale_clamp(5, 10, 10, 0, 100)

def test_scale_clamp_floats ():
	"""Test with float values."""
	val = subsequence.sequence_utils.scale_clamp(0.5, 0.0, 1.0, 0.0, 10.0)
	assert abs(val - 5.0) < 0.000001
