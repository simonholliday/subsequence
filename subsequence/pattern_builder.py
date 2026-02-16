import logging
import random
import typing

import subsequence.constants
import subsequence.constants.velocity
import subsequence.pattern
import subsequence.sequence_utils
import subsequence.mini_notation
import subsequence.conductor

logger = logging.getLogger(__name__)


def _expand_sequence_param (name: str, value: typing.Any, n: int) -> list:

	"""Expand a scalar to a list of length n, or adjust a list to length n.

	If value is a scalar (int, float, or str), returns [value] * n.
	If value is a list longer than n, truncates and logs a warning.
	If value is a list shorter than n, repeats the last value and logs a warning.
	"""

	if isinstance(value, (int, float, str)):
		return [value] * n

	result = list(value)

	if len(result) == 0:
		raise ValueError(f"sequence(): {name} list cannot be empty")

	if len(result) > n:
		logger.warning("sequence(): %s has %d values but only %d steps — truncating", name, len(result), n)
		return result[:n]

	if len(result) < n:
		logger.warning("sequence(): %s has %d values but %d steps — repeating last value", name, len(result), n)
		return result + [result[-1]] * (n - len(result))

	return result


class PatternBuilder:

	"""
	The musician's 'palette' for creating musical content.
	
	A `PatternBuilder` instance (commonly named `p`) is passed to every 
	pattern function. It provides methods for placing notes, generating rhythms, 
	and transforming the resulting sequence (e.g., swinging, reversing, or transposing).

	Rhythm in Subsequence is typically expressed in **beats** (where 1.0 is a 
	quarter note) or **steps** (subdivisions of a pattern).
	"""

	def __init__ (self, pattern: subsequence.pattern.Pattern, cycle: int, conductor: typing.Optional[subsequence.conductor.Conductor] = None, drum_note_map: typing.Optional[typing.Dict[str, int]] = None, section: typing.Any = None, bar: int = 0, rng: typing.Optional[random.Random] = None) -> None:

		"""Initialize the builder with pattern context, cycle count, and optional section info."""

		self._pattern = pattern
		self.cycle = cycle
		self.conductor = conductor
		self._drum_note_map = drum_note_map
		self.section = section
		self.bar = bar
		self.rng: random.Random = rng or random.Random()

	@property
	def c (self) -> typing.Optional[subsequence.conductor.Conductor]:
		
		"""Alias for self.conductor."""
		
		return self.conductor

	def set_length (self, length: float) -> None:

		"""
		Dynamically change the length of the pattern.

		The new length takes effect immediately for any subsequent notes 
		placed in the current builder call, and will be used by the 
		sequencer for next cycle's scheduling.

		Parameters:
			length: New pattern length in beats (e.g., 4.0 for a bar).
		"""

		self._pattern.length = length

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

	def note (self, pitch: typing.Union[int, str], beat: float, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.25) -> None:

		"""
		Place a single MIDI note at a specific beat position.

		Parameters:
			pitch: MIDI note number (0-127) or a drum name string from 
				the pattern's `drum_note_map`.
			beat: The beat position (0.0 is the start). Negative values 
				wrap from the end (e.g., -1.0 is one beat before the end).
			velocity: MIDI velocity (0-127, default 100).
			duration: Note duration in beats (default 0.25).

		Example:
			```python
			p.note(60, beat=0, velocity=110)      # Middle C on beat 1
			p.note("kick", beat=1.0)               # Kick on beat 2
			p.note(67, beat=-0.5, duration=0.5)  # G on the 'and' of the last beat
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

	def hit (self, pitch: typing.Union[int, str], beats: typing.List[float], velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1) -> None:

		"""
		Place multiple short 'hits' at a list of beat positions.
		
		Example:
			```python
			p.hit("snare", [1, 3])  # Standard backbeat
			```
		"""

		for beat in beats:
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def hit_steps (self, pitch: typing.Union[int, str], steps: typing.List[int], velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, step_count: int = 16, probability: float = 1.0, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Place short hits at specific step (grid) positions.

		Parameters:
			pitch: MIDI note number or drum name.
			steps: A list of grid indices (0 to `step_count - 1`).
			velocity: MIDI velocity (0-127).
			duration: Note duration in beats.
			step_count: How many grid steps the pattern is divided into 
				(default 16, which means sixteenth notes in a 4-beat bar).
			probability: Chance (0.0 to 1.0) that each hit will play.
			rng: Optional random generator (overrides the pattern's seed).

		Example:
			```python
			# Typical sixteenth-note hi-hats with some probability variation
			p.hit_steps("hh", range(16), velocity=70, probability=0.8)
			```
		"""

		if rng is None:
			rng = self.rng

		step_duration = self._pattern.length / step_count

		for i in steps:

			if probability < 1.0 and rng.random() >= probability:
				continue

			beat = i * step_duration
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def sequence (self, steps: typing.List[int], pitches: typing.Union[int, str, typing.List[typing.Union[int, str]]], velocities: typing.Union[int, typing.List[int]] = 100, durations: typing.Union[float, typing.List[float]] = 0.1, step_count: int = 16, probability: float = 1.0, rng: typing.Optional[random.Random] = None) -> None:

		"""
		A multi-parameter step sequencer.
		
		Define which grid steps fire, and then provide a list of pitches, 
		velocities, and durations. If you provide a list for any parameter, 
		Subsequence will step through it as it places each note.

		Parameters:
			steps: List of grid indices to trigger.
			pitches: Pitch or list of pitches.
			velocities: Velocity or list of velocities (default 100).
			durations: Duration or list of durations (default 0.1).
			step_count: Grid resolution (default 16).
		"""

		if not steps:
			raise ValueError("steps list cannot be empty")

		if rng is None:
			rng = self.rng

		n = len(steps)
		pitches_list = _expand_sequence_param("pitches", pitches, n)
		velocities_list = _expand_sequence_param("velocities", velocities, n)
		durations_list = _expand_sequence_param("durations", durations, n)

		step_duration = self._pattern.length / step_count

		for i, step_idx in enumerate(steps):

			if probability < 1.0 and rng.random() >= probability:
				continue

			beat = step_idx * step_duration
			self.note(pitch=pitches_list[i], beat=beat, velocity=velocities_list[i], duration=durations_list[i])

	def seq (self, notation: str, pitch: typing.Union[str, int, None] = None, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY) -> None:

		"""
		Build a pattern using an expressive string-based 'mini-notation'.

		The notation distributes events evenly across the current pattern length.

		**Syntax:**
		- `x y z`: Items separated by spaces are distributed across the bar.
		- `[a b]`: Groups items into a single subdivided step.
		- `~` or `.`: A rest.
		- `_`: Extends the previous note (sustain).

		Parameters:
			notation: The mini-notation string.
			pitch: If provided, all symbols in the string are triggers for 
				this specific pitch. If `None`, symbols are interpreted as 
				pitches (e.g., "60" or "kick").
			velocity: MIDI velocity (default 100).

		Example:
			```python
			# Simple kick rhythm
			p.seq("kick . [kick kick] .")

			# Subdivided melody
			p.seq("60 [62 64] 67 60")
			```
		"""

		events = subsequence.mini_notation.parse(notation, total_duration=float(self._pattern.length))

		for event in events:
			
			current_pitch = pitch
			
			# If no global pitch provided, use the symbol as the pitch
			if current_pitch is None:
				# Try converting to int if it looks like a number
				if event.symbol.isdigit():
					current_pitch = int(event.symbol)
				else:
					current_pitch = event.symbol

			self.note(
				pitch = current_pitch,
				beat = event.time,
				duration = event.duration,
				velocity = velocity
			)

	def fill (self, pitch: typing.Union[int, str], step: float, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.25) -> None:

		"""
		Fill the pattern with a note repeating at a fixed beat interval.

		Example:
			```python
			p.fill("hh", step=0.25)  # sixteenth notes
			```
		"""

		if step <= 0:
			raise ValueError("Step must be positive")

		beat = 0.0

		while beat < self._pattern.length:
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)
			beat += step

	def arpeggio (self, pitches: typing.Union[typing.List[int], typing.List[str]], step: float = 0.25, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: typing.Optional[float] = None) -> None:

		"""
		Cycle through a list of pitches at regular beat intervals.

		Example:
			```python
			# Arpeggiate the current chord tones
			p.arpeggio(chord.tones(60), step=0.25)
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

	def chord (self, chord_obj: typing.Any, root: int, velocity: int = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY, sustain: bool = False, duration: float = 1.0, inversion: int = 0, count: typing.Optional[int] = None) -> None:

		"""
		Place a chord at the start of the pattern.

		Note: If the pattern was registered with `voice_leading=True`, 
		this method automatically chooses the best inversion.

		Parameters:
			chord_obj: The chord to play (usually the `chord` parameter 
				passed to your pattern function).
			root: MIDI root note (e.g., 60 for Middle C).
			velocity: MIDI velocity (default 90).
			sustain: If True, the notes last for the entire pattern duration.
			duration: Note duration in beats (default 1.0).
			inversion: Specific chord inversion (ignored if voice leading is on).
			count: Number of notes to play (cycles tones if higher than 
				the chord's natural size).
		"""

		pitches = chord_obj.tones(root=root, inversion=inversion, count=count)

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
		Apply a 'swing' offset to all notes in the pattern.

		Parameters:
			ratio: The swing ratio. 2.0 is standard triplet swing (the 
				off-beat is delayed to the third triplet).
		"""

		self._pattern.apply_swing(swing_ratio=ratio)

	def euclidean (self, pitch: typing.Union[int, str], pulses: int, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, dropout: float = 0.0, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Generate a Euclidean rhythm.
		
		This distributes a fixed number of 'pulses' as evenly as possible 
		across the pattern. This produces many of the world's most 
		common musical rhythms.

		Parameters:
			pitch: MIDI note or drum name.
			pulses: Total number of notes to place.
			velocity: MIDI velocity.
			duration: Note duration.
			dropout: Probability (0.0 to 1.0) of skipping each pulse.

		Example:
			```python
			# A classic 3-against-16 rhythm
			p.euclidean("kick", pulses=3)
			```
		"""

		if rng is None:
			rng = self.rng

		steps = int(self._pattern.length * 4)
		sequence = subsequence.sequence_utils.generate_euclidean_sequence(steps=steps, pulses=pulses)

		step_duration = self._pattern.length / steps

		for i, hit_value in enumerate(sequence):

			if hit_value == 0:
				continue

			if dropout > 0 and rng.random() < dropout:
				continue

			beat = i * step_duration

			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def bresenham (self, pitch: typing.Union[int, str], pulses: int, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, dropout: float = 0.0, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Generate a rhythm using the Bresenham line algorithm.
		
		This is an alternative to Euclidean rhythms that often results in 
		slightly different (but still mathematically even) distributions.
		"""

		if rng is None:
			rng = self.rng

		steps = int(self._pattern.length * 4)
		sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=steps, pulses=pulses)

		step_duration = self._pattern.length / steps

		for i, hit_value in enumerate(sequence):

			if hit_value == 0:
				continue

			if dropout > 0 and rng.random() < dropout:
				continue

			beat = i * step_duration

			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def dropout (self, probability: float, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Randomly remove notes from the pattern.
		
		This operates on all notes currently placed in the builder.

		Parameters:
			probability: The chance (0.0 to 1.0) of any given note being removed.
		"""

		if rng is None:
			rng = self.rng

		positions_to_remove = []

		for position in list(self._pattern.steps.keys()):

			if rng.random() < probability:
				positions_to_remove.append(position)

		for position in positions_to_remove:
			del self._pattern.steps[position]

	def velocity_shape (self, low: int = subsequence.constants.velocity.VELOCITY_SHAPE_LOW, high: int = subsequence.constants.velocity.VELOCITY_SHAPE_HIGH) -> None:

		"""
		Apply organic velocity variation to all notes in the pattern.

		Uses a van der Corput sequence to distribute velocities evenly 
		across the specified range, which often sounds more 'human' than 
		purely random velocity variation.

		Parameters:
			low: Minimum velocity (default 60).
			high: Maximum velocity (default 120).
		"""

		positions = sorted(self._pattern.steps.keys())

		if not positions:
			return

		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(len(positions))

		for position, vdc_value in zip(positions, vdc_values):

			step = self._pattern.steps[position]

			for note in step.notes:
				note.velocity = int(low + (high - low) * vdc_value)

	# ─── Pattern Transforms ─────────────────────────────────────────
	#
	# These methods transform existing notes after they have been placed.
	# Call them at the end of your builder function, after all notes are
	# in position. They operate on self._pattern.steps (the pulse-position
	# dict) and can be chained in any order.

	def reverse (self) -> None:

		"""
		Flip the pattern backwards in time.
		"""

		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			new_position = (total_pulses - 1) - position

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			new_steps[new_position].notes.extend(step.notes)

		self._pattern.steps = new_steps

	def double_time (self) -> None:

		"""
		Compress all notes into the first half of the pattern, doubling the speed.
		"""

		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			new_position = position // 2

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			new_steps[new_position].notes.extend(
				subsequence.pattern.Note(
					pitch = note.pitch,
					velocity = note.velocity,
					duration = max(1, note.duration // 2),
					channel = note.channel
				)
				for note in step.notes
			)

		self._pattern.steps = new_steps

	def half_time (self) -> None:

		"""
		Expand all notes by factor of 2, halving the speed. 
		Notes that fall outside the pattern length are removed.
		"""

		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			new_position = position * 2

			if new_position >= total_pulses:
				continue

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			new_steps[new_position].notes.extend(
				subsequence.pattern.Note(
					pitch = note.pitch,
					velocity = note.velocity,
					duration = min(note.duration * 2, total_pulses - new_position),
					channel = note.channel
				)
				for note in step.notes
			)

		self._pattern.steps = new_steps

	def shift (self, steps: int, step_count: int = 16) -> None:

		"""
		Rotate the pattern by a number of grid steps.

		Parameters:
			steps: Positive values shift right, negative values shift left.
			step_count: The grid resolution (default 16).
		"""

		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		pulses_per_step = total_pulses / step_count
		shift_pulses = int(steps * pulses_per_step)

		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			new_position = (position + shift_pulses) % total_pulses

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			new_steps[new_position].notes.extend(step.notes)

		self._pattern.steps = new_steps

	def transpose (self, semitones: int) -> None:

		"""
		Shift all note pitches up or down.

		Parameters:
			semitones: Positive for up, negative for down.
		"""

		for step in self._pattern.steps.values():

			for note in step.notes:
				note.pitch = max(0, min(127, note.pitch + semitones))

	def invert (self, pivot: int = 60) -> None:

		"""
		Invert all pitches around a pivot note.
		"""

		for step in self._pattern.steps.values():

			for note in step.notes:
				note.pitch = max(0, min(127, pivot + (pivot - note.pitch)))

	def every (self, n: int, fn: typing.Callable[["PatternBuilder"], None]) -> None:

		"""
		Apply a transformation every Nth cycle.

		Parameters:
			n: The cycle frequency (e.g., 4 = every 4th bar).
			fn: A function (often a lambda) that receives the builder and 
				calls further methods.

		Example:
			```python
			# Reverse every 4th bar
			p.every(4, lambda p: p.reverse())
			```
		"""

		if self.cycle % n == 0:
			fn(self)
