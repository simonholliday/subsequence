import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STEP = 4
WEIGHT_THIRD = 3
WEIGHT_LEAP = 2


class WholeTone (subsequence.chord_graphs.ChordGraph):

	"""Symmetrical whole-tone chord graph.

	Scale: 0, 2, 4, 6, 8, 10 (six equally-spaced pitches).
	All chords are augmented triads. Every position is equivalent —
	there is no functional hierarchy, only proximity.

	Step-wise motion (whole step) is weighted highest, thirds next,
	larger leaps lowest. The result is a drifting, dreamlike quality
	with no sense of resolution. Useful for IDM, ambient, and
	experimental electronic music.
	"""

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a fully-connected whole-tone graph."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Six augmented triads, each a whole step apart.
		roots = [(key_pc + i) % 12 for i in range(0, 12, 2)]
		chords = [subsequence.chords.Chord(root_pc=r, quality="augmented") for r in roots]

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# Fully connected: every chord links to every other chord.
		for i, source in enumerate(chords):
			for j, target in enumerate(chords):
				if i == j:
					continue

				# Distance in whole-tone steps (1-3, since the scale is symmetric).
				step_distance = min(abs(i - j), 6 - abs(i - j))

				if step_distance == 1:
					weight = WEIGHT_STEP
				elif step_distance == 2:
					weight = WEIGHT_THIRD
				else:
					weight = WEIGHT_LEAP

				graph.add_transition(source, target, weight)

		tonic = chords[0]

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return whole-tone diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		roots = [(key_pc + i) % 12 for i in range(0, 12, 2)]
		diatonic: typing.Set[subsequence.chords.Chord] = set()

		for r in roots:
			diatonic.add(subsequence.chords.Chord(root_pc=r, quality="augmented"))

		# Minimal functional pull — only the tonic augmented chord.
		functional: typing.Set[subsequence.chords.Chord] = set()
		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="augmented"))

		return diatonic, functional
