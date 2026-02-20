import pytest

import subsequence.chord_graphs.functional_major
import subsequence.chords
import subsequence.harmony
import subsequence.harmonic_state
import subsequence.intervals


# ---------------------------------------------------------------------------
# diatonic_chords() tests
# ---------------------------------------------------------------------------

def test_diatonic_chords_c_major () -> None:

	"""C Ionian should produce the standard major-key triads."""

	chords = subsequence.harmony.diatonic_chords("C", mode="ionian")

	assert len(chords) == 7

	# Root pitch classes: C D E F G A B = 0 2 4 5 7 9 11
	expected_pcs = [0, 2, 4, 5, 7, 9, 11]
	expected_qualities = subsequence.intervals.IONIAN_QUALITIES

	for chord, pc, quality in zip(chords, expected_pcs, expected_qualities):
		assert chord.root_pc == pc
		assert chord.quality == quality


def test_diatonic_chords_major_alias () -> None:

	"""'major' should be an alias for 'ionian'."""

	assert subsequence.harmony.diatonic_chords("C", "major") == subsequence.harmony.diatonic_chords("C", "ionian")


def test_diatonic_chords_minor_alias () -> None:

	"""'minor' should be an alias for 'aeolian'."""

	assert subsequence.harmony.diatonic_chords("A", "minor") == subsequence.harmony.diatonic_chords("A", "aeolian")


def test_diatonic_chords_a_minor () -> None:

	"""A Aeolian should produce natural minor triads."""

	chords = subsequence.harmony.diatonic_chords("A", mode="minor")

	assert len(chords) == 7

	# A natural minor: A B C D E F G = 9 11 0 2 4 5 7
	expected_pcs = [9, 11, 0, 2, 4, 5, 7]
	expected_qualities = subsequence.intervals.AEOLIAN_QUALITIES

	for chord, pc, quality in zip(chords, expected_pcs, expected_qualities):
		assert chord.root_pc == pc
		assert chord.quality == quality


def test_diatonic_chords_all_modes () -> None:

	"""Every mode in the DIATONIC_MODE_MAP should return 7 chords without error."""

	for mode_name in subsequence.intervals.DIATONIC_MODE_MAP:
		chords = subsequence.harmony.diatonic_chords("C", mode=mode_name)
		assert len(chords) == 7, f"{mode_name} did not return 7 chords"


def test_diatonic_chords_invalid_mode () -> None:

	"""An unknown mode should raise ValueError."""

	with pytest.raises(ValueError, match="Unknown mode"):
		subsequence.harmony.diatonic_chords("C", mode="bebop")


def test_diatonic_chords_invalid_key () -> None:

	"""An unknown key name should raise ValueError."""

	with pytest.raises(ValueError, match="Unknown key name"):
		subsequence.harmony.diatonic_chords("Z", mode="ionian")



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
	diatonic, function_chords = subsequence.chord_graphs.functional_major.DiatonicMajor().gravity_sets("E")

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
