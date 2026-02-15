import pytest

import subsequence.chord_graphs
import subsequence.chord_graphs.aeolian_minor
import subsequence.chord_graphs.phrygian_minor
import subsequence.chord_graphs.functional_major
import subsequence.chord_graphs.turnaround_global
import subsequence.chords
import subsequence.harmonic_state


def test_aeolian_minor_phrygian_cadence () -> None:

	"""The aeolian minor graph should include a bII to i (Phrygian cadence) edge."""

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor()
	graph, tonic = graph_obj.build("A")

	# bII of A minor is Bb major (root_pc=10+1=11? No: A=9, bII = 9+1=10 = Bb)
	flat_two = subsequence.chords.Chord(root_pc=10, quality="major")

	transitions = graph.get_transitions(flat_two)

	assert any(chord == tonic for chord, _ in transitions)


def test_aeolian_minor_authentic_cadence () -> None:

	"""The aeolian minor graph should include a V to i edge."""

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor()
	graph, tonic = graph_obj.build("A")

	# V of A minor is E major (root_pc=4)
	dominant = subsequence.chords.Chord(root_pc=4, quality="major")

	transitions = graph.get_transitions(dominant)

	assert any(chord == tonic for chord, _ in transitions)


def test_aeolian_minor_plagal () -> None:

	"""The aeolian minor graph should include an iv to i edge."""

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor()
	graph, tonic = graph_obj.build("A")

	# iv of A minor is D minor (root_pc=2)
	subdominant = subsequence.chords.Chord(root_pc=2, quality="minor")

	transitions = graph.get_transitions(subdominant)

	assert any(chord == tonic for chord, _ in transitions)


def test_aeolian_minor_tonic_is_minor () -> None:

	"""The aeolian minor tonic should be a minor chord."""

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor()
	_, tonic = graph_obj.build("A")

	assert tonic.quality == "minor"
	assert tonic.root_pc == 9


def test_aeolian_minor_gravity_sets () -> None:

	"""The aeolian minor gravity sets should include minor-key chords."""

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor()
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


def test_aeolian_minor_no_dead_ends () -> None:

	"""Every chord reachable in the aeolian minor graph should have at least one outgoing transition."""

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor(include_dominant_7th=True)
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

	graph_obj = subsequence.chord_graphs.aeolian_minor.AeolianMinor(include_dominant_7th=True)

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

	state_aeolian = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="aeolian_minor")

	assert state_aeolian.current_chord.quality == "minor"

	state_phrygian = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="phrygian_minor")

	assert state_phrygian.current_chord.quality == "minor"


def test_harmonic_state_legacy_aliases () -> None:

	"""HarmonicState should still accept old string names as aliases."""

	state_fm = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	assert state_fm.current_chord.quality == "major"

	state_tg = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="turnaround_global")

	assert state_tg.current_chord.quality == "major"

	# These are now aliases to the new graphs.
	state_dm = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="dark_minor")
	assert state_dm.current_chord.quality == "minor"

	state_dt = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="dark_techno")
	assert state_dt.current_chord.quality == "minor"


def test_phrygian_minor_all_chords_are_minor () -> None:

	"""Every chord in the phrygian_minor graph must be minor quality."""

	graph_obj = subsequence.chord_graphs.phrygian_minor.PhrygianMinor()
	graph, tonic = graph_obj.build("E")

	# Walk every reachable chord and verify quality.
	visited = set()
	queue = [tonic]

	while queue:
		current = queue.pop(0)

		if current in visited:
			continue

		visited.add(current)

		assert current.quality == "minor", f"{current} is {current.quality}, expected minor"

		for target, _ in graph.get_transitions(current):

			if target not in visited:
				queue.append(target)

	assert len(visited) == 4


def test_phrygian_minor_tonic () -> None:

	"""The phrygian_minor tonic should be a minor chord on the key root."""

	graph_obj = subsequence.chord_graphs.phrygian_minor.PhrygianMinor()
	_, tonic = graph_obj.build("E")

	assert tonic.quality == "minor"
	assert tonic.root_pc == 4


def test_phrygian_minor_phrygian_cadence () -> None:

	"""The phrygian_minor graph should include a bii to i Phrygian cadence."""

	graph_obj = subsequence.chord_graphs.phrygian_minor.PhrygianMinor()
	graph, tonic = graph_obj.build("E")

	# bii of E minor is F minor (root_pc=5).
	flat_two = subsequence.chords.Chord(root_pc=5, quality="minor")

	transitions = graph.get_transitions(flat_two)

	assert any(chord == tonic for chord, _ in transitions)


def test_phrygian_minor_gravity_sets () -> None:

	"""Gravity sets should contain only minor chords."""

	graph_obj = subsequence.chord_graphs.phrygian_minor.PhrygianMinor()
	diatonic, functional = graph_obj.gravity_sets("E")

	for chord in diatonic:
		assert chord.quality == "minor"

	for chord in functional:
		assert chord.quality == "minor"

	# Tonic should be in both.
	tonic = subsequence.chords.Chord(root_pc=4, quality="minor")

	assert tonic in diatonic
	assert tonic in functional

	# bii should be in functional.
	flat_two = subsequence.chords.Chord(root_pc=5, quality="minor")

	assert flat_two in functional


def test_phrygian_minor_no_dead_ends () -> None:

	"""Every chord in the phrygian_minor graph should have outgoing transitions."""

	graph_obj = subsequence.chord_graphs.phrygian_minor.PhrygianMinor()
	graph, tonic = graph_obj.build("E")

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


def test_phrygian_minor_string_name () -> None:

	"""HarmonicState should accept 'phrygian_minor' as a style string."""

	state = subsequence.harmonic_state.HarmonicState(key_name="E", graph_style="phrygian_minor")

	assert state.current_chord.quality == "minor"


def test_unknown_string_raises () -> None:

	"""An unknown graph style string should raise ValueError."""

	with pytest.raises(ValueError, match="Unknown graph style"):
		subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="nonexistent")
