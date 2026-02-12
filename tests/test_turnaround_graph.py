import pytest

import subsequence.chord_graphs.turnaround_global
import subsequence.chords


def test_turnaround_edges_present () -> None:

	"""
	Turnaround graph should include ii->V7->I in the chosen key.
	"""

	graph, tonic = subsequence.chord_graphs.turnaround_global.build_graph(
		key_name = "C",
		include_dominant_7th = True,
		minor_turnaround_weight = 0.0
	)

	supertonic = subsequence.chords.Chord(root_pc=2, quality="minor")
	dominant_7th = subsequence.chords.Chord(root_pc=7, quality="dominant_7th")

	transitions = graph.get_transitions(supertonic)
	assert any(chord == dominant_7th for chord, _ in transitions)

	transitions_7th = graph.get_transitions(dominant_7th)
	assert any(chord == tonic for chord, _ in transitions_7th)


def test_minor_turnaround_weight_toggle () -> None:

	"""
	Minor turnarounds should appear only when weight is enabled.
	"""

	graph_disabled, _ = subsequence.chord_graphs.turnaround_global.build_graph(
		key_name = "A",
		include_dominant_7th = True,
		minor_turnaround_weight = 0.0
	)

	supertonic_half_dim = subsequence.chords.Chord(root_pc=2, quality="half_diminished_7th")
	transitions_disabled = graph_disabled.get_transitions(supertonic_half_dim)
	assert transitions_disabled == []

	graph_enabled, _ = subsequence.chord_graphs.turnaround_global.build_graph(
		key_name = "A",
		include_dominant_7th = True,
		minor_turnaround_weight = 0.5
	)

	transitions_enabled = graph_enabled.get_transitions(supertonic_half_dim)
	assert transitions_enabled != []
