import subsequence.motif


def test_motif_to_pattern () -> None:

	"""
	Motif rendering should create pattern steps at expected pulses.
	"""

	motif = subsequence.motif.Motif(pulses_per_beat=24)
	motif.add_note_beats(beat_position=0.0, pitch=60, velocity=100, duration_beats=1.0)
	motif.add_note_beats(beat_position=1.0, pitch=62, velocity=100, duration_beats=1.0)

	assert motif.get_length_beats() == 2

	pattern = motif.to_pattern(channel=0)

	assert 0 in pattern.steps
	assert 24 in pattern.steps
