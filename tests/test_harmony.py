import pytest

import subsequence.chord_graphs.functional_major
import subsequence.chords
import subsequence.harmony


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


def test_key_gravity_blend_changes_weights () -> None:

	"""
	Key gravity blend should alter transition probabilities between chord sets.
	"""

	graph, tonic = subsequence.chord_graphs.functional_major.build_graph("E", include_dominant_7th=True)
	diatonic, function_chords = subsequence.harmony._get_key_gravity_sets("E")

	diatonic_only = 1.0
	function_only = 0.0

	def modifier_diatonic (
		source: subsequence.chords.Chord,
		target: subsequence.chords.Chord,
		weight: int
	) -> float:

		is_function = 1.0 if target in function_chords else 0.0
		is_diatonic = 1.0 if target in diatonic else 0.0

		boost = (1.0 - diatonic_only) * is_function + diatonic_only * is_diatonic

		return 1.0 + boost

	def modifier_function (
		source: subsequence.chords.Chord,
		target: subsequence.chords.Chord,
		weight: int
	) -> float:

		is_function = 1.0 if target in function_chords else 0.0
		is_diatonic = 1.0 if target in diatonic else 0.0

		boost = (1.0 - function_only) * is_function + function_only * is_diatonic

		return 1.0 + boost

	source = tonic
	options = graph.get_transitions(source)
	assert options

	target_function = next(chord for chord, _ in options if chord in function_chords)
	target_diatonic = next(chord for chord, _ in options if chord in diatonic and chord not in function_chords)

	function_weight = next(weight for chord, weight in options if chord == target_function)
	diatonic_weight = next(weight for chord, weight in options if chord == target_diatonic)

	diatonic_adjusted = diatonic_weight * modifier_diatonic(source, target_diatonic, diatonic_weight)
	function_adjusted = function_weight * modifier_function(source, target_function, function_weight)

	assert diatonic_adjusted > diatonic_weight
	assert function_adjusted > function_weight
