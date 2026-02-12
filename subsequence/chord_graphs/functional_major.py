import typing

import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = 6
WEIGHT_MEDIUM = 4
WEIGHT_COMMON = 3
WEIGHT_WEAK = 1
WEIGHT_DECEPTIVE = 2


def build_graph (key_name: str, include_dominant_7th: bool = True, minor_turnaround_weight: float = 0.0) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

	"""
	Build a functional major-key graph and return it with the tonic chord.
	"""

	if key_name not in subsequence.chords.NOTE_NAME_TO_PC:
		raise ValueError(f"Unknown key name: {key_name}")

	key_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
	scale_intervals = [0, 2, 4, 5, 7, 9, 11]
	degree_qualities = ["major", "minor", "minor", "major", "major", "minor", "diminished"]

	chords: typing.List[subsequence.chords.Chord] = []

	for degree, quality in enumerate(degree_qualities):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		chords.append(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

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

	if include_dominant_7th:
		# Decision path: optional dominant seventh color for stronger cadences.
		dominant_7th = subsequence.chords.Chord(root_pc=dominant.root_pc, quality="dominant_7th")

		graph.add_transition(dominant, dominant_7th, WEIGHT_WEAK)
		graph.add_transition(dominant_7th, tonic, WEIGHT_STRONG)
		graph.add_transition(dominant_7th, submediant, WEIGHT_DECEPTIVE)

	return graph, tonic
