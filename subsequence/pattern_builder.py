import logging
import random
import typing

import subsequence.constants
import subsequence.pattern
import subsequence.sequence_utils

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
	Provides high-level musical methods for building pattern content.
	"""

	def __init__ (self, pattern: subsequence.pattern.Pattern, cycle: int, drum_note_map: typing.Optional[typing.Dict[str, int]] = None, section: typing.Any = None, bar: int = 0, rng: typing.Optional[random.Random] = None) -> None:

		"""Initialize the builder with pattern context, cycle count, and optional section info."""

		self._pattern = pattern
		self.cycle = cycle
		self._drum_note_map = drum_note_map
		self.section = section
		self.bar = bar
		self.rng: random.Random = rng or random.Random()

	def set_length (self, length: float) -> None:

		"""Change the pattern length for the current and future cycles.

		The new length takes effect immediately for any notes placed after this call,
		and the sequencer will use the new length when scheduling the next cycle.

		Parameters:
			length: New pattern length in beats

		Example:
			```python
			@composition.pattern(channel=0, length=4)
			def melody(p):
				if p.section and p.section.name == "breakdown":
					p.set_length(2)  # half-time during breakdown
				p.fill(60, step=0.5)
			```
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

	def hit_steps (self, pitch: typing.Union[int, str], steps: typing.List[int], velocity: int = 100, duration: float = 0.1, step_count: int = 16, probability: float = 1.0, rng: typing.Optional[random.Random] = None) -> None:

		"""Place short hits at specific step positions on a subdivided grid.

		The default `step_count=16` creates a sixteenth-note grid over a 4-beat pattern,
		where step 0 = beat 0, step 4 = beat 1, step 8 = beat 2, step 12 = beat 3.

		Parameters:
			pitch: MIDI note number or drum note map key (e.g., `"kick"`)
			steps: List of step indices (e.g., `[0, 4, 8, 12]` for quarter notes on a 16-step grid)
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default 0.1)
			step_count: Grid subdivisions per pattern (default 16 = sixteenth notes)
			probability: Chance of each hit sounding, 0.0-1.0 (default 1.0 = all hits)
			rng: Random number generator (default: ``self.rng``)

		Example:
			```python
			# Four-on-the-floor kick on a 16-step grid
			p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

			# Hi-hats with 80% probability per step
			p.hit_steps("hh", list(range(16)), velocity=80, probability=0.8)
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

		"""Place notes at specific step positions with per-step pitch, velocity, and duration.

		Like a hardware step sequencer: define which steps fire, then what plays at each one.
		Any of ``pitches``, ``velocities``, or ``durations`` can be a single value (applied to every
		step) or a list (one value per step).

		If a list is shorter than ``steps``, the last value is repeated. If longer, the list is
		truncated. Both cases log a warning.

		Parameters:
			steps: List of step indices on the grid (e.g., ``[0, 4, 8, 12]``)
			pitches: MIDI note number(s) or drum name(s) — scalar or per-step list
			velocities: MIDI velocity 0-127 — scalar or per-step list (default 100)
			durations: Note duration in beats — scalar or per-step list (default 0.1)
			step_count: Grid subdivisions per pattern (default 16 = sixteenth notes)
			probability: Chance of each hit sounding, 0.0-1.0 (default 1.0 = all hits)
			rng: Random number generator (default: ``self.rng``)

		Example:
			```python
			# Ascending melodic phrase
			p.sequence([0, 4, 8, 12], pitches=[60, 64, 67, 72])

			# Full per-step control
			p.sequence(
			    steps=[0, 2, 4, 6, 8, 10, 12, 14],
			    pitches=[60, 62, 64, 65, 67, 69, 71, 72],
			    velocities=[127, 100, 110, 90, 120, 95, 105, 85],
			    durations=[0.5, 0.25, 0.5, 0.25, 0.5, 0.25, 0.5, 0.25],
			)

			# Drum pattern with per-step velocity accents
			p.sequence(
			    steps=[0, 4, 8, 12],
			    pitches="kick",
			    velocities=[127, 90, 110, 90],
			)
			```
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

	def euclidean (self, pitch: typing.Union[int, str], pulses: int, velocity: int = 100, duration: float = 0.1, dropout: float = 0.0, rng: typing.Optional[random.Random] = None) -> None:

		"""Generate a Euclidean rhythm and place hits at the resulting beat positions.

		Euclidean rhythms distribute `pulses` evenly across the pattern length. The algorithm
		is based on Bjorklund's algorithm and creates rhythms used in traditional music worldwide.

		Parameters:
			pitch: MIDI note number or drum note map key
			pulses: Number of evenly-distributed hits
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default 0.1)
			dropout: Probability 0.0-1.0 of randomly removing hits (default 0.0)
			rng: Random number generator for dropout (default: ``self.rng``)

		Example:
			```python
			# Classic Euclidean(16,3) rhythm (common in African music)
			p.euclidean(pitch=36, pulses=3, velocity=127)

			# Euclidean(16,5) with some randomness
			p.euclidean(pitch=38, pulses=5, velocity=100, dropout=0.1)
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

	def bresenham (self, pitch: typing.Union[int, str], pulses: int, velocity: int = 100, duration: float = 0.1, dropout: float = 0.0, rng: typing.Optional[random.Random] = None) -> None:

		"""Generate a Bresenham rhythm and place hits at the resulting beat positions.

		Parameters:
			pitch: MIDI note number or drum note map key
			pulses: Number of evenly-distributed hits
			velocity: MIDI velocity 0-127 (default 100)
			duration: Note duration in beats (default 0.1)
			dropout: Probability 0.0-1.0 of randomly removing hits (default 0.0)
			rng: Random number generator for dropout (default: ``self.rng``)
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
		Randomly remove notes from the pattern based on a probability.
		"""

		if rng is None:
			rng = self.rng

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

	# ─── Pattern Transforms ─────────────────────────────────────────
	#
	# These methods transform existing notes after they have been placed.
	# Call them at the end of your builder function, after all notes are
	# in position. They operate on self._pattern.steps (the pulse-position
	# dict) and can be chained in any order.

	def reverse (self) -> None:

		"""Mirror all note positions in time, reversing the pattern.

		A note at the start of the pattern moves to the end, and vice versa.
		Notes at the same position stay together.

		Example:
			```python
			p.hit_steps("kick", [0, 4, 8, 12], velocity=127)
			p.reverse()  # kick now hits on steps 12, 8, 4, 0 (from the listener's perspective)
			```
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

		"""Compress all notes into the first half of the pattern, doubling the speed.

		Positions and durations are halved. The second half of the pattern is left empty,
		creating space for variation or layering.

		Example:
			```python
			p.fill(60, step=0.5)       # 8 eighth notes across 4 beats
			p.double_time()             # now 8 sixteenth notes in the first 2 beats
			```
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

		"""Expand all notes to double their time position, halving the speed.

		Positions and durations are doubled. Notes whose doubled position would exceed
		the pattern length are dropped.

		Example:
			```python
			p.fill(60, step=0.25)      # 16 sixteenth notes across 4 beats
			p.half_time()               # now 8 eighth notes in the first 4 beats, rest dropped
			```
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

		"""Rotate the pattern by a number of grid steps, wrapping around.

		Uses the same grid concept as ``hit_steps()`` — the default 16-step grid
		divides the pattern into sixteenth notes. Positive values shift right
		(later in time), negative values shift left (earlier).

		Parameters:
			steps: Number of grid steps to shift (positive = right, negative = left)
			step_count: Grid subdivisions per pattern (default 16, matching ``hit_steps()``)

		Example:
			```python
			# Shift a snare pattern by 4 steps (one beat) for a backbeat
			p.euclidean("snare", pulses=4)
			p.shift(4)
			```
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

		"""Shift all note pitches up or down by the given number of semitones.

		Pitches are clamped to the MIDI range 0-127.

		Parameters:
			semitones: Number of semitones to shift (positive = up, negative = down)

		Example:
			```python
			p.arpeggio([60, 64, 67], step=0.25)
			p.transpose(12)   # up one octave
			```
		"""

		for step in self._pattern.steps.values():

			for note in step.notes:
				note.pitch = max(0, min(127, note.pitch + semitones))

	def invert (self, pivot: int = 60) -> None:

		"""Invert all pitches around a pivot note, mirroring intervals.

		A note 3 semitones above the pivot becomes 3 semitones below, and vice versa.
		Pitches are clamped to the MIDI range 0-127.

		Parameters:
			pivot: MIDI note number to invert around (default 60 = middle C)

		Example:
			```python
			p.arpeggio([60, 64, 67], step=0.25)   # C E G
			p.invert(pivot=64)                      # becomes 68 64 61 (Ab E Db)
			```
		"""

		for step in self._pattern.steps.values():

			for note in step.notes:
				note.pitch = max(0, min(127, pivot + (pivot - note.pitch)))

	def every (self, n: int, fn: typing.Callable[["PatternBuilder"], None]) -> None:

		"""Apply a transform function every Nth cycle.

		A convenience wrapper around ``p.cycle``. Fires on cycle 0 (the first cycle)
		and every N cycles after that.

		Parameters:
			n: Apply the transform when cycle is a multiple of n
			fn: A function that receives this PatternBuilder and calls transform methods on it

		Example:
			```python
			p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

			# Reverse the pattern every 4th cycle
			p.every(4, lambda p: p.reverse())

			# Combine transforms in a single lambda
			p.every(8, lambda p: (p.double_time(), p.transpose(12)))
			```
		"""

		if self.cycle % n == 0:
			fn(self)
