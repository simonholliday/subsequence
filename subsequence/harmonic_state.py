import random
import typing

import subsequence.chord_graphs.aeolian_minor
import subsequence.chord_graphs.chromatic_mediant
import subsequence.chord_graphs.dorian_minor
import subsequence.chord_graphs.functional_major
import subsequence.chord_graphs.lydian_major
import subsequence.chord_graphs.phrygian_minor
import subsequence.chord_graphs.suspended
import subsequence.chord_graphs.turnaround_global
import subsequence.chords
import subsequence.weighted_graph


def _resolve_graph_style (
	style: str,
	include_dominant_7th: bool,
	minor_turnaround_weight: float
) -> subsequence.chord_graphs.ChordGraph:

	"""Create a ChordGraph instance from a string style name and legacy parameters."""

	if style in ("diatonic_major", "functional_major"):

		return subsequence.chord_graphs.functional_major.DiatonicMajor(
			include_dominant_7th = include_dominant_7th
		)

	if style in ("turnaround", "turnaround_global"):

		return subsequence.chord_graphs.turnaround_global.TurnaroundModulation(
			include_dominant_7th = include_dominant_7th,
			minor_turnaround_weight = minor_turnaround_weight
		)

	if style == "aeolian_minor":

		return subsequence.chord_graphs.aeolian_minor.AeolianMinor(
			include_dominant_7th = include_dominant_7th
		)

	if style == "phrygian_minor":

		return subsequence.chord_graphs.phrygian_minor.PhrygianMinor()

	if style == "lydian_major":

		return subsequence.chord_graphs.lydian_major.LydianMajor(
			include_dominant_7th = include_dominant_7th
		)

	if style == "dorian_minor":

		return subsequence.chord_graphs.dorian_minor.DorianMinor(
			include_dominant_7th = include_dominant_7th
		)

	if style == "chromatic_mediant":

		return subsequence.chord_graphs.chromatic_mediant.ChromaticMediant()

	if style == "suspended":

		return subsequence.chord_graphs.suspended.Suspended()

	raise ValueError(f"Unknown graph style: {style}")


class HarmonicState:

	"""Holds the current chord and key context for the composition."""

	def __init__ (
		self,
		key_name: str,
		graph_style: typing.Union[str, subsequence.chord_graphs.ChordGraph] = "functional_major",
		include_dominant_7th: bool = True,
		key_gravity_blend: float = 1.0,
		nir_strength: float = 0.5,
		minor_turnaround_weight: float = 0.0,
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""Initialize the harmonic state using a chord transition graph."""

		if key_gravity_blend < 0 or key_gravity_blend > 1:
			raise ValueError("Key gravity blend must be between 0 and 1")

		if nir_strength < 0 or nir_strength > 1:
			raise ValueError("NIR strength must be between 0 and 1")

		if minor_turnaround_weight < 0 or minor_turnaround_weight > 1:
			raise ValueError("Minor turnaround weight must be between 0 and 1")

		self.key_name = key_name
		self.key_root_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
		self.key_gravity_blend = key_gravity_blend
		self.nir_strength = nir_strength

		if isinstance(graph_style, str):
			chord_graph = _resolve_graph_style(graph_style, include_dominant_7th, minor_turnaround_weight)

		else:
			chord_graph = graph_style

		self.graph, tonic = chord_graph.build(key_name)
		self._diatonic_chords, self._function_chords = chord_graph.gravity_sets(key_name)

		self.rng = rng or random.Random()
		self.current_chord = tonic
		self.history: typing.List[subsequence.chords.Chord] = []


	def _calculate_nir_score (self, source: subsequence.chords.Chord, target: subsequence.chords.Chord) -> float:

		"""
		Calculate a Narmour Implication-Realization (NIR) score for a transition.
		Returns a multiplier (default 1.0, >1.0 for boost).
		"""

		if not self.history:
			return 1.0

		prev = self.history[-1]

		# Calculate interval from Prev -> Source (The "Implication" generator)
		# Using shortest-path distance in Pitch Class space (-6 to +6)
		prev_diff = (source.root_pc - prev.root_pc) % 12
		if prev_diff > 6:
			prev_diff -= 12

		prev_interval = abs(prev_diff)
		prev_direction = 1 if prev_diff > 0 else -1 if prev_diff < 0 else 0

		# Calculate interval from Source -> Target (The "Realization")
		target_diff = (target.root_pc - source.root_pc) % 12
		if target_diff > 6:
			target_diff -= 12

		target_interval = abs(target_diff)
		target_direction = 1 if target_diff > 0 else -1 if target_diff < 0 else 0

		score = 1.0

		# --- Rule A: Reversal (Gap Fill) ---
		# If previous was a Large Leap (> 4 semitones like P4, P5, m6), expect direction change.
		if prev_interval > 4:
			# Expect change in direction
			if target_direction != prev_direction and target_direction != 0:
				score += 0.5

			# Expect smaller interval (Gap Fill)
			if target_interval < 4:
				score += 0.3

		# --- Rule B: Process (Continuation/Inertia) ---
		# If previous was Small Step (< 3 semitones), expect similarity.
		elif prev_interval > 0 and prev_interval < 3:
			# Expect same direction
			if target_direction == prev_direction:
				score += 0.4

			# Expect similar size
			if abs(target_interval - prev_interval) <= 1:
				score += 0.2

		# --- Rule C: Closure ---
		# Return to Tonic (Closure) is often implied after tension
		if target.root_pc == self.key_root_pc:
			score += 0.2

		# --- Rule D: Proximity ---
		# General preference for small intervals (≤ 3 semitones).
		if target_interval > 0 and target_interval <= 3:
			score += 0.3

		# Scale the boost portion by nir_strength (score starts at 1.0, boost is the excess)
		return 1.0 + (score - 1.0) * self.nir_strength

	def step (self) -> subsequence.chords.Chord:

		"""Advance to the next chord based on the transition graph."""

		# Update history before choosing next (so structure tracks the path)
		self.history.append(self.current_chord)
		if len(self.history) > 4:
			self.history.pop(0)

		def weight_modifier (
			source: subsequence.chords.Chord,
			target: subsequence.chords.Chord,
			weight: int
		) -> float:

			"""Blend functional vs diatonic key gravity for transition weights."""

			is_function = 1.0 if target in self._function_chords else 0.0
			is_diatonic = 1.0 if target in self._diatonic_chords else 0.0

			# Decision path: blend controls whether key gravity favors functional or full diatonic chords.
			boost = (1.0 - self.key_gravity_blend) * is_function + self.key_gravity_blend * is_diatonic
			
			# Apply NIR gravity
			nir_score = self._calculate_nir_score(source, target)

			return (1.0 + boost) * nir_score

		# Decision path: chord changes occur here; key changes are not automatic.
		self.current_chord = self.graph.choose_next(self.current_chord, self.rng, weight_modifier=weight_modifier)

		return self.current_chord


	def get_current_chord (self) -> subsequence.chords.Chord:

		"""Return the current chord."""

		return self.current_chord


	def get_key_name (self) -> str:

		"""Return the current key name."""

		return self.key_name


	def get_chord_root_midi (self, base_midi: int, chord: subsequence.chords.Chord) -> int:

		"""Calculate the MIDI root for a chord relative to the key root."""

		offset = (chord.root_pc - self.key_root_pc) % 12

		return base_midi + offset
