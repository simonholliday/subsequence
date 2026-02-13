import pytest

import subsequence.chord_graphs
import subsequence.chord_graphs.dark_minor
import subsequence.chord_graphs.functional_major
import subsequence.chord_graphs.turnaround_global
import subsequence.chords
import subsequence.harmonic_state


def test_dark_minor_phrygian_cadence () -> None:

	"""The dark minor graph should include a bII to i (Phrygian cadence) edge."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor()
	graph, tonic = graph_obj.build("A")

	# bII of A minor is Bb major (root_pc=10+1=11? No: A=9, bII = 9+1=10 = Bb)
	flat_two = subsequence.chords.Chord(root_pc=10, quality="major")

	transitions = graph.get_transitions(flat_two)

	assert any(chord == tonic for chord, _ in transitions)


def test_dark_minor_authentic_cadence () -> None:

	"""The dark minor graph should include a V to i edge."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor()
	graph, tonic = graph_obj.build("A")

	# V of A minor is E major (root_pc=4)
	dominant = subsequence.chords.Chord(root_pc=4, quality="major")

	transitions = graph.get_transitions(dominant)

	assert any(chord == tonic for chord, _ in transitions)


def test_dark_minor_plagal () -> None:

	"""The dark minor graph should include an iv to i edge."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor()
	graph, tonic = graph_obj.build("A")

	# iv of A minor is D minor (root_pc=2)
	subdominant = subsequence.chords.Chord(root_pc=2, quality="minor")

	transitions = graph.get_transitions(subdominant)

	assert any(chord == tonic for chord, _ in transitions)


def test_dark_minor_tonic_is_minor () -> None:

	"""The dark minor tonic should be a minor chord."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor()
	_, tonic = graph_obj.build("A")

	assert tonic.quality == "minor"
	assert tonic.root_pc == 9


def test_dark_minor_gravity_sets () -> None:

	"""The dark minor gravity sets should include minor-key chords."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor()
	diatonic, functional = graph_obj.gravity_sets("A")

	# Tonic (Am) should be in both sets.
	tonic = subsequence.chords.Chord(root_pc=9, quality="minor")

	assert tonic in diatonic
	assert tonic in functional

	# bII (Bb major) should be in functional set.
	flat_two = subsequence.chords.Chord(root_pc=10, quality="major")

	assert flat_two in functional

	# V (E major) should be in functional set.
	dominant = subsequence.chords.Chord(root_pc=4, quality="major")

	assert dominant in functional


def test_dark_minor_no_dead_ends () -> None:

	"""Every chord reachable in the dark minor graph should have at least one outgoing transition."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor(include_dominant_7th=True)
	graph, tonic = graph_obj.build("A")

	# Walk every reachable chord via BFS from tonic.
	visited = set()
	queue = [tonic]

	while queue:
		current = queue.pop(0)

		if current in visited:
			continue

		visited.add(current)

		transitions = graph.get_transitions(current)

		assert len(transitions) > 0, f"Dead end: {current} has no outgoing transitions"

		for target, _ in transitions:

			if target not in visited:
				queue.append(target)


def test_harmonic_state_accepts_chord_graph_instance () -> None:

	"""HarmonicState should accept a ChordGraph instance directly."""

	graph_obj = subsequence.chord_graphs.dark_minor.DarkMinor(include_dominant_7th=True)

	state = subsequence.harmonic_state.HarmonicState(
		key_name = "E",
		graph_style = graph_obj,
		key_gravity_blend = 0.8
	)

	assert state.current_chord.quality == "minor"
	assert state.key_name == "E"


def test_harmonic_state_new_string_names () -> None:

	"""HarmonicState should accept the new canonical string names."""

	state_diatonic = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="diatonic_major")

	assert state_diatonic.current_chord.quality == "major"

	state_turnaround = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="turnaround")

	assert state_turnaround.current_chord.quality == "major"

	state_dark = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="dark_minor")

	assert state_dark.current_chord.quality == "minor"


def test_harmonic_state_legacy_aliases () -> None:

	"""HarmonicState should still accept old string names as aliases."""

	state_fm = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	assert state_fm.current_chord.quality == "major"

	state_tg = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="turnaround_global")

	assert state_tg.current_chord.quality == "major"


def test_unknown_string_raises () -> None:

	"""An unknown graph style string should raise ValueError."""

	with pytest.raises(ValueError, match="Unknown graph style"):
		subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="nonexistent")
