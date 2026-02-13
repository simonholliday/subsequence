import random
import typing

import subsequence.constants
import subsequence.pattern
import subsequence.sequence_utils


class PatternBuilder:

	"""
	Provides high-level musical methods for building pattern content.
	"""

	def __init__ (self, pattern: subsequence.pattern.Pattern, cycle: int, drum_note_map: typing.Optional[typing.Dict[str, int]] = None) -> None:

		"""
		Initialize the builder with a pattern, cycle count, and optional drum note map.
		"""

		self._pattern = pattern
		self.cycle = cycle
		self._drum_note_map = drum_note_map

	def _resolve_pitch (self, pitch: typing.Union[int, str]) -> int:

		"""
		Resolve a pitch value to a MIDI note number.
		"""

		if isinstance(pitch, int):
			return pitch

		if self._drum_note_map is None:
			raise ValueError(f"String pitch '{pitch}' requires a drum_note_map, but none was provided")

		if pitch not in self._drum_note_map:
			raise ValueError(f"Unknown drum name '{pitch}' — not found in drum_note_map")

		return self._drum_note_map[pitch]

	def note (self, pitch: typing.Union[int, str], beat: float, velocity: int = 100, duration: float = 0.25) -> None:

		"""
		Place a single note at a beat position.
		"""

		midi_pitch = self._resolve_pitch(pitch)

		# Negative beat values wrap to the end of the pattern.
		if beat < 0:
			beat = self._pattern.length + beat

		self._pattern.add_note_beats(
			beat_position = beat,
			pitch = midi_pitch,
			velocity = velocity,
			duration_beats = duration
		)

	def hit (self, pitch: typing.Union[int, str], beats: typing.List[float], velocity: int = 100, duration: float = 0.1) -> None:

		"""
		Place short hits at one or more beat positions.
		"""

		for beat in beats:
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def fill (self, pitch: typing.Union[int, str], step: float, velocity: int = 100, duration: float = 0.25) -> None:

		"""
		Fill the pattern with evenly-spaced notes at the given step interval.
		"""

		if step <= 0:
			raise ValueError("Step must be positive")

		beat = 0.0

		while beat < self._pattern.length:
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)
			beat += step

	def arpeggio (self, pitches: typing.Union[typing.List[int], typing.List[str]], step: float = 0.25, velocity: int = 100, duration: typing.Optional[float] = None) -> None:

		"""
		Cycle through a list of pitches at regular intervals to create an arpeggio.
		"""

		if not pitches:
			raise ValueError("Pitches list cannot be empty")

		if step <= 0:
			raise ValueError("Step must be positive")

		resolved_pitches = [self._resolve_pitch(p) for p in pitches]

		if duration is None:
			duration = step

		self._pattern.add_arpeggio_beats(
			pitches = resolved_pitches,
			step_beats = step,
			velocity = velocity,
			duration_beats = duration
		)

	def chord (self, chord_obj: typing.Any, root: int, velocity: int = 90, sustain: bool = False, duration: float = 1.0) -> None:

		"""
		Place a chord at beat 0 using the chord's intervals.
		"""

		pitches = chord_obj.tones(root=root)

		if sustain:
			duration = float(self._pattern.length)

		for pitch in pitches:
			self._pattern.add_note_beats(
				beat_position = 0.0,
				pitch = pitch,
				velocity = velocity,
				duration_beats = duration
			)

	def swing (self, ratio: float = 2.0) -> None:

		"""
		Apply swing timing to all placed notes.
		"""

		self._pattern.apply_swing(swing_ratio=ratio)

	def euclidean (self, pitch: typing.Union[int, str], pulses: int, velocity: int = 100, duration: float = 0.1, dropout: float = 0.0) -> None:

		"""
		Generate a Euclidean rhythm and place hits at the resulting beat positions.
		"""

		steps = self._pattern.length * 4
		sequence = subsequence.sequence_utils.generate_euclidean_sequence(steps=steps, pulses=pulses)

		step_duration = self._pattern.length / steps
		rng = random.Random()

		for i, hit_value in enumerate(sequence):

			if hit_value == 0:
				continue

			if dropout > 0 and rng.random() < dropout:
				continue

			beat = i * step_duration

			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def bresenham (self, pitch: typing.Union[int, str], pulses: int, velocity: int = 100, duration: float = 0.1, dropout: float = 0.0) -> None:

		"""
		Generate a Bresenham rhythm and place hits at the resulting beat positions.
		"""

		steps = self._pattern.length * 4
		sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=steps, pulses=pulses)

		step_duration = self._pattern.length / steps
		rng = random.Random()

		for i, hit_value in enumerate(sequence):

			if hit_value == 0:
				continue

			if dropout > 0 and rng.random() < dropout:
				continue

			beat = i * step_duration

			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def dropout (self, probability: float, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Randomly remove notes from the pattern based on a probability.
		"""

		if rng is None:
			rng = random.Random()

		positions_to_remove = []

		for position in list(self._pattern.steps.keys()):

			if rng.random() < probability:
				positions_to_remove.append(position)

		for position in positions_to_remove:
			del self._pattern.steps[position]

	def velocity_shape (self, low: int = 60, high: int = 120) -> None:

		"""
		Apply a van der Corput velocity distribution to existing notes.
		"""

		positions = sorted(self._pattern.steps.keys())

		if not positions:
			return

		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(len(positions))

		for position, vdc_value in zip(positions, vdc_values):

			step = self._pattern.steps[position]

			for note in step.notes:
				note.velocity = int(low + (high - low) * vdc_value)

