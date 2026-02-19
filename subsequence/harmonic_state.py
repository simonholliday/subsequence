import random
import typing

import subsequence.chord_graphs.aeolian_minor
import subsequence.chord_graphs.chromatic_mediant
import subsequence.chord_graphs.diminished
import subsequence.chord_graphs.dorian_minor
import subsequence.chord_graphs.functional_major
import subsequence.chord_graphs.lydian_major
import subsequence.chord_graphs.mixolydian
import subsequence.chord_graphs.phrygian_minor
import subsequence.chord_graphs.suspended
import subsequence.chord_graphs.turnaround_global
import subsequence.chord_graphs.whole_tone
import subsequence.chords
import subsequence.weighted_graph


DEFAULT_ROOT_DIVERSITY: float = 0.4


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

	if style == "mixolydian":

		return subsequence.chord_graphs.mixolydian.Mixolydian()

	if style == "whole_tone":

		return subsequence.chord_graphs.whole_tone.WholeTone()

	if style == "diminished":

		return subsequence.chord_graphs.diminished.Diminished()

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
		root_diversity: float = DEFAULT_ROOT_DIVERSITY,
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""
		Initialize the harmonic state using a chord transition graph.

		Parameters:
			key_name: Note name for the key (e.g., ``"C"``, ``"F#"``).
			graph_style: Built-in style name or a custom ``ChordGraph`` instance.
			include_dominant_7th: Include V7 chords in the graph (default True).
			key_gravity_blend: Balance between functional and diatonic gravity
				(0.0 = functional only, 1.0 = full diatonic). Default 1.0.
			nir_strength: Melodic inertia from Narmour's Implication-Realization
				model (0.0 = off, 1.0 = full). Default 0.5.
			minor_turnaround_weight: For turnaround style, weight toward minor
				turnarounds (0.0 to 1.0). Default 0.0.
			root_diversity: Root-repetition damping factor (0.0 to 1.0). Each
				recent chord sharing a candidate's root pitch class multiplies
				the transition weight by this factor. At the default (0.4), one
				recent same-root chord reduces the weight to 40%; two reduce it
				to 16%. Set to 1.0 to disable the penalty entirely. Default 0.4.
			rng: Optional seeded ``random.Random`` for deterministic playback.
		"""

		if key_gravity_blend < 0 or key_gravity_blend > 1:
			raise ValueError("Key gravity blend must be between 0 and 1")

		if nir_strength < 0 or nir_strength > 1:
			raise ValueError("NIR strength must be between 0 and 1")

		if minor_turnaround_weight < 0 or minor_turnaround_weight > 1:
			raise ValueError("Minor turnaround weight must be between 0 and 1")

		if root_diversity < 0 or root_diversity > 1:
			raise ValueError("Root diversity must be between 0 and 1")

		self.key_name = key_name
		self.key_root_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
		self.key_gravity_blend = key_gravity_blend
		self.nir_strength = nir_strength
		self.root_diversity = root_diversity
		self.minor_turnaround_weight = minor_turnaround_weight


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

			"""
			Combine three forces that shape chord transition probabilities:

			1. **Key gravity** — blends functional pull (tonic, dominant) with
			   full diatonic pull, controlled by ``key_gravity_blend``.
			2. **Melodic inertia (NIR)** — Narmour's cognitive expectation
			   model favoring continuation after small steps and reversal
			   after large leaps, controlled by ``nir_strength``.
			3. **Root diversity** — exponential damping that discourages
			   revisiting a root pitch class heard recently, controlled by
			   ``root_diversity``. Each recent chord sharing the target's
			   root multiplies the weight by ``root_diversity`` (default
			   0.4), so the penalty grows stronger with each consecutive
			   same-root step.

			The final modifier is:

				``(1 + gravity_boost) × nir_score × diversity``
			"""

			is_function = 1.0 if target in self._function_chords else 0.0
			is_diatonic = 1.0 if target in self._diatonic_chords else 0.0

			# Decision path: blend controls whether key gravity favors functional or full diatonic chords.
			boost = (1.0 - self.key_gravity_blend) * is_function + self.key_gravity_blend * is_diatonic

			# Apply NIR gravity
			nir_score = self._calculate_nir_score(source, target)

			# Root diversity: penalise transitions to a root heard recently.
			recent_same_root = sum(
				1 for h in self.history
				if h.root_pc == target.root_pc
			)
			diversity = self.root_diversity ** recent_same_root

			return (1.0 + boost) * nir_score * diversity

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
