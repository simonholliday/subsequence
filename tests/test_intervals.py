import subsequence
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


def test_scale_notes_range_c_major () -> None:

	"""C major from C4 to C5 should return all 8 notes."""

	result = subsequence.scale_notes("C", "ionian", low=60, high=72)
	assert result == [60, 62, 64, 65, 67, 69, 71, 72]


def test_scale_notes_range_e_minor () -> None:

	"""E natural minor (aeolian) from E2 to E3 should return one octave."""

	result = subsequence.scale_notes("E", "aeolian", low=40, high=52)
	assert result == [40, 42, 43, 45, 47, 48, 50, 52]


def test_scale_notes_count_one_octave () -> None:

	"""count=8 from C4 should match range C4–C5."""

	result = subsequence.scale_notes("C", "ionian", low=60, count=8)
	assert result == [60, 62, 64, 65, 67, 69, 71, 72]


def test_scale_notes_count_multi_octave () -> None:

	"""count=15 should continue ascending into higher octaves."""

	result = subsequence.scale_notes("C", "ionian", low=60, count=15)
	assert len(result) == 15
	assert result[0] == 60
	assert result[7] == 72  # C5 — octave above start
	assert result[14] == 84  # C6 — two octaves above C4


def test_scale_notes_pentatonic () -> None:

	"""Major pentatonic has 5 notes per octave."""

	result = subsequence.scale_notes("C", "major_pentatonic", low=60, high=72)
	assert result == [60, 62, 64, 67, 69, 72]


def test_scale_notes_custom_scale () -> None:

	"""Custom registered scales should work with scale_notes()."""

	subsequence.register_scale("test_wholetone_sn", [0, 2, 4, 6, 8, 10])
	result = subsequence.scale_notes("C", "test_wholetone_sn", low=60, high=71)
	assert result == [60, 62, 64, 66, 68, 70]


def test_scale_notes_exported_at_package_level () -> None:

	"""scale_notes should be importable directly from subsequence."""

	assert callable(subsequence.scale_notes)
