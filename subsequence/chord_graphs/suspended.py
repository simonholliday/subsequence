import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK

# Suspended-specific weight for same-root sus2 ↔ sus4 colour changes.
WEIGHT_COLOUR = 5


class Suspended (subsequence.chord_graphs.ChordGraph):

	"""Open harmony using suspended chords - no major or minor thirds.

	All chords are sus2 or sus4, creating ambiguous, open textures.
	Same-root sus2 ↔ sus4 movement (colour change without root movement)
	is heavily weighted. Root movement favors fourths/fifths and whole
	steps. A single minor tonic provides occasional grounding.

	Good for ambient, post-rock, drone, and minimalist electronic music.
	"""

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a suspended-chord graph with open, ambiguous harmony."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Core suspended chords.
		tonic_sus2 = subsequence.chords.Chord(root_pc=key_pc, quality="sus2")
		tonic_sus4 = subsequence.chords.Chord(root_pc=key_pc, quality="sus4")
		sub_sus2 = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="sus2")
		sub_sus4 = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="sus4")
		dom_sus2 = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="sus2")
		dom_sus4 = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="sus4")
		subtonic_sus2 = subsequence.chords.Chord(root_pc=(key_pc + 10) % 12, quality="sus2")

		# Minor tonic as the one "resolved" chord.
		tonic_minor = subsequence.chords.Chord(root_pc=key_pc, quality="minor")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- Same-root colour changes (sus2 ↔ sus4) ---
		graph.add_transition(tonic_sus2, tonic_sus4, WEIGHT_COLOUR)
		graph.add_transition(tonic_sus4, tonic_sus2, WEIGHT_COLOUR)
		graph.add_transition(sub_sus2, sub_sus4, WEIGHT_COLOUR)
		graph.add_transition(sub_sus4, sub_sus2, WEIGHT_COLOUR)
		graph.add_transition(dom_sus2, dom_sus4, WEIGHT_COLOUR)
		graph.add_transition(dom_sus4, dom_sus2, WEIGHT_COLOUR)

		# --- Root motion by fourths/fifths ---
		graph.add_transition(tonic_sus2, sub_sus2, WEIGHT_MEDIUM)
		graph.add_transition(tonic_sus4, sub_sus4, WEIGHT_MEDIUM)
		graph.add_transition(sub_sus2, tonic_sus2, WEIGHT_MEDIUM)
		graph.add_transition(sub_sus4, tonic_sus4, WEIGHT_MEDIUM)

		graph.add_transition(tonic_sus2, dom_sus2, WEIGHT_COMMON)
		graph.add_transition(tonic_sus4, dom_sus4, WEIGHT_COMMON)
		graph.add_transition(dom_sus2, tonic_sus2, WEIGHT_MEDIUM)
		graph.add_transition(dom_sus4, tonic_sus4, WEIGHT_MEDIUM)

		# --- bVII whole-step motion ---
		graph.add_transition(tonic_sus2, subtonic_sus2, WEIGHT_COMMON)
		graph.add_transition(subtonic_sus2, tonic_sus2, WEIGHT_COMMON)
		graph.add_transition(subtonic_sus2, sub_sus2, WEIGHT_WEAK)
		graph.add_transition(sub_sus2, subtonic_sus2, WEIGHT_WEAK)

		# --- Minor tonic as resolution ---
		graph.add_transition(tonic_sus4, tonic_minor, WEIGHT_WEAK)
		graph.add_transition(dom_sus4, tonic_minor, WEIGHT_WEAK)
		graph.add_transition(tonic_minor, tonic_sus2, WEIGHT_MEDIUM)
		graph.add_transition(tonic_minor, tonic_sus4, WEIGHT_COMMON)

		# --- Cross-root colour movement ---
		graph.add_transition(sub_sus2, dom_sus4, WEIGHT_WEAK)
		graph.add_transition(dom_sus2, sub_sus4, WEIGHT_WEAK)

		return graph, tonic_sus2

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return suspended diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# All chords in the graph form the diatonic set.
		diatonic: typing.Set[subsequence.chords.Chord] = set()

		for interval in [0, 5, 7, 10]:
			diatonic.add(subsequence.chords.Chord(root_pc=(key_pc + interval) % 12, quality="sus2"))

		for interval in [0, 5, 7]:
			diatonic.add(subsequence.chords.Chord(root_pc=(key_pc + interval) % 12, quality="sus4"))

		diatonic.add(subsequence.chords.Chord(root_pc=key_pc, quality="minor"))

		# Functional set: tonic sus2/sus4 and the minor resolution.
		functional: typing.Set[subsequence.chords.Chord] = set()

		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="sus2"))
		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="sus4"))
		functional.add(subsequence.chords.Chord(root_pc=key_pc, quality="minor"))

		return diatonic, functional
