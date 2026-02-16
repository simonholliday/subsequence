import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK
WEIGHT_MIXOLYDIAN = 5


class Mixolydian (subsequence.chord_graphs.ChordGraph):

	"""Major-mode chord graph with a flat seventh degree.

	Scale: 1, 2, 3, 4, 5, 6, b7.
	Chords: I (major), ii (minor), iii° (diminished), IV (major),
	v (minor), vi (minor), bVII (major).

	The I ↔ bVII shuttle is the defining colour. The minor v avoids
	dominant function, keeping progressions open and unresolved.
	Common in EDM, synthwave, and rock-influenced electronic music.
	"""

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a Mixolydian mode graph."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		tonic = subsequence.chords.Chord(root_pc=key_pc, quality="major")
		supertonic = subsequence.chords.Chord(root_pc=(key_pc + 2) % 12, quality="minor")
		mediant = subsequence.chords.Chord(root_pc=(key_pc + 4) % 12, quality="diminished")
		subdominant = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="major")
		minor_dominant = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="minor")
		submediant = subsequence.chords.Chord(root_pc=(key_pc + 9) % 12, quality="minor")
		flat_seven = subsequence.chords.Chord(root_pc=(key_pc + 10) % 12, quality="major")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- I ↔ bVII: the Mixolydian shuttle ---
		graph.add_transition(tonic, flat_seven, WEIGHT_MIXOLYDIAN)
		graph.add_transition(flat_seven, tonic, WEIGHT_MIXOLYDIAN)

		# --- Plagal motion ---
		graph.add_transition(subdominant, tonic, WEIGHT_STRONG)
		graph.add_transition(tonic, subdominant, WEIGHT_MEDIUM)

		# --- bVII ↔ IV: common EDM chain ---
		graph.add_transition(flat_seven, subdominant, WEIGHT_MEDIUM)
		graph.add_transition(subdominant, flat_seven, WEIGHT_COMMON)

		# --- Minor dominant ---
		graph.add_transition(minor_dominant, tonic, WEIGHT_MEDIUM)
		graph.add_transition(tonic, minor_dominant, WEIGHT_COMMON)

		# --- Supertonic ---
		graph.add_transition(supertonic, minor_dominant, WEIGHT_COMMON)
		graph.add_transition(supertonic, subdominant, WEIGHT_COMMON)
		graph.add_transition(tonic, supertonic, WEIGHT_WEAK)

		# --- Submediant ---
		graph.add_transition(submediant, flat_seven, WEIGHT_COMMON)
		graph.add_transition(submediant, subdominant, WEIGHT_WEAK)
		graph.add_transition(tonic, submediant, WEIGHT_WEAK)
		graph.add_transition(minor_dominant, submediant, WEIGHT_WEAK)

		# --- Mediant (diminished - rare, colour) ---
		graph.add_transition(mediant, subdominant, WEIGHT_WEAK)
		graph.add_transition(mediant, tonic, WEIGHT_WEAK)
		graph.add_transition(supertonic, mediant, WEIGHT_WEAK)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return Mixolydian diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		scale_intervals = [0, 2, 4, 5, 7, 9, 10]
		degree_qualities = ["major", "minor", "diminished", "major", "minor", "minor", "major"]

		diatonic: typing.Set[subsequence.chords.Chord] = set()

		for interval, quality in zip(scale_intervals, degree_qualities):
			root_pc = (key_pc + interval) % 12
			diatonic.add(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

		# Functional: I, IV, bVII (the primary colour chords).
		functional: typing.Set[subsequence.chords.Chord] = set()
		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 10) % 12, quality="major"))

		return diatonic, functional
