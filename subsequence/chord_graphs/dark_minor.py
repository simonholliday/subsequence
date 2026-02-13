import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_DECEPTIVE = subsequence.chord_graphs.WEIGHT_DECEPTIVE
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK

# Dark-minor-specific weights.
WEIGHT_PHRYGIAN = 5
WEIGHT_PLAGAL = 4


class DarkMinor (subsequence.chord_graphs.ChordGraph):

	"""Minor-key graph with Phrygian, aeolian, and chromatic elements for dark electronic music."""

	def __init__ (self, include_dominant_7th: bool = True) -> None:

		"""Configure whether to include dominant seventh chords."""

		self.include_dominant_7th = include_dominant_7th

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a dark minor-key graph with Phrygian and aeolian elements."""

		if key_name not in subsequence.chords.NOTE_NAME_TO_PC:
			raise ValueError(f"Unknown key name: {key_name}")

		key_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]

		# Natural minor scale: 0, 2, 3, 5, 7, 8, 10
		tonic = subsequence.chords.Chord(root_pc=key_pc, quality="minor")
		supertonic_dim = subsequence.chords.Chord(root_pc=(key_pc + 2) % 12, quality="diminished")
		mediant = subsequence.chords.Chord(root_pc=(key_pc + 3) % 12, quality="major")
		subdominant = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="minor")
		natural_dominant = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="minor")
		submediant = subsequence.chords.Chord(root_pc=(key_pc + 8) % 12, quality="major")
		subtonic = subsequence.chords.Chord(root_pc=(key_pc + 10) % 12, quality="major")

		# Harmonic minor additions.
		dominant = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="major")
		leading_dim = subsequence.chords.Chord(root_pc=(key_pc + 11) % 12, quality="diminished")

		# Phrygian/Neapolitan flat-two.
		flat_two = subsequence.chords.Chord(root_pc=(key_pc + 1) % 12, quality="major")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- Tonic departures ---
		graph.add_transition(tonic, subdominant, WEIGHT_PLAGAL)
		graph.add_transition(tonic, submediant, WEIGHT_COMMON)
		graph.add_transition(tonic, subtonic, WEIGHT_COMMON)
		graph.add_transition(tonic, flat_two, WEIGHT_WEAK)
		graph.add_transition(tonic, natural_dominant, WEIGHT_COMMON)

		# --- Natural dominant (v) departures ---
		graph.add_transition(natural_dominant, submediant, WEIGHT_COMMON)
		graph.add_transition(natural_dominant, subdominant, WEIGHT_COMMON)
		graph.add_transition(natural_dominant, tonic, WEIGHT_WEAK)

		# --- Minor plagal ---
		graph.add_transition(subdominant, tonic, WEIGHT_PLAGAL)
		graph.add_transition(subdominant, dominant, WEIGHT_MEDIUM)
		graph.add_transition(subdominant, submediant, WEIGHT_WEAK)

		# --- Aeolian cycle: i -> bVI -> bVII -> i ---
		graph.add_transition(submediant, subtonic, WEIGHT_MEDIUM)
		graph.add_transition(subtonic, tonic, WEIGHT_MEDIUM)

		# --- Andalusian descent: i -> bVII -> bVI -> V ---
		graph.add_transition(subtonic, submediant, WEIGHT_COMMON)
		graph.add_transition(submediant, dominant, WEIGHT_MEDIUM)

		# --- Phrygian cadence: bII -> i ---
		graph.add_transition(flat_two, tonic, WEIGHT_PHRYGIAN)
		graph.add_transition(flat_two, dominant, WEIGHT_COMMON)

		# --- Harmonic minor cadence: V -> i ---
		graph.add_transition(dominant, tonic, WEIGHT_STRONG)
		graph.add_transition(dominant, submediant, WEIGHT_DECEPTIVE)

		# --- Chromatic connectors ---
		graph.add_transition(supertonic_dim, dominant, WEIGHT_MEDIUM)
		graph.add_transition(leading_dim, tonic, WEIGHT_STRONG)
		graph.add_transition(mediant, submediant, WEIGHT_COMMON)
		graph.add_transition(mediant, subdominant, WEIGHT_WEAK)

		# --- Optional dominant seventh ---
		if self.include_dominant_7th:
			dominant_7th = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="dominant_7th")

			graph.add_transition(dominant, dominant_7th, WEIGHT_WEAK)
			graph.add_transition(dominant_7th, tonic, WEIGHT_STRONG)
			graph.add_transition(dominant_7th, submediant, WEIGHT_DECEPTIVE)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return minor-key diatonic and functional chord sets."""

		key_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]

		# Natural minor diatonic triads.
		natural_minor_intervals = [0, 2, 3, 5, 7, 8, 10]
		natural_minor_qualities = ["minor", "diminished", "major", "minor", "minor", "major", "major"]

		diatonic: typing.Set[subsequence.chords.Chord] = set()

		for interval, quality in zip(natural_minor_intervals, natural_minor_qualities):
			root_pc = (key_pc + interval) % 12
			diatonic.add(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

		# Harmonic minor V (major) and bII (Phrygian).
		dominant_pc = (key_pc + 7) % 12
		flat_two_pc = (key_pc + 1) % 12

		diatonic.add(subsequence.chords.Chord(root_pc=dominant_pc, quality="major"))
		diatonic.add(subsequence.chords.Chord(root_pc=flat_two_pc, quality="major"))

		dominant_7th = subsequence.chords.Chord(root_pc=dominant_pc, quality="dominant_7th")
		diatonic.add(dominant_7th)

		# Functional set: i, iv, V(/V7), bII.
		functional: typing.Set[subsequence.chords.Chord] = set()

		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="minor"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="minor"))
		functional.add(subsequence.chords.Chord(root_pc=dominant_pc, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=flat_two_pc, quality="major"))
		functional.add(dominant_7th)

		return diatonic, functional
