import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.intervals
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_DECEPTIVE = subsequence.chord_graphs.WEIGHT_DECEPTIVE
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK


class DiatonicMajor (subsequence.chord_graphs.ChordGraph):

	"""Single-key functional major harmony graph."""

	def __init__ (self, include_dominant_7th: bool = True) -> None:

		"""Configure whether to include dominant seventh chords."""

		self.include_dominant_7th = include_dominant_7th

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build the graph for a given major key."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		chords = subsequence.chord_graphs.build_diatonic_chords(
			key_pc,
			subsequence.intervals.get_intervals("major_ionian"),
			subsequence.intervals.IONIAN_QUALITIES
		)

		tonic = chords[0]
		supertonic = chords[1]
		mediant = chords[2]
		subdominant = chords[3]
		dominant = chords[4]
		submediant = chords[5]
		leading = chords[6]

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		graph.add_transition(tonic, subdominant, WEIGHT_COMMON)
		graph.add_transition(tonic, dominant, WEIGHT_COMMON)
		graph.add_transition(tonic, submediant, WEIGHT_COMMON)
		graph.add_transition(tonic, supertonic, WEIGHT_WEAK)

		graph.add_transition(supertonic, dominant, WEIGHT_STRONG)

		graph.add_transition(mediant, submediant, WEIGHT_COMMON)
		graph.add_transition(mediant, subdominant, WEIGHT_WEAK)

		graph.add_transition(subdominant, dominant, WEIGHT_STRONG)
		graph.add_transition(subdominant, supertonic, WEIGHT_COMMON)

		graph.add_transition(dominant, tonic, WEIGHT_STRONG)
		graph.add_transition(dominant, submediant, WEIGHT_DECEPTIVE)

		graph.add_transition(submediant, supertonic, WEIGHT_COMMON)
		graph.add_transition(submediant, subdominant, WEIGHT_COMMON)
		graph.add_transition(submediant, dominant, WEIGHT_WEAK)

		graph.add_transition(leading, tonic, WEIGHT_STRONG)

		if self.include_dominant_7th:
			# Decision path: optional dominant seventh color for stronger cadences.
			dominant_7th = subsequence.chords.Chord(root_pc=dominant.root_pc, quality="dominant_7th")

			graph.add_transition(dominant, dominant_7th, WEIGHT_WEAK)
			graph.add_transition(dominant_7th, tonic, WEIGHT_STRONG)
			graph.add_transition(dominant_7th, submediant, WEIGHT_DECEPTIVE)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return major-key diatonic and functional chord sets."""

		return subsequence.chord_graphs._major_key_gravity_sets(key_name)


def build_graph (key_name: str, include_dominant_7th: bool = True, minor_turnaround_weight: float = 0.0) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

	"""Build a functional major-key graph and return it with the tonic chord."""

	graph_obj = DiatonicMajor(include_dominant_7th=include_dominant_7th)

	return graph_obj.build(key_name)
