import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK

# Mediant-specific weight for the signature third-relation shifts.
WEIGHT_MEDIANT = 5


class ChromaticMediant (subsequence.chord_graphs.ChordGraph):

	"""Chromatic third-related harmony - roots move by major or minor thirds.

	All transitions connect chords whose roots are a major or minor third
	apart, creating dramatic, colorful shifts that sound both surprising
	and connected through shared common tones. No dominant-tonic or
	subdominant-tonic functional motion is used.

	Good for cinematic, ambient, soundtrack, and experimental music.
	"""

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a chromatic mediant graph with third-related root movement."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Core chords - major and minor triads at third-related intervals.
		tonic = subsequence.chords.Chord(root_pc=key_pc, quality="major")
		flat_mediant = subsequence.chords.Chord(root_pc=(key_pc + 3) % 12, quality="major")
		mediant = subsequence.chords.Chord(root_pc=(key_pc + 4) % 12, quality="major")
		flat_submediant = subsequence.chords.Chord(root_pc=(key_pc + 8) % 12, quality="major")
		submediant = subsequence.chords.Chord(root_pc=(key_pc + 9) % 12, quality="major")

		# Minor variants for color contrast.
		tonic_minor = subsequence.chords.Chord(root_pc=key_pc, quality="minor")
		subdominant_minor = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="minor")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- Tonic departures (by thirds) ---
		graph.add_transition(tonic, flat_mediant, WEIGHT_MEDIANT)
		graph.add_transition(tonic, mediant, WEIGHT_MEDIANT)
		graph.add_transition(tonic, flat_submediant, WEIGHT_COMMON)
		graph.add_transition(tonic, submediant, WEIGHT_COMMON)
		graph.add_transition(tonic, tonic_minor, WEIGHT_WEAK)

		# --- Flat mediant (bIII) departures ---
		graph.add_transition(flat_mediant, tonic, WEIGHT_MEDIANT)
		graph.add_transition(flat_mediant, flat_submediant, WEIGHT_COMMON)
		graph.add_transition(flat_mediant, submediant, WEIGHT_MEDIUM)

		# --- Mediant (III) departures ---
		graph.add_transition(mediant, tonic, WEIGHT_MEDIANT)
		graph.add_transition(mediant, flat_submediant, WEIGHT_MEDIUM)
		graph.add_transition(mediant, submediant, WEIGHT_COMMON)
		graph.add_transition(mediant, flat_mediant, WEIGHT_WEAK)

		# --- Flat submediant (bVI) departures ---
		graph.add_transition(flat_submediant, tonic, WEIGHT_MEDIANT)
		graph.add_transition(flat_submediant, mediant, WEIGHT_COMMON)
		graph.add_transition(flat_submediant, flat_mediant, WEIGHT_COMMON)
		graph.add_transition(flat_submediant, subdominant_minor, WEIGHT_WEAK)

		# --- Submediant (VI) departures ---
		graph.add_transition(submediant, tonic, WEIGHT_MEDIUM)
		graph.add_transition(submediant, mediant, WEIGHT_COMMON)
		graph.add_transition(submediant, flat_mediant, WEIGHT_COMMON)
		graph.add_transition(submediant, flat_submediant, WEIGHT_WEAK)

		# --- Tonic minor departures ---
		graph.add_transition(tonic_minor, flat_mediant, WEIGHT_MEDIANT)
		graph.add_transition(tonic_minor, flat_submediant, WEIGHT_COMMON)
		graph.add_transition(tonic_minor, tonic, WEIGHT_MEDIUM)

		# --- Subdominant minor (iv) connector ---
		graph.add_transition(subdominant_minor, tonic, WEIGHT_MEDIUM)
		graph.add_transition(subdominant_minor, flat_submediant, WEIGHT_COMMON)
		graph.add_transition(subdominant_minor, flat_mediant, WEIGHT_WEAK)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return chromatic mediant diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# All chords in the graph form the "diatonic" set for gravity.
		diatonic: typing.Set[subsequence.chords.Chord] = set()

		for interval in [0, 3, 4, 8, 9]:
			diatonic.add(subsequence.chords.Chord(root_pc=(key_pc + interval) % 12, quality="major"))

		diatonic.add(subsequence.chords.Chord(root_pc=key_pc, quality="minor"))
		diatonic.add(subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="minor"))

		# Functional set: I, bIII, bVI (strongest mediant poles).
		functional: typing.Set[subsequence.chords.Chord] = set()

		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 3) % 12, quality="major"))
		functional.add(subsequence.chords.Chord(root_pc=(key_pc + 8) % 12, quality="major"))

		return diatonic, functional
