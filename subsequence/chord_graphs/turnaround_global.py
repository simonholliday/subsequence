import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_DECEPTIVE = subsequence.chord_graphs.WEIGHT_DECEPTIVE
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK


def _build_major_key_chords (key_pc: int) -> typing.Dict[str, subsequence.chords.Chord]:

	"""Return common functional chords for a major key root."""

	scale_intervals = [0, 2, 4, 5, 7, 9, 11]
	degree_qualities = ["major", "minor", "minor", "major", "major", "minor", "diminished"]

	chords: typing.List[subsequence.chords.Chord] = []

	for degree, quality in enumerate(degree_qualities):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		chords.append(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

	return {
		"I": chords[0],
		"ii": chords[1],
		"iii": chords[2],
		"IV": chords[3],
		"V": chords[4],
		"vi": chords[5],
		"vii": chords[6],
	}


def _add_turnaround_edges (
	graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord],
	chords: typing.Dict[str, subsequence.chords.Chord],
	include_dominant_7th: bool
) -> None:

	"""Add ii-V-I style edges for a single major key."""

	tonic = chords["I"]
	supertonic = chords["ii"]
	submediant = chords["vi"]
	subdominant = chords["IV"]
	dominant = chords["V"]
	dominant_7th = subsequence.chords.Chord(root_pc=dominant.root_pc, quality="dominant_7th")

	# Decision path: allow the dominant seventh to drive stronger resolutions.
	dominant_target = dominant_7th if include_dominant_7th else dominant

	graph.add_transition(tonic, submediant, WEIGHT_COMMON)
	graph.add_transition(submediant, supertonic, WEIGHT_COMMON)
	graph.add_transition(supertonic, dominant_target, WEIGHT_STRONG)
	graph.add_transition(dominant_target, tonic, WEIGHT_STRONG)

	graph.add_transition(tonic, subdominant, WEIGHT_MEDIUM)
	graph.add_transition(tonic, dominant, WEIGHT_MEDIUM)

	if include_dominant_7th:
		# Decision path: deceptive resolution only applies to dominant sevenths.
		graph.add_transition(dominant_7th, submediant, WEIGHT_DECEPTIVE)


def _add_minor_turnaround (
	graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord],
	key_pc: int,
	minor_turnaround_weight: float,
	include_dominant_7th: bool
) -> None:

	"""Add a minor ii-V-I turnaround using a weight multiplier."""

	if minor_turnaround_weight <= 0:
		# Decision path: weight of zero disables minor turnarounds entirely.
		return

	scale_intervals = [0, 2, 3, 5, 7, 8, 10]
	supertonic_pc = (key_pc + scale_intervals[1]) % 12
	dominant_pc = (key_pc + scale_intervals[4]) % 12
	tonic_pc = key_pc % 12

	supertonic = subsequence.chords.Chord(root_pc=supertonic_pc, quality="half_diminished_7th")
	dominant_7th = subsequence.chords.Chord(root_pc=dominant_pc, quality="dominant_7th")
	tonic_minor = subsequence.chords.Chord(root_pc=tonic_pc, quality="minor")

	minor_weight_strong = max(1, int(round(WEIGHT_STRONG * minor_turnaround_weight)))

	if include_dominant_7th:
		graph.add_transition(supertonic, dominant_7th, minor_weight_strong)
		graph.add_transition(dominant_7th, tonic_minor, minor_weight_strong)

	else:
		# Decision path: if dominant sevenths are disabled, resolve via the triad.
		dominant = subsequence.chords.Chord(root_pc=dominant_pc, quality="major")
		graph.add_transition(supertonic, dominant, minor_weight_strong)
		graph.add_transition(dominant, tonic_minor, minor_weight_strong)


class TurnaroundModulation (subsequence.chord_graphs.ChordGraph):

	"""Global ii-V-I turnaround graph enabling modulation between all keys."""

	def __init__ (self, include_dominant_7th: bool = True, minor_turnaround_weight: float = 0.0) -> None:

		"""Configure dominant sevenths and minor turnaround strength."""

		if minor_turnaround_weight < 0 or minor_turnaround_weight > 1:
			raise ValueError("Minor turnaround weight must be between 0 and 1")

		self.include_dominant_7th = include_dominant_7th
		self.minor_turnaround_weight = minor_turnaround_weight

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build the global turnaround graph for all 12 keys."""

		if key_name not in subsequence.chords.NOTE_NAME_TO_PC:
			raise ValueError(f"Unknown key name: {key_name}")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		for key_pc in range(12):
			chords = _build_major_key_chords(key_pc)
			_add_turnaround_edges(graph, chords, self.include_dominant_7th)
			_add_minor_turnaround(graph, key_pc, self.minor_turnaround_weight, self.include_dominant_7th)

		tonic_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
		tonic = subsequence.chords.Chord(root_pc=tonic_pc, quality="major")

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return major-key diatonic and functional chord sets."""

		return subsequence.chord_graphs._major_key_gravity_sets(key_name)


def build_graph (key_name: str, include_dominant_7th: bool = True, minor_turnaround_weight: float = 0.0) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

	"""Build a global turnaround graph and return it with the chosen key tonic."""

	graph_obj = TurnaroundModulation(
		include_dominant_7th = include_dominant_7th,
		minor_turnaround_weight = minor_turnaround_weight
	)

	return graph_obj.build(key_name)
