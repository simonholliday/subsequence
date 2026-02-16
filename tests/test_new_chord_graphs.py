"""Tests for chord graph styles."""

import random

import pytest

import subsequence.chord_graphs
import subsequence.chord_graphs.chromatic_mediant
import subsequence.chord_graphs.diminished
import subsequence.chord_graphs.dorian_minor
import subsequence.chord_graphs.lydian_major
import subsequence.chord_graphs.mixolydian
import subsequence.chord_graphs.suspended
import subsequence.chord_graphs.whole_tone
import subsequence.chords
import subsequence.harmonic_state


# ---- Helpers ----

def _assert_no_dead_ends (graph_obj: subsequence.chord_graphs.ChordGraph, key: str) -> int:

	"""BFS from tonic - every reachable chord must have outgoing transitions. Returns node count."""

	graph, tonic = graph_obj.build(key)

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

	return len(visited)


def _assert_stepping_stable (style: str, key: str = "C", steps: int = 50) -> None:

	"""Calling step() many times should not raise."""

	state = subsequence.harmonic_state.HarmonicState(
		key_name = key,
		graph_style = style,
		key_gravity_blend = 0.8
	)

	rng = random.Random(42)
	state.rng = rng

	for _ in range(steps):
		state.step()


# ===========================================================================
# Lydian Major
# ===========================================================================

class TestLydianMajor:

	def test_tonic_is_major (self) -> None:

		"""Tonic should be a major chord on the key root."""

		graph_obj = subsequence.chord_graphs.lydian_major.LydianMajor()
		_, tonic = graph_obj.build("C")

		assert tonic.quality == "major"
		assert tonic.root_pc == 0

	def test_lydian_shimmer (self) -> None:

		"""The graph should include a II → I transition (the Lydian shimmer)."""

		graph_obj = subsequence.chord_graphs.lydian_major.LydianMajor()
		graph, tonic = graph_obj.build("C")

		# II of C Lydian is D major (root_pc=2).
		supertonic = subsequence.chords.Chord(root_pc=2, quality="major")

		transitions = graph.get_transitions(supertonic)

		assert any(chord == tonic for chord, _ in transitions)

	def test_no_natural_iv (self) -> None:

		"""The graph should not contain a natural IV chord (F major in key of C)."""

		graph_obj = subsequence.chord_graphs.lydian_major.LydianMajor()
		graph, tonic = graph_obj.build("C")

		natural_iv = subsequence.chords.Chord(root_pc=5, quality="major")

		# Walk all reachable chords.
		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			assert current != natural_iv, "Natural IV should not appear in a Lydian graph"

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.lydian_major.LydianMajor(include_dominant_7th=True)
		_assert_no_dead_ends(graph_obj, "C")

	def test_gravity_sets (self) -> None:

		"""Tonic should be in both diatonic and functional sets. II should be in functional."""

		graph_obj = subsequence.chord_graphs.lydian_major.LydianMajor()
		diatonic, functional = graph_obj.gravity_sets("C")

		tonic = subsequence.chords.Chord(root_pc=0, quality="major")

		assert tonic in diatonic
		assert tonic in functional

		# II (D major) - the Lydian signature - should be functional.
		supertonic = subsequence.chords.Chord(root_pc=2, quality="major")

		assert supertonic in functional

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'lydian_major' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="lydian_major")

		assert state.current_chord.quality == "major"

	def test_stepping_stable (self) -> None:

		"""Stepping 50 times should not raise any errors."""

		_assert_stepping_stable("lydian_major")


# ===========================================================================
# Dorian Minor
# ===========================================================================

class TestDorianMinor:

	def test_tonic_is_minor (self) -> None:

		"""Tonic should be a minor chord on the key root."""

		graph_obj = subsequence.chord_graphs.dorian_minor.DorianMinor()
		_, tonic = graph_obj.build("D")

		assert tonic.quality == "minor"
		assert tonic.root_pc == 2

	def test_dorian_iv_major (self) -> None:

		"""The graph should include a IV (major) → i transition."""

		graph_obj = subsequence.chord_graphs.dorian_minor.DorianMinor()
		graph, tonic = graph_obj.build("D")

		# IV of D Dorian is G major (root_pc=7).
		subdominant = subsequence.chords.Chord(root_pc=7, quality="major")

		transitions = graph.get_transitions(subdominant)

		assert any(chord == tonic for chord, _ in transitions)

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.dorian_minor.DorianMinor(include_dominant_7th=True)
		_assert_no_dead_ends(graph_obj, "D")

	def test_gravity_sets (self) -> None:

		"""Tonic should be in both sets. IV (major) should be in functional."""

		graph_obj = subsequence.chord_graphs.dorian_minor.DorianMinor()
		diatonic, functional = graph_obj.gravity_sets("D")

		tonic = subsequence.chords.Chord(root_pc=2, quality="minor")

		assert tonic in diatonic
		assert tonic in functional

		# IV (G major) should be in functional.
		subdominant = subsequence.chords.Chord(root_pc=7, quality="major")

		assert subdominant in functional

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'dorian_minor' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="D", graph_style="dorian_minor")

		assert state.current_chord.quality == "minor"

	def test_stepping_stable (self) -> None:

		"""Stepping 50 times should not raise any errors."""

		_assert_stepping_stable("dorian_minor", key="D")


# ===========================================================================
# Chromatic Mediant
# ===========================================================================

class TestChromaticMediant:

	def test_tonic_is_major (self) -> None:

		"""Tonic should be a major chord on the key root."""

		graph_obj = subsequence.chord_graphs.chromatic_mediant.ChromaticMediant()
		_, tonic = graph_obj.build("C")

		assert tonic.quality == "major"
		assert tonic.root_pc == 0

	def test_mediant_transition (self) -> None:

		"""The graph should include a bIII → I transition (third relation)."""

		graph_obj = subsequence.chord_graphs.chromatic_mediant.ChromaticMediant()
		graph, tonic = graph_obj.build("C")

		# bIII of C is Eb major (root_pc=3).
		flat_mediant = subsequence.chords.Chord(root_pc=3, quality="major")

		transitions = graph.get_transitions(flat_mediant)

		assert any(chord == tonic for chord, _ in transitions)

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.chromatic_mediant.ChromaticMediant()
		_assert_no_dead_ends(graph_obj, "C")

	def test_gravity_sets (self) -> None:

		"""Tonic and bIII should be in the functional set."""

		graph_obj = subsequence.chord_graphs.chromatic_mediant.ChromaticMediant()
		diatonic, functional = graph_obj.gravity_sets("C")

		tonic = subsequence.chords.Chord(root_pc=0, quality="major")

		assert tonic in diatonic
		assert tonic in functional

		flat_mediant = subsequence.chords.Chord(root_pc=3, quality="major")

		assert flat_mediant in functional

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'chromatic_mediant' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="chromatic_mediant")

		assert state.current_chord.quality == "major"

	def test_stepping_stable (self) -> None:

		"""Stepping 50 times should not raise any errors."""

		_assert_stepping_stable("chromatic_mediant")


# ===========================================================================
# Suspended
# ===========================================================================

class TestSuspended:

	def test_sus_chord_qualities_exist (self) -> None:

		"""sus2 and sus4 chord qualities should be defined."""

		assert "sus2" in subsequence.chords.CHORD_INTERVALS
		assert "sus4" in subsequence.chords.CHORD_INTERVALS

		assert subsequence.chords.CHORD_INTERVALS["sus2"] == [0, 2, 7]
		assert subsequence.chords.CHORD_INTERVALS["sus4"] == [0, 5, 7]

	def test_tonic_is_sus2 (self) -> None:

		"""Tonic should be a sus2 chord on the key root."""

		graph_obj = subsequence.chord_graphs.suspended.Suspended()
		_, tonic = graph_obj.build("A")

		assert tonic.quality == "sus2"
		assert tonic.root_pc == 9

	def test_colour_change (self) -> None:

		"""The graph should include a sus2 → sus4 colour change on the same root."""

		graph_obj = subsequence.chord_graphs.suspended.Suspended()
		graph, tonic = graph_obj.build("A")

		tonic_sus4 = subsequence.chords.Chord(root_pc=9, quality="sus4")
		transitions = graph.get_transitions(tonic)

		assert any(chord == tonic_sus4 for chord, _ in transitions)

	def test_minor_resolution (self) -> None:

		"""The graph should include a path to the minor tonic resolution chord."""

		graph_obj = subsequence.chord_graphs.suspended.Suspended()
		graph, tonic = graph_obj.build("A")

		tonic_minor = subsequence.chords.Chord(root_pc=9, quality="minor")

		# Walk all reachable chords and check that tonic_minor is reachable.
		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

		assert tonic_minor in visited, "Minor tonic should be reachable from the graph"

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.suspended.Suspended()
		_assert_no_dead_ends(graph_obj, "A")

	def test_gravity_sets (self) -> None:

		"""Tonic sus2/sus4 and minor should be in the functional set."""

		graph_obj = subsequence.chord_graphs.suspended.Suspended()
		diatonic, functional = graph_obj.gravity_sets("A")

		tonic_sus2 = subsequence.chords.Chord(root_pc=9, quality="sus2")
		tonic_sus4 = subsequence.chords.Chord(root_pc=9, quality="sus4")
		tonic_minor = subsequence.chords.Chord(root_pc=9, quality="minor")

		assert tonic_sus2 in functional
		assert tonic_sus4 in functional
		assert tonic_minor in functional

		assert tonic_sus2 in diatonic
		assert tonic_sus4 in diatonic
		assert tonic_minor in diatonic

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'suspended' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="A", graph_style="suspended")

		assert state.current_chord.quality == "sus2"

	def test_stepping_stable (self) -> None:

		"""Stepping 50 times should not raise any errors."""

		_assert_stepping_stable("suspended", key="A")


# ===========================================================================
# Mixolydian
# ===========================================================================

class TestMixolydian:

	def test_tonic_is_major (self) -> None:

		"""Tonic should be a major chord on the key root."""

		graph_obj = subsequence.chord_graphs.mixolydian.Mixolydian()
		_, tonic = graph_obj.build("C")

		assert tonic.quality == "major"
		assert tonic.root_pc == 0

	def test_flat_seven_is_major (self) -> None:

		"""bVII should be a major chord (the Mixolydian signature)."""

		graph_obj = subsequence.chord_graphs.mixolydian.Mixolydian()
		graph, tonic = graph_obj.build("C")

		# bVII of C is Bb major (root_pc=10).
		flat_seven = subsequence.chords.Chord(root_pc=10, quality="major")

		transitions = graph.get_transitions(tonic)

		assert any(chord == flat_seven for chord, _ in transitions)

	def test_no_dominant_major (self) -> None:

		"""v should be minor (not V major) - Mixolydian avoids dominant function."""

		graph_obj = subsequence.chord_graphs.mixolydian.Mixolydian()
		graph, tonic = graph_obj.build("C")

		# Walk all reachable chords - G major (root_pc=7) should not appear.
		dominant_major = subsequence.chords.Chord(root_pc=7, quality="major")

		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			assert current != dominant_major, "V major should not appear in a Mixolydian graph"

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.mixolydian.Mixolydian()
		_assert_no_dead_ends(graph_obj, "C")

	def test_gravity_sets (self) -> None:

		"""Diatonic set should have 7 chords. Functional should include I, IV, bVII."""

		graph_obj = subsequence.chord_graphs.mixolydian.Mixolydian()
		diatonic, functional = graph_obj.gravity_sets("C")

		assert len(diatonic) == 7

		tonic = subsequence.chords.Chord(root_pc=0, quality="major")
		subdominant = subsequence.chords.Chord(root_pc=5, quality="major")
		flat_seven = subsequence.chords.Chord(root_pc=10, quality="major")

		assert tonic in functional
		assert subdominant in functional
		assert flat_seven in functional

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'mixolydian' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="mixolydian")

		assert state.current_chord.quality == "major"

	def test_stepping_stable (self) -> None:

		"""Stepping 100 times should not raise any errors."""

		_assert_stepping_stable("mixolydian", steps=100)


# ===========================================================================
# Whole Tone
# ===========================================================================

class TestWholeTone:

	def test_all_augmented (self) -> None:

		"""Every chord in the graph should be augmented quality."""

		graph_obj = subsequence.chord_graphs.whole_tone.WholeTone()
		graph, tonic = graph_obj.build("C")

		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			assert current.quality == "augmented", f"Expected augmented, got {current.quality}"

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

	def test_six_chords (self) -> None:

		"""The graph should contain exactly 6 chords."""

		graph_obj = subsequence.chord_graphs.whole_tone.WholeTone()
		count = _assert_no_dead_ends(graph_obj, "C")

		assert count == 6

	def test_fully_connected (self) -> None:

		"""Every chord should have edges to all 5 other chords."""

		graph_obj = subsequence.chord_graphs.whole_tone.WholeTone()
		graph, tonic = graph_obj.build("C")

		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			transitions = graph.get_transitions(current)

			assert len(transitions) == 5, f"Expected 5 transitions, got {len(transitions)}"

			for target, _ in transitions:

				if target not in visited:
					queue.append(target)

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.whole_tone.WholeTone()
		_assert_no_dead_ends(graph_obj, "C")

	def test_gravity_sets (self) -> None:

		"""Diatonic set should have 6 chords. Functional should have 1 (tonic only)."""

		graph_obj = subsequence.chord_graphs.whole_tone.WholeTone()
		diatonic, functional = graph_obj.gravity_sets("C")

		assert len(diatonic) == 6
		assert len(functional) == 1

		tonic = subsequence.chords.Chord(root_pc=0, quality="augmented")

		assert tonic in diatonic
		assert tonic in functional

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'whole_tone' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="whole_tone")

		assert state.current_chord.quality == "augmented"

	def test_stepping_stable (self) -> None:

		"""Stepping 100 times should not raise any errors."""

		_assert_stepping_stable("whole_tone", steps=100)


# ===========================================================================
# Diminished
# ===========================================================================

class TestDiminished:

	def test_diminished_count (self) -> None:

		"""The graph should contain 4 diminished chords."""

		graph_obj = subsequence.chord_graphs.diminished.Diminished()
		graph, tonic = graph_obj.build("C")

		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

		dim_count = sum(1 for c in visited if c.quality == "diminished")

		assert dim_count == 4

	def test_dominant_count (self) -> None:

		"""The graph should contain 4 dominant 7th chords."""

		graph_obj = subsequence.chord_graphs.diminished.Diminished()
		graph, tonic = graph_obj.build("C")

		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

		dom_count = sum(1 for c in visited if c.quality == "dominant_7th")

		assert dom_count == 4

	def test_symmetry (self) -> None:

		"""Diminished chord roots should be 3 semitones apart (minor third symmetry)."""

		graph_obj = subsequence.chord_graphs.diminished.Diminished()
		_, tonic = graph_obj.build("C")

		# In key of C, diminished roots should be 0, 3, 6, 9.
		expected_roots = {0, 3, 6, 9}

		graph, _ = graph_obj.build("C")

		visited = set()
		queue = [tonic]

		while queue:
			current = queue.pop(0)

			if current in visited:
				continue

			visited.add(current)

			for target, _ in graph.get_transitions(current):

				if target not in visited:
					queue.append(target)

		dim_roots = {c.root_pc for c in visited if c.quality == "diminished"}

		assert dim_roots == expected_roots

	def test_no_dead_ends (self) -> None:

		"""Every chord reachable in the graph should have outgoing transitions."""

		graph_obj = subsequence.chord_graphs.diminished.Diminished()
		_assert_no_dead_ends(graph_obj, "C")

	def test_gravity_sets (self) -> None:

		"""Diatonic should have 8 chords. Functional should be the 4 diminished chords."""

		graph_obj = subsequence.chord_graphs.diminished.Diminished()
		diatonic, functional = graph_obj.gravity_sets("C")

		assert len(diatonic) == 8
		assert len(functional) == 4

		# All functional chords should be diminished.
		for chord in functional:
			assert chord.quality == "diminished"

	def test_string_name (self) -> None:

		"""HarmonicState should accept 'diminished' as a style string."""

		state = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="diminished")

		assert state.current_chord.quality == "diminished"

	def test_stepping_stable (self) -> None:

		"""Stepping 100 times should not raise any errors."""

		_assert_stepping_stable("diminished", steps=100)
