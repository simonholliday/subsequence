"""Persistent melodic context for NIR-guided single-note line generation.

Provides :class:`MelodicState`, a stateful object that tracks recent pitch
history across bar rebuilds and applies the Narmour Implication-Realization
(NIR) model to score candidate pitches.  Because pattern builders are
recreated fresh each cycle, this state must live at module level (the same
pattern as :class:`~subsequence.easing.EasedValue`) so melodic continuity
survives bar boundaries.

The NIR rules operate on **absolute MIDI pitches** (direct semitone
subtraction), not pitch-class modular arithmetic, so registral direction is
properly tracked across octaves: a leap from C4 (60) to G4 (67) is +7
upward, not an ambiguous -5.
"""

import random
import typing

import subsequence.chords
import subsequence.intervals


class MelodicState:

	"""Persistent melodic context that applies NIR scoring to single-note lines."""


	def __init__ (
		self,
		key: str = "C",
		mode: str = "ionian",
		low: int = 48,
		high: int = 72,
		nir_strength: float = 0.5,
		chord_weight: float = 0.4,
		rest_probability: float = 0.0,
		pitch_diversity: float = 0.6,
	) -> None:

		"""Initialise a melodic state for a given key, mode, and MIDI register.

		Parameters:
			key: Root note of the key (e.g. ``"C"``, ``"F#"``, ``"Bb"``).
			mode: Scale mode name.  Accepts any mode registered with
			      :func:`~subsequence.intervals.scale_pitch_classes` (e.g.
			      ``"ionian"``, ``"aeolian"``, ``"dorian"``).
			low: Lowest MIDI note (inclusive) in the pitch pool.
			high: Highest MIDI note (inclusive) in the pitch pool.
			nir_strength: 0.0–1.0.  Scales how strongly the NIR rules
			    influence candidate scores.  0.0 = uniform; 1.0 = full boost.
			chord_weight: 0.0–1.0.  Additive multiplier bonus for candidates
			    whose pitch class belongs to the current chord tones.
			rest_probability: 0.0–1.0.  Probability of producing a rest
			    (returning ``None``) at any given step.
			pitch_diversity: 0.0–1.0.  Exponential penalty per recent
			    repetition of the same pitch.  Lower values discourage
			    repetition more aggressively.
		"""

		self.key = key
		self.mode = mode
		self.low = low
		self.high = high
		self.nir_strength = nir_strength
		self.chord_weight = chord_weight
		self.rest_probability = rest_probability
		self.pitch_diversity = pitch_diversity

		key_pc = subsequence.chords.key_name_to_pc(key)
		scale_pcs = set(subsequence.intervals.scale_pitch_classes(key_pc, mode))

		# Pitch pool: all scale tones within [low, high].
		self._pitch_pool: typing.List[int] = [
			p for p in range(low, high + 1) if p % 12 in scale_pcs
		]

		# Tonic pitch class for Rule C (closure).
		self._tonic_pc: int = key_pc

		# History of last N absolute MIDI pitches (capped at 4, same as HarmonicState).
		self.history: typing.List[int] = []


	def choose_next (
		self,
		chord_tones: typing.Optional[typing.List[int]],
		rng: random.Random,
	) -> typing.Optional[int]:

		"""Score all pitch-pool candidates and return the chosen pitch, or None for a rest."""

		if self.rest_probability > 0.0 and rng.random() < self.rest_probability:
			return None

		if not self._pitch_pool:
			return None

		# Resolve chord tones to pitch classes for fast membership testing.
		chord_tone_pcs: typing.Set[int] = (
			{t % 12 for t in chord_tones} if chord_tones else set()
		)

		scores = [self._score_candidate(p, chord_tone_pcs) for p in self._pitch_pool]

		# Weighted random choice: select using cumulative score as a probability weight.
		total = sum(scores)

		if total <= 0.0:
			chosen = rng.choice(self._pitch_pool)

		else:
			r = rng.uniform(0.0, total)
			cumulative = 0.0
			chosen = self._pitch_pool[-1]

			for pitch, score in zip(self._pitch_pool, scores):
				cumulative += score
				if r <= cumulative:
					chosen = pitch
					break

		# Persist history for the next call (capped at 4 entries).
		self.history.append(chosen)
		if len(self.history) > 4:
			self.history.pop(0)

		return chosen


	def _score_candidate (
		self,
		candidate: int,
		chord_tone_pcs: typing.Set[int],
	) -> float:

		"""Score one candidate pitch using NIR rules, chord weighting, range gravity, and pitch diversity."""

		score = 1.0

		# --- NIR rules (require at least one history note for Realization) ---
		if self.history:
			last_note = self.history[-1]

			target_diff = candidate - last_note
			target_interval = abs(target_diff)
			target_direction = 1 if target_diff > 0 else -1 if target_diff < 0 else 0

			# Rules A & B require an Implication context (prev -> last -> candidate).
			if len(self.history) >= 2:
				prev_note = self.history[-2]

				prev_diff = last_note - prev_note
				prev_interval = abs(prev_diff)
				prev_direction = 1 if prev_diff > 0 else -1 if prev_diff < 0 else 0

				# Rule A: Reversal (gap fill) — after a large leap, expect direction change.
				if prev_interval > 4:
					if target_direction != prev_direction and target_direction != 0:
						score += 0.5

					if target_interval < 4:
						score += 0.3

				# Rule B: Process (continuation) — after a small step, expect more of the same.
				elif 0 < prev_interval < 3:
					if target_direction == prev_direction:
						score += 0.4

					if abs(target_interval - prev_interval) <= 1:
						score += 0.2

			# Rule C: Closure — the tonic is a cognitively stable landing point.
			if candidate % 12 == self._tonic_pc:
				score += 0.2

			# Rule D: Proximity — smaller intervals are generally preferred.
			if 0 < target_interval <= 3:
				score += 0.3

			# Scale the entire NIR boost by nir_strength, leaving the base at 1.0.
			score = 1.0 + (score - 1.0) * self.nir_strength

		# --- Chord tone boost ---
		if candidate % 12 in chord_tone_pcs:
			score *= 1.0 + self.chord_weight

		# --- Range gravity: penalise notes far from the centre of [low, high] ---
		centre = (self.low + self.high) / 2.0
		half_range = max(1.0, (self.high - self.low) / 2.0)
		distance_ratio = abs(candidate - centre) / half_range
		score *= 1.0 - 0.3 * (distance_ratio ** 2)

		# --- Pitch diversity: exponential penalty for recently-heard pitches ---
		recent_occurrences = sum(1 for h in self.history if h == candidate)
		score *= self.pitch_diversity ** recent_occurrences

		return max(0.0, score)
