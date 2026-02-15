import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_STRONG = subsequence.chord_graphs.WEIGHT_STRONG
WEIGHT_MEDIUM = subsequence.chord_graphs.WEIGHT_MEDIUM
WEIGHT_WEAK = subsequence.chord_graphs.WEIGHT_WEAK


class DarkTechno (subsequence.chord_graphs.ChordGraph):

	"""All-minor chord graph for dark and hard techno.

	Only four chords, all minor quality — dark techno barely moves
	harmonically. The Phrygian bII (half-step above tonic) is the
	signature dark cadence. Use with high gravity (0.9+) so the
	harmony sits on the tonic most of the time with occasional drifts.
	"""

	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build a minimal all-minor graph with Phrygian and plagal motion."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# Four chords, all minor.
		tonic = subsequence.chords.Chord(root_pc=key_pc, quality="minor")
		flat_two = subsequence.chords.Chord(root_pc=(key_pc + 1) % 12, quality="minor")
		subdominant = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="minor")
		natural_dominant = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="minor")

		graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = subsequence.weighted_graph.WeightedGraph()

		# --- Tonic departures ---
		graph.add_transition(tonic, flat_two, WEIGHT_MEDIUM)
		graph.add_transition(tonic, subdominant, WEIGHT_MEDIUM)
		graph.add_transition(tonic, natural_dominant, WEIGHT_WEAK)

		# --- Phrygian cadence: bII -> i (strongest resolution) ---
		graph.add_transition(flat_two, tonic, WEIGHT_STRONG)
		graph.add_transition(flat_two, natural_dominant, WEIGHT_WEAK)

		# --- Plagal motion ---
		graph.add_transition(subdominant, tonic, WEIGHT_STRONG)
		graph.add_transition(subdominant, natural_dominant, WEIGHT_MEDIUM)

		# --- Natural dominant departures ---
		graph.add_transition(natural_dominant, tonic, WEIGHT_MEDIUM)
		graph.add_transition(natural_dominant, flat_two, WEIGHT_WEAK)

		return graph, tonic

	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return all-minor diatonic and functional chord sets."""

		key_pc = subsequence.chord_graphs.validate_key_name(key_name)

		# All four chords are diatonic to this dark palette.
		diatonic: typing.Set[subsequence.chords.Chord] = set()

		for interval in [0, 1, 5, 7]:
			root_pc = (key_pc + interval) % 12
			diatonic.add(subsequence.chords.Chord(root_pc=root_pc, quality="minor"))

		# Functional set: tonic, bII (Phrygian), subdominant.
		functional: typing.Set[subsequence.chords.Chord] = set()

		for interval in [0, 1, 5]:
			root_pc = (key_pc + interval) % 12
			functional.add(subsequence.chords.Chord(root_pc=root_pc, quality="minor"))

		return diatonic, functional
