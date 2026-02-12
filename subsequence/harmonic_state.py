import random
import typing

import subsequence.chord_graphs.functional_major
import subsequence.chord_graphs.turnaround_global
import subsequence.chords
import subsequence.weighted_graph


GraphBuilderType = typing.Callable[
	[str, bool, float],
	typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]
]


GRAPH_BUILDERS: typing.Dict[str, GraphBuilderType] = {
	"functional_major": subsequence.chord_graphs.functional_major.build_graph,
	"turnaround_global": subsequence.chord_graphs.turnaround_global.build_graph,
}


def get_graph_builder (graph_style: str) -> GraphBuilderType:

	"""
	Return a chord graph builder by name.
	"""

	if graph_style not in GRAPH_BUILDERS:
		raise ValueError(f"Unknown graph style: {graph_style}")

	return GRAPH_BUILDERS[graph_style]


def _build_major_key_chords (key_name: str) -> typing.List[subsequence.chords.Chord]:

	"""
	Return diatonic triads for a major key.
	"""

	key_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
	scale_intervals = [0, 2, 4, 5, 7, 9, 11]
	degree_qualities = ["major", "minor", "minor", "major", "major", "minor", "diminished"]

	chords: typing.List[subsequence.chords.Chord] = []

	for degree, quality in enumerate(degree_qualities):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		chords.append(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

	return chords


def _get_key_gravity_sets (key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

	"""
	Return diatonic and functional chord sets for key gravity.
	"""

	diatonic = set(_build_major_key_chords(key_name))

	key_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
	scale_intervals = [0, 2, 5, 7]
	function_qualities = ["major", "minor", "major", "major"]

	function_chords: typing.Set[subsequence.chords.Chord] = set()

	for interval, quality in zip(scale_intervals, function_qualities):
		root_pc = (key_pc + interval) % 12
		function_chords.add(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

	# Decision path: include the dominant seventh as a functional and diatonic chord option.
	dominant_7th = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="dominant_7th")
	function_chords.add(dominant_7th)
	diatonic.add(dominant_7th)

	return diatonic, function_chords


class HarmonicState:

	"""
	Holds the current chord and key context for the composition.
	"""

	def __init__ (
		self,
		key_name: str,
		graph_style: str = "functional_major",
		include_dominant_7th: bool = True,
		key_gravity_blend: float = 1.0,
		minor_turnaround_weight: float = 0.0,
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""
		Initialize the harmonic state using a chord transition graph.
		"""

		if key_gravity_blend < 0 or key_gravity_blend > 1:
			raise ValueError("Key gravity blend must be between 0 and 1")

		if minor_turnaround_weight < 0 or minor_turnaround_weight > 1:
			raise ValueError("Minor turnaround weight must be between 0 and 1")

		self.key_name = key_name
		self.key_root_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
		self.key_gravity_blend = key_gravity_blend

		graph_builder = get_graph_builder(graph_style)
		self.graph, tonic = graph_builder(
			key_name = key_name,
			include_dominant_7th = include_dominant_7th,
			minor_turnaround_weight = minor_turnaround_weight
		)

		self._diatonic_chords, self._function_chords = _get_key_gravity_sets(self.key_name)

		self.rng = rng or random.Random()
		self.current_chord = tonic


	def step (self) -> subsequence.chords.Chord:

		"""
		Advance to the next chord based on the transition graph.
		"""

		def weight_modifier (
			source: subsequence.chords.Chord,
			target: subsequence.chords.Chord,
			weight: int
		) -> float:

			"""
			Blend functional vs diatonic key gravity for transition weights.
			"""

			is_function = 1.0 if target in self._function_chords else 0.0
			is_diatonic = 1.0 if target in self._diatonic_chords else 0.0

			# Decision path: blend controls whether key gravity favors functional or full diatonic chords.
			boost = (1.0 - self.key_gravity_blend) * is_function + self.key_gravity_blend * is_diatonic

			return 1.0 + boost

		# Decision path: chord changes occur here; key changes are not automatic.
		self.current_chord = self.graph.choose_next(self.current_chord, self.rng, weight_modifier=weight_modifier)

		return self.current_chord


	def get_current_chord (self) -> subsequence.chords.Chord:

		"""
		Return the current chord.
		"""

		return self.current_chord


	def get_key_name (self) -> str:

		"""
		Return the current key name.
		"""

		return self.key_name


	def get_chord_root_midi (self, base_midi: int, chord: subsequence.chords.Chord) -> int:

		"""
		Calculate the MIDI root for a chord relative to the key root.
		"""

		offset = (chord.root_pc - self.key_root_pc) % 12

		return base_midi + offset
