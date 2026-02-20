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

# Lydian-specific weight for the signature I ↔ II shimmer.
WEIGHT_LYDIAN = 5


class LydianMajor (subsequence.chord_graphs.ChordGraph):

	"""Lydian-flavored major harmony with a raised fourth degree.

	The raised 4th (#4) gives a bright, floating quality. The II chord
	(major, a whole step above tonic) is the defining Lydian sound  - 
	the I ↔ II "shimmer" is the strongest motion in the graph. The
	natural IV chord is absent entirely, keeping the harmony purely modal.

	Good for ambient, cinematic, and progressive electronic music.
	"""

	def __init__ (self, include_dominant_7th: bool = True) -> None:

		"""Configure whether to include dominant seventh chords."""

		self.include_dominant_7th = include_dominant_7th

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a Lydian major-key graph for the given key."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Lydian scale: 0, 2, 4, 6, 7, 9, 11
		# Degrees:      I, II, iii, #iv°, V, vi, vii
		tonic = subsequence.chords.Chord(root_pc=key_pc, quality="major")
		supertonic = subsequence.chords.Chord(root_pc=(key_pc + 2) % 12, quality="major")
		mediant = subsequence.chords.Chord(root_pc=(key_pc + 4) % 12, quality="minor")
		sharp_four_dim = subsequence.chords.Chord(root_pc=(key_pc + 6) % 12, quality="diminished")
		dominant = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="major")
		submediant = subsequence.chords.Chord(root_pc=(key_pc + 9) % 12, quality="minor")
		leading = subsequence.chords.Chord(root_pc=(key_pc + 11) % 12, quality="minor")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- The Lydian shimmer: I ↔ II ---
		graph.add_transition(tonic, supertonic, WEIGHT_LYDIAN)
		graph.add_transition(supertonic, tonic, WEIGHT_LYDIAN)

		# --- Tonic departures ---
		graph.add_transition(tonic, dominant, WEIGHT_COMMON)
		graph.add_transition(tonic, submediant, WEIGHT_COMMON)
		graph.add_transition(tonic, mediant, WEIGHT_WEAK)

		# --- Supertonic departures (beyond → tonic) ---
		graph.add_transition(supertonic, dominant, WEIGHT_COMMON)
		graph.add_transition(supertonic, mediant, WEIGHT_WEAK)

		# --- Mediant departures ---
		graph.add_transition(mediant, submediant, WEIGHT_COMMON)
		graph.add_transition(mediant, tonic, WEIGHT_WEAK)

		# --- Dominant departures ---
		graph.add_transition(dominant, tonic, WEIGHT_STRONG)
		graph.add_transition(dominant, submediant, WEIGHT_DECEPTIVE)

		# --- Submediant departures ---
		graph.add_transition(submediant, supertonic, WEIGHT_COMMON)
		graph.add_transition(submediant, dominant, WEIGHT_COMMON)
		graph.add_transition(submediant, tonic, WEIGHT_WEAK)

		# --- Leading tone (vii) departures ---
		graph.add_transition(leading, tonic, WEIGHT_STRONG)
		graph.add_transition(leading, supertonic, WEIGHT_WEAK)

		# --- #iv° connectors ---
		graph.add_transition(sharp_four_dim, dominant, WEIGHT_MEDIUM)
		graph.add_transition(sharp_four_dim, tonic, WEIGHT_WEAK)

		if self.include_dominant_7th:
			dominant_7th = subsequence.chords.Chord(root_pc=dominant.root_pc, quality="dominant_7th")

			graph.add_transition(dominant, dominant_7th, WEIGHT_WEAK)
			graph.add_transition(dominant_7th, tonic, WEIGHT_STRONG)
			graph.add_transition(dominant_7th, submediant, WEIGHT_DECEPTIVE)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return Lydian diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		diatonic: typing.Set[subsequence.chords.Chord] = set(
			subsequence.chord_graphs.build_diatonic_chords(
				key_pc,
				subsequence.intervals.get_intervals("lydian"),
				subsequence.intervals.LYDIAN_QUALITIES
			)
		)

		# Add dominant 7th to diatonic set.
		dominant_7th = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="dominant_7th")
		diatonic.add(dominant_7th)

		# Functional set: I, II (Lydian signature), V.
		functional: typing.Set[subsequence.chords.Chord] = set()

		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 2) % 12, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="major"))
		functional.add(dominant_7th)

		return diatonic, functional
