import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_SYMMETRY = 5
WEIGHT_ESCAPE = 4
WEIGHT_RESOLVE = 4
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON


class Diminished (subsequence.chord_graphs.ChordGraph):

	"""Octatonic (diminished) chord graph with minor-third symmetry.

	Built on the half-whole diminished scale: 0, 1, 3, 4, 6, 7, 9, 10.
	Two chord types interlock:

	- 4 diminished triads at roots 0, 3, 6, 9 (the symmetry backbone)
	- 4 dominant 7th chords at roots 1, 4, 7, 10 (escape chords)

	Diminished chords connect to each other by minor thirds (the defining
	rotation). Dominant 7th chords sit a half step above each diminished
	chord, acting as tension points. The result is angular, disorienting,
	and cyclical - useful for dark techno, industrial, and experimental
	electronic music.
	"""

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build an octatonic graph with diminished and dominant 7th chords."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Four diminished triads, each a minor third apart.
		dim_roots = [(key_pc + i) % 12 for i in [0, 3, 6, 9]]
		dim_chords = [subsequence.chords.Chord(root_pc=r, quality="diminished") for r in dim_roots]

		# Four dominant 7th chords, each a half step above a diminished chord.
		dom_roots = [(key_pc + i) % 12 for i in [1, 4, 7, 10]]
		dom_chords = [subsequence.chords.Chord(root_pc=r, quality="dominant_7th") for r in dom_roots]

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- Diminished ↔ diminished (minor third rotation) ---
		for i, source in enumerate(dim_chords):
			for j, target in enumerate(dim_chords):
				if i != j:
					graph.add_transition(source, target, WEIGHT_SYMMETRY)

		# --- Diminished → dominant 7th (half step up = escape) ---
		for i in range(4):
			graph.add_transition(dim_chords[i], dom_chords[i], WEIGHT_ESCAPE)

		# --- Dominant 7th → diminished (half step down = resolve) ---
		for i in range(4):
			graph.add_transition(dom_chords[i], dim_chords[i], WEIGHT_RESOLVE)

		# --- Dominant 7th ↔ dominant 7th (minor third rotation) ---
		for i, source in enumerate(dom_chords):
			for j, target in enumerate(dom_chords):
				if i != j:
					graph.add_transition(source, target, WEIGHT_COMMON)

		tonic = dim_chords[0]

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return octatonic diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		diatonic: typing.Set[subsequence.chords.Chord] = set()

		# All 8 chords are diatonic to the octatonic scale.
		for i in [0, 3, 6, 9]:
			diatonic.add(subsequence.chords.Chord(root_pc=(key_pc + i) % 12, quality="diminished"))

		for i in [1, 4, 7, 10]:
			diatonic.add(subsequence.chords.Chord(root_pc=(key_pc + i) % 12, quality="dominant_7th"))

		# Functional: the 4 diminished chords (symmetry backbone).
		functional: typing.Set[subsequence.chords.Chord] = set()

		for i in [0, 3, 6, 9]:
			functional.add(subsequence.chords.Chord(root_pc=(key_pc + i) % 12, quality="diminished"))

		return diatonic, functional
