import subsequence.intervals


def test_get_intervals () -> None:

	"""
	Interval lookup should return a known definition.
	"""

	assert subsequence.intervals.get_intervals("major_triad") == [0, 4, 7]


def test_get_diatonic_intervals () -> None:

	"""
	Diatonic chord construction should return the expected tonic triad.
	"""

	major_scale = [0, 2, 4, 5, 7, 9, 11]
	chords = subsequence.intervals.get_diatonic_intervals(major_scale)

	assert chords[0] == [0, 4, 7]
