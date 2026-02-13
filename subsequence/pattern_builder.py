import random
import typing

import subsequence.constants
import subsequence.pattern
import subsequence.sequence_utils


class PatternBuilder:

	"""
	Provides high-level musical methods for building pattern content.
	"""

	def __init__ (self, pattern: subsequence.pattern.Pattern, cycle: int, drum_note_map: typing.Optional[typing.Dict[str, int]] = None, section: typing.Any = None, bar: int = 0) -> None:

		"""Initialize the builder with pattern context, cycle count, and optional section info."""

		self._pattern = pattern
		self.cycle = cycle
		self._drum_note_map = drum_note_map
		self.section = section
		self.bar = bar

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

		"""Place a single note at a beat position.

		Negative beat values wrap to the end of the pattern (e.g., `-1` = last beat).

		Parameters:
			pitch: MIDI note number or drum note map key (e.g., `"kick"`)
			beat: Beat position (0.0 = start of pattern)
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default 0.25)

		Example:
			```python
			# Place a note at beat 0
			p.note(pitch=60, beat=0, velocity=90, duration=0.5)

			# Place a drum hit using the drum note map
			p.note(pitch="kick", beat=0, velocity=127)
			```
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

	def hit_steps (self, pitch: typing.Union[int, str], steps: typing.List[int], velocity: int = 100, duration: float = 0.1, step_count: int = 16) -> None:

		"""Place short hits at specific step positions on a subdivided grid.

		The default `step_count=16` creates a sixteenth-note grid over a 4-beat pattern,
		where step 0 = beat 0, step 4 = beat 1, step 8 = beat 2, step 12 = beat 3.

		Parameters:
			pitch: MIDI note number or drum note map key (e.g., `"kick"`)
			steps: List of step indices (e.g., `[0, 4, 8, 12]` for quarter notes on a 16-step grid)
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default 0.1)
			step_count: Grid subdivisions per pattern (default 16 = sixteenth notes)

		Example:
			```python
			# Four-on-the-floor kick on a 16-step grid
			p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

			# Backbeat snare (beats 2 and 4)
			p.hit_steps("snare", [4, 12], velocity=100)

			# Eighth-note hi-hats on an 8-step grid
			p.hit_steps("hh", list(range(8)), velocity=80, step_count=8)
			```
		"""

		step_duration = self._pattern.length / step_count
		beats = [i * step_duration for i in steps]
		self.hit(pitch, beats=beats, velocity=velocity, duration=duration)

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

		"""Cycle through a list of pitches at regular intervals to create an arpeggio.

		Parameters:
			pitches: List of MIDI note numbers or drum note map keys
			step: Interval between notes in beats (default 0.25 = sixteenth notes)
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default: same as step)

		Example:
			```python
			# Sixteenth-note arpeggio from chord tones
			tones = chord.tones(root=60)  # [60, 64, 67] for C major
			p.arpeggio(tones, step=0.25, velocity=90)

			# Slower eighth-note arpeggio
			p.arpeggio([60, 64, 67, 72], step=0.5, velocity=100)
			```
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

		"""Place a chord at beat 0 using the chord's intervals.

		Parameters:
			chord_obj: A `Chord` object (automatically injected if the pattern accepts a `chord` parameter)
			root: MIDI root note number
			velocity: MIDI velocity 0-127 (default 90)
			sustain: If True, duration spans the entire pattern length (default False)
			duration: Note duration in beats (default 1.0, ignored if sustain=True)

		Example:
			```python
			@composition.pattern(channel=0, length=4)
			def chords(p, chord):
				# chord is automatically injected
				p.chord(chord, root=60, velocity=90, sustain=True)
			```
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

		"""Apply swing timing to all placed notes.

		Delays every other note by a ratio. A ratio of 2.0 creates classic "triplet swing"
		where off-beats land on the third triplet.

		Parameters:
			ratio: Swing ratio (default 2.0). Higher values = more swing.

		Example:
			```python
			# Place eighth notes, then apply triplet swing
			p.hit_steps("hh", list(range(8)), velocity=80, step_count=8)
			p.swing(ratio=2.0)
			```
		"""

		self._pattern.apply_swing(swing_ratio=ratio)

	def euclidean (self, pitch: typing.Union[int, str], pulses: int, velocity: int = 100, duration: float = 0.1, dropout: float = 0.0) -> None:

		"""Generate a Euclidean rhythm and place hits at the resulting beat positions.

		Euclidean rhythms distribute `pulses` evenly across the pattern length. The algorithm
		is based on Bjorklund's algorithm and creates rhythms used in traditional music worldwide.

		Parameters:
			pitch: MIDI note number or drum note map key
			pulses: Number of evenly-distributed hits
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default 0.1)
			dropout: Probability 0.0-1.0 of randomly removing hits (default 0.0)

		Example:
			```python
			# Classic Euclidean(16,3) rhythm (common in African music)
			p.euclidean(pitch=36, pulses=3, velocity=127)

			# Euclidean(16,5) with some randomness
			p.euclidean(pitch=38, pulses=5, velocity=100, dropout=0.1)
			```
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

		"""Apply a van der Corput velocity distribution to existing notes.

		Creates organic-sounding velocity variation using the van der Corput low-discrepancy sequence.
		This distributes velocities more evenly than pure randomness.

		Parameters:
			low: Minimum velocity (default 60)
			high: Maximum velocity (default 120)

		Example:
			```python
			# Place hi-hats, then shape velocities for a natural feel
			p.hit_steps("hh", list(range(16)), velocity=80)
			p.velocity_shape(low=60, high=100)
			```
		"""

		positions = sorted(self._pattern.steps.keys())

		if not positions:
			return

		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(len(positions))

		for position, vdc_value in zip(positions, vdc_values):

			step = self._pattern.steps[position]

			for note in step.notes:
				note.velocity = int(low + (high - low) * vdc_value)

