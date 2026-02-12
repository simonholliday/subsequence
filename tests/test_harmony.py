import pytest

import subsequence.chord_graphs.functional_major
import subsequence.chords


def test_dominant_7th_included () -> None:

	"""
	Dominant seventh should appear when enabled and resolve to tonic.
	"""

	graph, tonic = subsequence.chord_graphs.functional_major.build_graph("E", include_dominant_7th=True)

	dominant = subsequence.chords.Chord(root_pc=11, quality="major")
	dominant_7th = subsequence.chords.Chord(root_pc=11, quality="dominant_7th")

	transitions = graph.get_transitions(dominant)
	assert any(chord == dominant_7th for chord, _ in transitions)

	transitions_7th = graph.get_transitions(dominant_7th)
	assert any(chord == tonic for chord, _ in transitions_7th)


def test_invalid_key_name () -> None:

	"""
	Invalid key names should raise an error.
	"""

	with pytest.raises(ValueError):
		subsequence.chord_graphs.functional_major.build_graph("H", include_dominant_7th=True)
