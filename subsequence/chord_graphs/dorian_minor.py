import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK

# Dorian-specific weight for the signature i ↔ IV plagal motion.
WEIGHT_DORIAN = 5


class DorianMinor (subsequence.chord_graphs.ChordGraph):

	"""Dorian-flavored minor harmony with a natural sixth degree.

	The natural 6th (instead of the aeolian b6) gives minor harmony a
	warmer, more hopeful quality. The IV chord (major subdominant in a
	minor key) is the defining Dorian sound. No harmonic-minor dominant V
	is used - the graph stays purely modal.

	Good for lo-fi, neo-soul, chill electronic, jazz, and funk.
	"""

	def __init__ (self, include_dominant_7th: bool = False) -> None:

		"""Configure whether to include dominant seventh chords.

		Defaults to False because Dorian is modal - dominant 7ths
		introduce functional tonal pull that weakens the modal feel.
		"""

		self.include_dominant_7th = include_dominant_7th

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a Dorian minor-key graph for the given key."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Dorian scale: 0, 2, 3, 5, 7, 9, 10
		# Degrees:      i, ii, bIII, IV, v, vi°, bVII
		tonic = subsequence.chords.Chord(root_pc=key_pc, quality="minor")
		supertonic = subsequence.chords.Chord(root_pc=(key_pc + 2) % 12, quality="minor")
		mediant = subsequence.chords.Chord(root_pc=(key_pc + 3) % 12, quality="major")
		subdominant = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="major")
		natural_dominant = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="minor")
		submediant_dim = subsequence.chords.Chord(root_pc=(key_pc + 9) % 12, quality="diminished")
		subtonic = subsequence.chords.Chord(root_pc=(key_pc + 10) % 12, quality="major")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- The Dorian signature: i ↔ IV ---
		graph.add_transition(tonic, subdominant, WEIGHT_DORIAN)
		graph.add_transition(subdominant, tonic, WEIGHT_DORIAN)

		# --- Tonic departures ---
		graph.add_transition(tonic, supertonic, WEIGHT_COMMON)
		graph.add_transition(tonic, subtonic, WEIGHT_COMMON)
		graph.add_transition(tonic, natural_dominant, WEIGHT_WEAK)
		graph.add_transition(tonic, mediant, WEIGHT_WEAK)

		# --- Supertonic departures ---
		graph.add_transition(supertonic, natural_dominant, WEIGHT_MEDIUM)
		graph.add_transition(supertonic, subdominant, WEIGHT_COMMON)
		graph.add_transition(supertonic, tonic, WEIGHT_WEAK)

		# --- Mediant (bIII) departures ---
		graph.add_transition(mediant, subdominant, WEIGHT_COMMON)
		graph.add_transition(mediant, subtonic, WEIGHT_COMMON)
		graph.add_transition(mediant, tonic, WEIGHT_WEAK)

		# --- Subdominant departures (beyond → tonic) ---
		graph.add_transition(subdominant, natural_dominant, WEIGHT_COMMON)
		graph.add_transition(subdominant, subtonic, WEIGHT_WEAK)

		# --- Natural dominant (v) departures ---
		graph.add_transition(natural_dominant, tonic, WEIGHT_MEDIUM)
		graph.add_transition(natural_dominant, subdominant, WEIGHT_COMMON)
		graph.add_transition(natural_dominant, mediant, WEIGHT_WEAK)

		# --- Subtonic (bVII) departures ---
		graph.add_transition(subtonic, tonic, WEIGHT_MEDIUM)
		graph.add_transition(subtonic, subdominant, WEIGHT_COMMON)
		graph.add_transition(subtonic, supertonic, WEIGHT_WEAK)

		# --- Submediant dim (vi°) connectors ---
		graph.add_transition(submediant_dim, natural_dominant, WEIGHT_MEDIUM)
		graph.add_transition(submediant_dim, tonic, WEIGHT_WEAK)

		if self.include_dominant_7th:
			# Harmonic minor dominant - optional tonal color.
			dominant_7th = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="dominant_7th")

			graph.add_transition(natural_dominant, dominant_7th, WEIGHT_WEAK)
			graph.add_transition(dominant_7th, tonic, WEIGHT_STRONG)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return Dorian diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Dorian scale: 0, 2, 3, 5, 7, 9, 10
		dorian_intervals = [0, 2, 3, 5, 7, 9, 10]
		dorian_qualities = ["minor", "minor", "major", "major", "minor", "diminished", "major"]

		diatonic: typing.Set[subsequence.chords.Chord] = set(
			subsequence.chord_graphs.build_diatonic_chords(key_pc, dorian_intervals, dorian_qualities)
		)

		# Functional set: i, IV (Dorian signature), v, bVII.
		functional: typing.Set[subsequence.chords.Chord] = set()

		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="minor"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="minor"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 10) % 12, quality="major"))

		return diatonic, functional
