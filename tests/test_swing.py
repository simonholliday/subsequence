import subsequence.swing


def test_apply_swing_moves_offbeat () -> None:

	"""
	An offbeat eighth should be delayed with swing applied.
	"""

	steps = {0: ["a"], 12: ["b"]}
	swung = subsequence.swing.apply_swing(steps, swing_ratio=2.0, pulses_per_quarter=24)

	assert 0 in swung
	assert 16 in swung
