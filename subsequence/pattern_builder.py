import logging
import random
import typing

import subsequence.chords
import subsequence.constants
import subsequence.constants.velocity
import subsequence.groove
import subsequence.intervals
import subsequence.pattern
import subsequence.sequence_utils
import subsequence.mini_notation
import subsequence.conductor
import subsequence.easing
import subsequence.weighted_graph

logger = logging.getLogger(__name__)


def _expand_sequence_param (name: str, value: typing.Any, n: int) -> list:

	"""Expand a scalar to a list of length n, or adjust a list to length n.

	Parameters:
		name: The name of the parameter being expanded (used for logging).
		value: A scalar (e.g., int, float, str) or an iterable to expand.
		n: The target length for the returned list.

	Returns:
		A list of length `n`. If `value` is a scalar, returns `[value] * n`.
		If `value` is a list longer than `n`, truncates it and logs a warning.
		If `value` is a list shorter than `n`, repeats the last value and logs a warning.
	"""

	if isinstance(value, (int, float, str)):
		return [value] * n

	result = list(value)

	if len(result) == 0:
		raise ValueError(f"sequence(): {name} list cannot be empty")

	if len(result) > n:
		logger.warning("sequence(): %s has %d values but only %d steps - truncating", name, len(result), n)
		return result[:n]

	if len(result) < n:
		logger.warning("sequence(): %s has %d values but %d steps - repeating last value", name, len(result), n)
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

	def __init__ (self, pattern: subsequence.pattern.Pattern, cycle: int, conductor: typing.Optional[subsequence.conductor.Conductor] = None, drum_note_map: typing.Optional[typing.Dict[str, int]] = None, section: typing.Any = None, bar: int = 0, rng: typing.Optional[random.Random] = None, tweaks: typing.Optional[typing.Dict[str, typing.Any]] = None, default_grid: int = 16) -> None:

		"""Initialize the builder with pattern context, cycle count, and optional section info.

		Parameters:
			pattern: The ``Pattern`` instance this builder populates.
			cycle: Zero-based rebuild counter.
			conductor: Optional ``Conductor`` for time-varying signals.
			drum_note_map: Optional mapping of drum names to MIDI notes.
			section: Current ``SectionInfo`` (or ``None``).
			bar: Global bar count.
			rng: Optional seeded ``Random`` for reproducibility.
			tweaks: Per-pattern overrides set via ``composition.tweak()``.
			default_grid: Number of grid slots used by ``hit_steps()``,
				``sequence()``, and ``shift()`` when no explicit ``grid``
				is passed.  Normally set automatically from the decorator's
				``length`` and ``unit`` parameters.
		"""

		self._pattern = pattern
		self.cycle = cycle
		self.conductor = conductor
		self._drum_note_map = drum_note_map
		self.section = section
		self.bar = bar
		self.rng: random.Random = rng or random.Random()
		self._tweaks: typing.Dict[str, typing.Any] = tweaks or {}
		self._default_grid: int = default_grid

	@property
	def c (self) -> typing.Optional[subsequence.conductor.Conductor]:

		"""Alias for self.conductor."""

		return self.conductor

	def signal (self, name: str) -> float:

		"""Read a conductor signal at the current bar.

		Shorthand for ``p.c.get(name, p.bar * 4)``. Returns 0.0 if
		no conductor is attached or the signal is not defined.
		"""

		if self.conductor is None:
			return 0.0

		return self.conductor.get(name, self.bar * 4)

	def param (self, name: str, default: typing.Any = None) -> typing.Any:

		"""Read a tweakable parameter for this pattern.

		Returns the value set via ``composition.tweak()`` if one
		exists, otherwise returns ``default``.

		Parameters:
			name: The parameter name.
			default: The value to return if no tweak is active.

		Example::

			@composition.pattern(channel=0, length=4)
			def bass (p):
				pitches = p.param("pitches", [60, 64, 67, 72])
				p.sequence(steps=[0, 4, 8, 12], pitches=pitches)
		"""

		return self._tweaks.get(name, default)

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
			raise ValueError(f"Unknown drum name '{pitch}' - not found in drum_note_map")

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

	def hit_steps (self, pitch: typing.Union[int, str], steps: typing.List[int], velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, grid: typing.Optional[int] = None, probability: float = 1.0, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Place short hits at specific step (grid) positions.

		Parameters:
			pitch: MIDI note number or drum name.
			steps: A list of grid indices (0 to ``grid - 1``).
			velocity: MIDI velocity (0-127).
			duration: Note duration in beats.
			grid: How many grid slots the pattern is divided into.
				Defaults to the pattern's ``default_grid`` (set from the
				decorator's ``length`` and ``unit``, or sixteenth-note
				resolution when ``unit`` is omitted).
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

		if grid is None:
			grid = self._default_grid

		step_duration = self._pattern.length / grid

		for i in steps:

			if probability < 1.0 and rng.random() >= probability:
				continue

			beat = i * step_duration
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)

	def sequence (self, steps: typing.List[int], pitches: typing.Union[int, str, typing.List[typing.Union[int, str]]], velocities: typing.Union[int, typing.List[int]] = 100, durations: typing.Union[float, typing.List[float]] = 0.1, grid: typing.Optional[int] = None, probability: float = 1.0, rng: typing.Optional[random.Random] = None) -> None:

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
			grid: Grid resolution. Defaults to the pattern's
				``default_grid`` (derived from the decorator's ``length``
				and ``unit``).
		"""

		if not steps:
			raise ValueError("steps list cannot be empty")

		if rng is None:
			rng = self.rng

		if grid is None:
			grid = self._default_grid

		n = len(steps)
		pitches_list = _expand_sequence_param("pitches", pitches, n)
		velocities_list = _expand_sequence_param("velocities", velocities, n)
		durations_list = _expand_sequence_param("durations", durations, n)

		step_duration = self._pattern.length / grid

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
		- `x?0.6`: Probability suffix — fires with the given probability (0.0–1.0).

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

			# Ghost snare: snare on 2 and 4, ghost note 50% of the time
			p.seq(". snare?0.5 . snare")
			```
		"""

		events = subsequence.mini_notation.parse(notation, total_duration=float(self._pattern.length))

		for event in events:

			# Apply probability before placing the note.
			if event.probability < 1.0 and self.rng.random() >= event.probability:
				continue

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

	def arpeggio (
		self,
		pitches: typing.Union[typing.List[int], typing.List[str]],
		step: float = 0.25,
		velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: typing.Optional[float] = None,
		direction: str = "up",
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""
		Cycle through a list of pitches at regular beat intervals.

		Parameters:
			pitches: List of MIDI note numbers or note name strings (e.g. ``"C4"``).
			step: Time between each note in beats (default 0.25 = 16th note).
			velocity: MIDI velocity for all notes (default 85).
			duration: Note duration in beats. Defaults to ``step`` (each note
			          fills its slot exactly).
			direction: Order in which pitches are cycled:

			    - ``"up"`` — lowest to highest, then wrap (default).
			    - ``"down"`` — highest to lowest, then wrap.
			    - ``"up_down"`` — ascend then descend (ping-pong), cycling.
			    - ``"random"`` — shuffled once per call using *rng*.

			rng: Random number generator used when ``direction="random"``.
			     Defaults to ``self.rng`` (the pattern's seeded RNG).

		Example:
			```python
			# Ascending arpeggio (default)
			p.arpeggio(chord.tones(60), step=0.25)

			# Ping-pong: C E G E C E G E ...
			p.arpeggio([60, 64, 67], step=0.25, direction="up_down")

			# Descending
			p.arpeggio([60, 64, 67], step=0.25, direction="down")
			```
		"""

		if not pitches:
			raise ValueError("Pitches list cannot be empty")

		if step <= 0:
			raise ValueError("Step must be positive")

		resolved = [self._resolve_pitch(p) for p in pitches]

		if direction == "up":
			pass  # already in ascending order as supplied
		elif direction == "down":
			resolved = list(reversed(resolved))
		elif direction == "up_down":
			if len(resolved) > 1:
				resolved = resolved + list(reversed(resolved[1:-1]))
		elif direction == "random":
			if rng is None:
				rng = self.rng
			resolved = list(resolved)
			rng.shuffle(resolved)
		else:
			raise ValueError(f"direction must be 'up', 'down', 'up_down', or 'random', got '{direction}'")

		if duration is None:
			duration = step

		self._pattern.add_arpeggio_beats(
			pitches = resolved,
			step_beats = step,
			velocity = velocity,
			duration_beats = duration
		)

	def chord (self, chord_obj: typing.Any, root: int, velocity: int = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY, sustain: bool = False, duration: float = 1.0, inversion: int = 0, count: typing.Optional[int] = None, legato: typing.Optional[float] = None) -> None:

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
				Mutually exclusive with ``legato``.
			duration: Note duration in beats (default 1.0). Ignored when
				``legato`` is set, since legato recalculates all durations.
			inversion: Specific chord inversion (ignored if voice leading is on).
			count: Number of notes to play (cycles tones if higher than
				the chord's natural size).
			legato: If given, calls ``p.legato(ratio)`` after placing the
				chord, stretching each note to fill ``ratio`` of the gap to
				the next note. Mutually exclusive with ``sustain``.

		Example::

			# Shorthand for: p.chord(...) then p.legato(0.9)
			p.chord(chord, root=root, velocity=85, count=4, legato=0.9)
		"""

		if sustain and legato is not None:
			raise ValueError("sustain=True and legato= are mutually exclusive — use one or the other")

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

		if legato is not None:
			self.legato(legato)

	def strum (self, chord_obj: typing.Any, root: int, velocity: int = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY, sustain: bool = False, duration: float = 1.0, inversion: int = 0, count: typing.Optional[int] = None, offset: float = 0.05, direction: str = "up", legato: typing.Optional[float] = None) -> None:

		"""
		Play a chord with a small time offset between each note (strum effect).

		Works exactly like ``chord()`` but staggers the notes instead of
		playing them simultaneously. The first note always lands on beat 0;
		subsequent notes are delayed by ``offset`` beats each.

		Parameters:
			chord_obj: The chord to play (usually the ``chord`` parameter
				passed to your pattern function).
			root: MIDI root note (e.g., 60 for Middle C).
			velocity: MIDI velocity (default 90).
			sustain: If True, the notes last for the entire pattern duration.
				Mutually exclusive with ``legato``.
			duration: Note duration in beats (default 1.0). Ignored when
				``legato`` is set, since legato recalculates all durations.
			inversion: Specific chord inversion (ignored if voice leading is on).
			count: Number of notes to play (cycles tones if higher than
				the chord's natural size).
			offset: Time in beats between each note onset (default 0.05).
			direction: ``"up"`` for low-to-high, ``"down"`` for high-to-low.
			legato: If given, calls ``p.legato(ratio)`` after placing the
				chord, stretching each note to fill ``ratio`` of the gap to
				the next note. Mutually exclusive with ``sustain``.

		Example::

			# Gentle upward strum with legato
			p.strum(chord, root=52, velocity=85, offset=0.06, legato=0.95)

			# Fast downward strum
			p.strum(chord, root=52, direction="down", offset=0.03)
		"""

		if sustain and legato is not None:
			raise ValueError("sustain=True and legato= are mutually exclusive — use one or the other")

		if offset <= 0:
			raise ValueError("offset must be positive")

		if direction not in ("up", "down"):
			raise ValueError(f"direction must be 'up' or 'down', got '{direction}'")

		pitches = chord_obj.tones(root=root, inversion=inversion, count=count)

		if direction == "down":
			pitches = list(reversed(pitches))

		if sustain:
			duration = float(self._pattern.length)

		for i, pitch in enumerate(pitches):
			self.note(pitch=pitch, beat=i * offset, velocity=velocity, duration=duration)

		if legato is not None:
			self.legato(legato)

	def swing (self, ratio: float = 2.0) -> None:

		"""
		Apply a 'swing' offset to all notes in the pattern.

		Parameters:
			ratio: The swing ratio. 2.0 is standard triplet swing (the 
				off-beat is delayed to the third triplet).
		"""

		self._pattern.apply_swing(swing_ratio=ratio)

	def groove (self, template: subsequence.groove.Groove) -> None:

		"""
		Apply a groove template to all notes in the pattern.

		A groove shifts notes at grid positions by per-step timing offsets
		and optionally scales their velocity. Use ``Groove.swing(percent)``
		for simple swing, ``Groove.from_agr(path)`` to import an Ableton
		groove file, or construct a ``Groove`` directly for custom feel.

		Parameters:
			template: A Groove instance defining the timing/velocity template.
		"""

		self._pattern.steps = subsequence.groove.apply_groove(
			self._pattern.steps, template
		)

	def _place_rhythm_sequence (
		self,
		sequence: typing.List[int],
		pitch: typing.Union[int, str],
		velocity: int,
		duration: float,
		dropout: float,
		rng: random.Random,
		no_overlap: bool = False
	) -> None:

		"""Place hits from a binary sequence into the pattern.

		Shared implementation for ``euclidean()`` and ``bresenham()``.
		Each active step (1) is placed as a note; steps are evenly spaced
		across the pattern length. Zeros and dropout-gated steps are skipped.
		"""

		midi_pitch = self._resolve_pitch(pitch)
		step_duration = self._pattern.length / len(sequence)

		for i, hit_value in enumerate(sequence):

			if hit_value == 0:
				continue

			if dropout > 0 and rng.random() < dropout:
				continue

			if no_overlap:
				pulse = int(i * step_duration * subsequence.constants.MIDI_QUARTER_NOTE + 0.5)
				if pulse in self._pattern.steps:
					if any(n.pitch == midi_pitch for n in self._pattern.steps[pulse].notes):
						continue

			self.note(pitch=pitch, beat=i * step_duration, velocity=velocity, duration=duration)

	def euclidean (self, pitch: typing.Union[int, str], pulses: int, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, dropout: float = 0.0, no_overlap: bool = False, rng: typing.Optional[random.Random] = None) -> None:

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
			no_overlap: If True, skip steps where a note of the same pitch
				already exists. Useful for layering ghost notes around
				hand-placed anchors.

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
		self._place_rhythm_sequence(sequence, pitch, velocity, duration, dropout, rng, no_overlap=no_overlap)

	def bresenham (self, pitch: typing.Union[int, str], pulses: int, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, dropout: float = 0.0, no_overlap: bool = False, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Generate a rhythm using the Bresenham line algorithm.

		This is an alternative to Euclidean rhythms that often results in
		slightly different (but still mathematically even) distributions.

		Parameters:
			pitch: MIDI note or drum name.
			pulses: Total number of notes to place.
			velocity: MIDI velocity.
			duration: Note duration.
			dropout: Probability (0.0 to 1.0) of skipping each pulse.
			no_overlap: If True, skip steps where a note of the same pitch
				already exists. Useful for layering ghost notes around
				hand-placed anchors.
		"""

		if rng is None:
			rng = self.rng

		steps = int(self._pattern.length * 4)
		sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=steps, pulses=pulses)
		self._place_rhythm_sequence(sequence, pitch, velocity, duration, dropout, rng, no_overlap=no_overlap)

	def bresenham_poly (
		self,
		parts: typing.Dict[typing.Union[int, str], float],
		velocity: typing.Union[int, typing.Dict[typing.Union[int, str], int]] = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: float = 0.1,
		grid: typing.Optional[int] = None,
		dropout: float = 0.0,
		no_overlap: bool = False,
		rng: typing.Optional[random.Random] = None,
	) -> None:

		"""
		Distribute multiple drum voices across the pattern using weighted Bresenham.

		Each step is assigned to exactly one voice — voices never overlap, producing
		interlocking rhythmic patterns. Density weights control how frequently each
		voice fires. If the weights sum to less than 1.0, the remainder becomes
		evenly-distributed rests (silent steps).

		Because notes are placed via ``self.note()``, all post-placement transforms
		(``groove``, ``humanize``, ``velocity_shape``, ``shift``, etc.) work normally.

		Parameters:
			parts: Mapping of pitch (MIDI note or drum name) to density weight.
				Higher weight means more hits per bar. Weights in the range (0, 1]
				are typical; a weight of 0.5 targets roughly one hit every two steps.
			velocity: Either a single MIDI velocity applied to all voices, or a dict
				mapping each pitch to its own velocity. Pitches absent from the dict
				fall back to the default velocity (100).
			duration: Note duration in beats (default 0.1).
			grid: Number of steps to divide the pattern into. Defaults to the
				pattern's standard sixteenth-note grid (``length * 4``).
			dropout: Probability (0.0–1.0) of randomly skipping each placed hit.
			no_overlap: If True, skip steps where a note of the same pitch already
				exists. Useful for layering ghost notes around hand-placed anchors.
			rng: Optional random generator (overrides the pattern's seed).

		Example:
			```python
			p.bresenham_poly(
				parts={"kick_1": 0.25, "snare_1": 0.125, "hi_hat_closed": 0.5},
				velocity={"kick_1": 100, "snare_1": 90, "hi_hat_closed": 70},
			)
			```

		Layering with hand-placed hits:
			```python
			# Algorithmic base — interlocking texture, no overlaps within this layer
			p.bresenham_poly(
				parts={"hi_hat_closed": 0.5, "snare_2": 0.1},
				velocity={"hi_hat_closed": 65, "snare_2": 40},
			)
			# Hand-placed anchors on top — these CAN overlap the algorithmic layer
			p.hit_steps("kick_1", [0, 8], velocity=110)
			p.hit_steps("snare_1", [4, 12], velocity=100)
			```

		Stable vs shifting patterns:
			Because the algorithm redistributes all positions when weights change,
			a single voice with a continuously ramping density will shift positions
			every bar. This is great for background texture (hats, shakers) but
			can sound jarring for prominent, distinctive sounds (claps, cowbells).

			**For stable patterns** — use ``bresenham()`` with integer pulses.
			Positions stay fixed until the pulse count steps up::

				pulses = max(1, round(density * 16))
				p.bresenham("hand_clap", pulses=pulses, velocity=95)

			**For shifting texture** — use ``bresenham_poly()`` with continuous
			density. Positions evolve every bar::

				p.bresenham_poly(parts={"hi_hat_closed": density}, velocity=70)

			**To stabilise a solo voice** — pair it with a second voice. More
			voices in a single call means less positional shift per voice::

				p.bresenham_poly(
					parts={"hand_clap": 0.12, "snare_2": 0.08},
					velocity={"hand_clap": 95, "snare_2": 40},
				)
		"""

		if not parts:
			raise ValueError("parts dict cannot be empty")

		if any(w < 0 for w in parts.values()):
			raise ValueError("All density weights must be non-negative")

		if rng is None:
			rng = self.rng

		if grid is None:
			grid = self._default_grid

		voice_names = list(parts.keys())
		weights = [parts[name] for name in voice_names]

		# If weights don't fill the bar, add an implicit rest voice.
		weight_sum = sum(weights)
		rest_index: typing.Optional[int] = None
		if weight_sum < 1.0:
			rest_index = len(voice_names)
			weights.append(1.0 - weight_sum)

		sequence = subsequence.sequence_utils.generate_bresenham_sequence_weighted(
			steps=grid, weights=weights
		)

		step_duration = self._pattern.length / grid

		for step_idx, voice_idx in enumerate(sequence):

			if voice_idx == rest_index:
				continue

			if dropout > 0 and rng.random() < dropout:
				continue

			pitch = voice_names[voice_idx]

			if no_overlap:
				midi_pitch = self._resolve_pitch(pitch)
				pulse = int(step_idx * step_duration * subsequence.constants.MIDI_QUARTER_NOTE + 0.5)
				if pulse in self._pattern.steps:
					if any(n.pitch == midi_pitch for n in self._pattern.steps[pulse].notes):
						continue

			if isinstance(velocity, dict):
				vel = velocity.get(pitch, subsequence.constants.velocity.DEFAULT_VELOCITY)
			else:
				vel = velocity

			self.note(pitch=pitch, beat=step_idx * step_duration, velocity=vel, duration=duration)

	@staticmethod
	def _build_ghost_bias (grid: int, bias: str) -> typing.List[float]:

		"""Build probability weights for ``ghost_fill()`` bias modes."""

		steps_per_beat = max(1, grid // 4)
		weights: typing.List[float] = []

		for i in range(grid):
			pos = i % steps_per_beat

			if bias == "uniform":
				weights.append(1.0)
			elif bias == "offbeat":
				if pos == 0:
					weights.append(0.05)
				elif steps_per_beat > 1 and pos == steps_per_beat // 2:
					weights.append(0.3)
				else:
					weights.append(1.0)
			elif bias == "syncopated":
				if pos == 0:
					weights.append(0.05)
				elif steps_per_beat > 1 and pos == steps_per_beat // 2:
					weights.append(1.0)
				else:
					weights.append(0.3)
			elif bias == "before":
				if pos == steps_per_beat - 1:
					weights.append(1.0)
				elif pos == 0:
					weights.append(0.05)
				else:
					weights.append(0.25)
			elif bias == "after":
				if steps_per_beat > 1 and pos == 1:
					weights.append(1.0)
				elif pos == 0:
					weights.append(0.05)
				else:
					weights.append(0.25)
			else:
				raise ValueError(
					f"Unknown ghost_fill bias {bias!r}. "
					f"Use 'uniform', 'offbeat', 'syncopated', 'before', 'after', "
					f"or a list of floats."
				)

		return weights

	def ghost_fill (
		self,
		pitch: typing.Union[int, str],
		density: float = 0.3,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 35,
		bias: typing.Union[str, typing.List[float]] = "uniform",
		no_overlap: bool = True,
		grid: typing.Optional[int] = None,
		duration: float = 0.1,
		rng: typing.Optional[random.Random] = None,
	) -> None:

		"""Fill the pattern with probability-biased ghost notes.

		A single method for generating musically-aware ghost note layers.
		Combines density control, velocity randomisation, and rhythmic bias
		to produce the micro-detail layering heard in dense electronic
		music production.

		Parameters:
			pitch: MIDI note number or drum name.
			density: Overall density (0.0–1.0).  How many available steps
				receive ghost notes.  0.3 = roughly 30% of steps at peak bias.
			velocity: Single velocity or ``(low, high)`` tuple.  When a tuple,
				each ghost note gets a random velocity in that range.
			bias: Probability distribution shape:

				- ``"uniform"``    — equal probability everywhere
				- ``"offbeat"``    — prefer sixteenth-note off-beats
				- ``"syncopated"`` — prefer eighth-note "and" positions
				- ``"before"``     — cluster just before beat positions
				- ``"after"``      — cluster just after beat positions
				- Or: a list of floats (one per grid step) for a custom field.

			no_overlap: If True (default), skip where same pitch already exists.
				Essential for layering ghosts around hand-placed anchors.
			grid: Grid resolution.  Defaults to the pattern's default grid.
			duration: Note duration in beats (default 0.1).
			rng: Random generator.  Defaults to ``self.rng``.

		Example:
			```python
			p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
			p.hit_steps("snare_1", [4, 12], velocity=95)
			p.ghost_fill("kick_1", density=0.2, velocity=(30, 45),
			             bias="offbeat", no_overlap=True)
			p.ghost_fill("snare_1", density=0.15, velocity=(25, 40),
			             bias="before")
			```
		"""

		if rng is None:
			rng = self.rng

		if grid is None:
			grid = self._default_grid

		if isinstance(bias, list):
			weights = list(bias)
			if len(weights) < grid:
				weights.extend([weights[-1] if weights else 0.0] * (grid - len(weights)))
			elif len(weights) > grid:
				weights = weights[:grid]
		else:
			weights = self._build_ghost_bias(grid, bias)

		max_weight = max(weights) if weights else 1.0

		if max_weight <= 0:
			return

		midi_pitch = self._resolve_pitch(pitch)
		step_duration = self._pattern.length / grid

		for i in range(grid):
			prob = density * weights[i] / max_weight

			if rng.random() >= prob:
				continue

			if no_overlap:
				pulse = int(i * step_duration * subsequence.constants.MIDI_QUARTER_NOTE)
				if pulse in self._pattern.steps:
					if any(n.pitch == midi_pitch for n in self._pattern.steps[pulse].notes):
						continue

			if isinstance(velocity, tuple):
				vel = rng.randint(velocity[0], velocity[1])
			else:
				vel = velocity

			self.note(pitch=pitch, beat=i * step_duration, velocity=vel, duration=duration)

	def cellular (
		self,
		pitch: typing.Union[int, str],
		rule: int = 30,
		generation: typing.Optional[int] = None,
		velocity: int = 60,
		duration: float = 0.1,
		no_overlap: bool = False,
		dropout: float = 0.0,
		rng: typing.Optional[random.Random] = None,
	) -> None:

		"""Generate an evolving rhythm using a cellular automaton.

		Uses an elementary CA (1D binary cellular automaton) to produce
		rhythmic patterns that change organically each bar.  The CA state
		evolves by one generation per cycle, creating patterns that are
		deterministic yet surprising — structured chaos.

		Rule 30 is the default: it produces quasi-random patterns with hidden
		self-similarity.  Rule 90 produces fractal patterns.  Rule 110 is
		Turing-complete.

		Parameters:
			pitch: MIDI note number or drum name.
			rule: Wolfram rule number (0–255).  Default 30.
			generation: CA generation to render.  Defaults to ``self.cycle``
				so the pattern evolves each bar automatically.
			velocity: MIDI velocity.
			duration: Note duration in beats.
			no_overlap: If True, skip where same pitch already exists.
			dropout: Probability (0.0–1.0) of skipping each hit.
			rng: Random generator for dropout.

		Example:
			```python
			p.hit_steps("kick_1", [0, 8], velocity=100)
			p.cellular("kick_1", rule=30, velocity=40, no_overlap=True)
			```
		"""

		if generation is None:
			generation = self.cycle

		if rng is None:
			rng = self.rng

		steps = self._default_grid
		sequence = subsequence.sequence_utils.generate_cellular_automaton(
			steps=steps, rule=rule, generation=generation
		)

		self._place_rhythm_sequence(
			sequence, pitch, velocity, duration, dropout, rng, no_overlap=no_overlap
		)

	def markov (
		self,
		transitions: typing.Dict[str, typing.List[typing.Tuple[str, int]]],
		pitch_map: typing.Dict[str, int],
		velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: float = 0.1,
		step: float = 0.25,
		start: typing.Optional[str] = None,
	) -> None:

		"""Generate a sequence by walking a first-order Markov chain.

		Builds a :class:`~subsequence.weighted_graph.WeightedGraph` from
		``transitions`` and walks it, placing one note per ``step`` beats.
		The probability of each next state depends only on the current one —
		use this to generate basslines, melodies, or rhythm motifs that have
		stylistic coherence without being perfectly repetitive.

		The transition dict uses the same ``(target, weight)`` pair format
		as :meth:`Composition.form`, so the idiom is already familiar.

		Parameters:
			transitions: Mapping of state name to a list of
				``(next_state, weight)`` tuples.  Higher weight means higher
				probability of that transition.
			pitch_map: Mapping of state name to absolute MIDI note number.
				States absent from this dict are walked but produce no note.
			velocity: MIDI velocity for all placed notes (default 100).
			duration: Note duration in beats (default 0.1).
			step: Time between note onsets in beats (default 0.25 = 16th note).
			start: Name of the starting state.  Defaults to the first key
				in ``transitions`` when not provided.

		Raises:
			ValueError: If ``transitions`` or ``pitch_map`` is empty.

		Example:
			```python
			# Walking bassline: root anchors, 3rd and 5th passing tones
			p.markov(
			    transitions={
			        "root": [("3rd", 3), ("5th", 2), ("root", 1)],
			        "3rd":  [("5th", 3), ("root", 2)],
			        "5th":  [("root", 3), ("3rd", 1)],
			    },
			    pitch_map={"root": 52, "3rd": 56, "5th": 59},
			    velocity=80,
			    step=0.5,
			)
			```
		"""

		if not transitions:
			raise ValueError("transitions dict cannot be empty")

		if not pitch_map:
			raise ValueError("pitch_map dict cannot be empty")

		graph: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()

		for source, targets in transitions.items():
			for target, weight in targets:
				graph.add_transition(source, target, weight)

		if start is None:
			start = next(iter(transitions))

		n_steps = int(self._pattern.length / step)

		state = start
		beat = 0.0

		for _ in range(n_steps):

			if state in pitch_map:
				self.note(pitch=pitch_map[state], beat=beat, velocity=velocity, duration=duration)

			state = graph.choose_next(state, self.rng)
			beat += step

	# These methods transform existing notes after they have been placed.
	# Call them at the end of your builder function, after all notes are
	# in position. They operate on self._pattern.steps (the pulse-position
	# dict) and can be chained in any order.

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

	def humanize (
		self,
		timing: float = 0.03,
		velocity: float = 0.0,
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""
		Add subtle random variations to note timing and velocity.

		This makes patterns feel less mechanical by introducing small
		imperfections — the micro-variations that distinguish a played
		performance from a perfectly quantized sequence.

		Called with no arguments, only timing variation is applied
		(velocity defaults to 0.0 — no change). Pass a velocity value
		to also randomise dynamics:

		    # Timing only (default)
		    p.humanize()

		    # Both axes
		    p.humanize(timing=0.04, velocity=0.08)

		    # Stronger feel
		    p.humanize(timing=0.08, velocity=0.15)

		Resolution note: the sequencer runs at 24 PPQN. At 120 BPM, one
		pulse ≈ 20ms. Timing shifts smaller than roughly 0.04 beats may
		have no audible effect because they round to zero pulses.
		Recommended range: timing=0.02–0.08, velocity=0.05–0.15.

		When the composition has a seed set, ``p.rng`` is deterministic,
		so ``p.humanize()`` produces the same result on every run.

		Parameters:
			timing: Maximum timing offset in beats (e.g. 0.05 = ±1.2
				pulses at 24 PPQN). Notes shift by a random amount
				within ``[-timing, +timing]`` beats. Clamped to
				pulse 0 at the lower bound.
			velocity: Maximum velocity scale factor (0.0 to 1.0). Each
				note's velocity is multiplied by a random value in
				``[1 - velocity, 1 + velocity]``, clamped to 1–127.
			rng: Random instance to use. Defaults to ``self.rng``
				(seeded when the composition has a seed).
		"""

		if rng is None:
			rng = self.rng

		max_timing_pulses = timing * subsequence.constants.MIDI_QUARTER_NOTE
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for pulse, step in self._pattern.steps.items():

			if timing != 0.0:
				offset = rng.uniform(-max_timing_pulses, max_timing_pulses)
				new_pulse = max(0, int(round(pulse + offset)))
			else:
				new_pulse = pulse
			
			if new_pulse not in new_steps:
				new_steps[new_pulse] = subsequence.pattern.Step()
			
			# Process notes: randomise velocity once per note, then place in new bucket.
			for note in step.notes:
				if velocity != 0.0:
					scale = rng.uniform(1.0 - velocity, 1.0 + velocity)
					note.velocity = max(1, min(127, int(round(note.velocity * scale))))
				
				new_steps[new_pulse].notes.append(note)

		self._pattern.steps = new_steps


	def cc (self, control: int, value: int, beat: float = 0.0) -> None:

		"""
		Send a single CC message at a beat position.

		Parameters:
			control: MIDI CC number (0–127).
			value: CC value (0–127).
			beat: Beat position within the pattern.
		"""

		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = control,
				value = value
			)
		)


	def cc_ramp (
		self,
		control: int,
		start: int,
		end: int,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 1,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear"
	) -> None:

		"""
		Interpolate a CC value over a beat range.

		Parameters:
			control: MIDI CC number (0–127).
			start: Starting CC value (0–127).
			end: Ending CC value (0–127).
			beat_start: Beat position to begin the ramp.
			beat_end: Beat position to end the ramp. Defaults to pattern length.
			resolution: Pulses between CC messages (1 = every pulse, ~20ms at 120 BPM).
				Higher values (e.g. 2 or 4) reduce MIDI traffic density but may sound
				stepped at slow tempos.
			shape: Easing curve — a name string (e.g. ``"exponential"``) or any
			       callable that maps [0, 1] → [0, 1].  Defaults to ``"linear"``.
			       See :mod:`subsequence.easing` for available shapes.
		"""

		if beat_end is None:
			beat_end = self._pattern.length

		pulse_start = int(beat_start * subsequence.constants.MIDI_QUARTER_NOTE)
		pulse_end = int(beat_end * subsequence.constants.MIDI_QUARTER_NOTE)
		span = pulse_end - pulse_start

		if span <= 0:
			return

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:

			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = int(round(start + (end - start) * eased_t))
			interpolated = max(0, min(127, interpolated))

			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = control,
					value = interpolated
				)
			)

			pulse += resolution


	def pitch_bend (self, value: float, beat: float = 0.0) -> None:

		"""
		Send a single pitch bend message at a beat position.

		Parameters:
			value: Pitch bend amount, normalised from -1.0 to 1.0.
			beat: Beat position within the pattern.
		"""

		midi_value = max(-8192, min(8191, int(round(value * 8192))))
		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'pitchwheel',
				value = midi_value
			)
		)


	def pitch_bend_ramp (
		self,
		start: float,
		end: float,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 1,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear"
	) -> None:

		"""
		Interpolate pitch bend over a beat range.

		Parameters:
			start: Starting pitch bend (-1.0 to 1.0).
			end: Ending pitch bend (-1.0 to 1.0).
			beat_start: Beat position to begin the ramp.
			beat_end: Beat position to end the ramp. Defaults to pattern length.
			resolution: Pulses between pitch bend messages (1 = every pulse).
				Higher values (e.g. 2 or 4) reduce MIDI traffic density but may sound
				stepped at slow tempos.
			shape: Easing curve — a name string (e.g. ``"ease_out"``) or any
			       callable that maps [0, 1] → [0, 1].  Defaults to ``"linear"``.
			       See :mod:`subsequence.easing` for available shapes.
		"""

		if beat_end is None:
			beat_end = self._pattern.length

		pulse_start = int(beat_start * subsequence.constants.MIDI_QUARTER_NOTE)
		pulse_end = int(beat_end * subsequence.constants.MIDI_QUARTER_NOTE)
		span = pulse_end - pulse_start

		if span <= 0:
			return

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:

			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = start + (end - start) * eased_t
			midi_value = max(-8192, min(8191, int(round(interpolated * 8192))))

			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'pitchwheel',
					value = midi_value
				)
			)

			pulse += resolution


	def program_change (self, program: int, beat: float = 0.0) -> None:

		"""
		Send a Program Change message at a beat position.

		Switches the instrument patch on this pattern's MIDI channel.
		Program numbers follow the General MIDI numbering (0–127, where
		e.g. 0 = Acoustic Grand Piano, 40 = Violin, 33 = Electric Bass).

		Parameters:
			program: Program (patch) number (0–127).
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			@composition.pattern(channel=1, length=4)
			def strings (p):
			    p.program_change(48)  # Switch to String Ensemble 1 (GM #49)
			    p.chord("major", root=60, velocity=75)
			```
		"""

		program = max(0, min(127, program))
		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'program_change',
				value = program
			)
		)


	def sysex (self, data: typing.Union[bytes, typing.List[int]], beat: float = 0.0) -> None:

		"""
		Send a System Exclusive (SysEx) message at a beat position.

		SysEx messages allow deep integration with synthesizers and other
		hardware: patch dumps, parameter control, and vendor-specific commands.
		The ``data`` argument should contain only the inner payload bytes,
		without the surrounding ``0xF0`` / ``0xF7`` framing — mido adds those
		automatically.

		Parameters:
			data: SysEx payload as ``bytes`` or a list of integers (0–127).
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			# GM System On — reset a GM-compatible device to defaults
			p.sysex([0x7E, 0x7F, 0x09, 0x01])
			```
		"""

		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'sysex',
				data = bytes(data)
			)
		)


	def osc (self, address: str, *args: typing.Any, beat: float = 0.0) -> None:

		"""
		Send an OSC message at a beat position.

		Requires ``composition.osc()`` to be called before ``composition.play()``.
		If no OSC server is configured the event is silently dropped.

		Parameters:
			address: OSC address path (e.g. ``"/mixer/fader/1"``).
			*args: OSC arguments — float, int, str, or bytes.
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			# Enable a chorus effect at beat 2
			p.osc("/fx/chorus/enable", 1, beat=2.0)

			# Set a mixer pan value immediately
			p.osc("/mixer/pan/1", -0.5)
			```
		"""

		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.osc_events.append(
			subsequence.pattern.OscEvent(
				pulse = pulse,
				address = address,
				args = args
			)
		)


	def osc_ramp (
		self,
		address: str,
		start: float,
		end: float,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 4,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear"
	) -> None:

		"""
		Interpolate an OSC float value over a beat range.

		Generates one OSC message per ``resolution`` pulses, sending the
		interpolated value to ``address`` at each step. Useful for smoothly
		automating mixer faders, effect parameters, and other continuous controls
		on a remote machine.

		Requires ``composition.osc()`` to be called before ``composition.play()``.
		If no OSC server is configured the events are silently dropped.

		Parameters:
			address: OSC address path (e.g. ``"/mixer/fader/1"``).
			start: Starting float value.
			end: Ending float value.
			beat_start: Beat position to begin the ramp (default 0.0).
			beat_end: Beat position to end the ramp. Defaults to pattern length.
			resolution: Pulses between OSC messages (default 4 — approximately
				6 messages per beat at 120 BPM, which is smooth for fader
				automation while keeping UDP traffic light). Use ``resolution=1``
				for pulse-level precision.
			shape: Easing curve — a name string (e.g. ``"ease_in"``) or any
			       callable that maps [0, 1] → [0, 1]. Defaults to ``"linear"``.
			       See :mod:`subsequence.easing` for available shapes.

		Example:
			```python
			# Fade a mixer fader up over 4 beats
			p.osc_ramp("/mixer/fader/1", start=0.0, end=1.0)

			# Ease in a reverb send over the last 2 beats
			p.osc_ramp("/fx/reverb/wet", 0.0, 0.8, beat_start=2, beat_end=4, shape="ease_in")
			```
		"""

		if beat_end is None:
			beat_end = self._pattern.length

		pulse_start = int(beat_start * subsequence.constants.MIDI_QUARTER_NOTE)
		pulse_end = int(beat_end * subsequence.constants.MIDI_QUARTER_NOTE)
		span = pulse_end - pulse_start

		if span <= 0:
			return

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:

			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = start + (end - start) * eased_t

			self._pattern.osc_events.append(
				subsequence.pattern.OscEvent(
					pulse = pulse,
					address = address,
					args = (interpolated,)
				)
			)

			pulse += resolution


	# ── Note-correlated pitch bend ────────────────────────────────────────────

	def _generate_bend_events (
		self,
		start_value: float,
		end_value: float,
		pulse_start: int,
		pulse_end: int,
		resolution: int,
		shape: typing.Union[str, subsequence.easing.EasingFn],
	) -> None:

		"""Generate a series of pitchwheel CcEvents between two pulse positions.

		This is the shared inner loop used by ``bend()``, ``portamento()``, and
		``slide()``.  Appends events directly to ``self._pattern.cc_events``.

		Parameters:
			start_value: Normalised bend at the start of the ramp (-1.0 to 1.0).
			end_value: Normalised bend at the end of the ramp (-1.0 to 1.0).
			pulse_start: Absolute pulse position to start the ramp.
			pulse_end: Absolute pulse position to end the ramp.
			resolution: Number of pulses between consecutive events.
			shape: Easing curve name or callable.
		"""

		span = pulse_end - pulse_start

		if span <= 0:
			return

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:
			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = start_value + (end_value - start_value) * eased_t
			midi_value = max(-8192, min(8191, int(round(interpolated * 8192))))
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'pitchwheel',
					value = midi_value,
				)
			)
			pulse += resolution


	def bend (
		self,
		note: int,
		amount: float,
		start: float = 0.0,
		end: float = 1.0,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
	) -> None:

		"""Bend a specific note by index.

		Generates a pitch bend ramp that covers a fraction of the target note's
		duration, then resets to 0.0 at the next note's onset.  Call this
		*after* ``legato()`` / ``staccato()`` so that note durations are final.

		Parameters:
			note: Note index (0 = first, -1 = last, etc.).
			amount: Target bend normalised to -1.0..1.0 (positive = up).
				With a standard ±2-semitone pitch wheel range, 0.5 = 1 semitone.
			start: Fraction of the note's duration at which the ramp begins
				(0.0 = note onset, default).
			end: Fraction of the note's duration at which the ramp ends
				(1.0 = note end, default).
			shape: Easing curve — a name string (e.g. ``"ease_in"``) or any
			       callable mapping [0, 1] → [0, 1].  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.

		Raises:
			IndexError: If *note* is out of range for the current pattern.

		Example:
			```python
			p.sequence(steps=[0, 4, 8, 12], pitches=midi_notes.E1)
			p.legato(0.95)

			# Bend the last note up one semitone (with ±2 st range), easing in
			p.bend(note=-1, amount=0.5, shape="ease_in")

			# Bend the second note down, starting halfway through
			p.bend(note=1, amount=-0.3, start=0.5)
			```
		"""

		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)

		# Resolve note index (supports negative indexing)
		position = sorted_positions[note]
		note_idx = note if note >= 0 else len(sorted_positions) + note

		# Duration: use the longest note at this step
		step = self._pattern.steps[position]
		note_duration = max(n.duration for n in step.notes)

		# Clamp start/end fractions and compute pulse range for the ramp
		start_clamped = max(0.0, min(1.0, start))
		end_clamped = max(0.0, min(1.0, end))
		bend_start_pulse = position + int(note_duration * start_clamped)
		bend_end_pulse = position + int(note_duration * end_clamped)

		self._generate_bend_events(0.0, amount, bend_start_pulse, bend_end_pulse, resolution, shape)

		# Reset bend at the next note's onset (or pulse 0 for the last note)
		if note_idx < len(sorted_positions) - 1:
			reset_pulse = sorted_positions[note_idx + 1]
		else:
			reset_pulse = 0

		reset_midi = max(-8192, min(8191, int(round(0.0 * 8192))))
		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = reset_pulse,
				message_type = 'pitchwheel',
				value = reset_midi,
			)
		)


	def portamento (
		self,
		time: float = 0.15,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
		bend_range: typing.Optional[float] = 2.0,
		wrap: bool = True,
	) -> None:

		"""Glide between all consecutive notes using pitch bend.

		Generates a pitch bend ramp in the tail of each note, bending toward
		the next note's pitch, then resets at the next note's onset.  Call this
		*after* ``legato()`` / ``staccato()`` so that note durations are final.

		Most effective on mono instruments where pitch bend is per-channel.

		Parameters:
			time: Fraction of each note's duration used for the glide
				(default 0.15 — last 15% of the note).
			shape: Easing curve.  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.
			bend_range: Instrument's pitch wheel range in semitones
				(default 2.0 — standard ±2 st).  Pairs with intervals larger
				than this value are skipped.  Pass ``None`` to disable range
				checking and always generate the bend (large intervals are
				clamped to ±1.0).
			wrap: If ``True`` (default), glide from the last note toward the
				first note of the next cycle.

		Example:
			```python
			p.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])
			p.legato(0.95)

			# Gentle glide across all note transitions
			p.portamento(time=0.15, shape="ease_in_out")

			# Wide bend range (synth set to ±12 semitones)
			p.portamento(time=0.2, bend_range=12)

			# No range limit — bend as far as MIDI allows
			p.portamento(time=0.1, bend_range=None)
			```
		"""

		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		n = len(sorted_positions)

		def _lowest_pitch (pos: int) -> int:
			return min(note.pitch for note in self._pattern.steps[pos].notes)

		def _longest_duration (pos: int) -> int:
			return max(note.duration for note in self._pattern.steps[pos].notes)

		for i in range(n):
			a_pos = sorted_positions[i]
			is_last = (i == n - 1)

			if is_last:
				if not wrap:
					continue
				b_pos = sorted_positions[0]
			else:
				b_pos = sorted_positions[i + 1]

			interval = _lowest_pitch(b_pos) - _lowest_pitch(a_pos)

			if bend_range is not None and abs(interval) > bend_range:
				continue

			normaliser = bend_range if bend_range is not None else 2.0
			amount = max(-1.0, min(1.0, interval / normaliser))

			a_duration = _longest_duration(a_pos)
			glide_start_pulse = a_pos + int(a_duration * (1.0 - time))
			glide_end_pulse = a_pos + a_duration

			self._generate_bend_events(0.0, amount, glide_start_pulse, glide_end_pulse, resolution, shape)

			# Reset at the destination note's onset
			reset_pulse = b_pos if not is_last else 0
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = reset_pulse,
					message_type = 'pitchwheel',
					value = 0,
				)
			)


	def slide (
		self,
		notes: typing.Optional[typing.List[int]] = None,
		steps: typing.Optional[typing.List[int]] = None,
		time: float = 0.15,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
		bend_range: typing.Optional[float] = 2.0,
		wrap: bool = True,
		extend: bool = True,
	) -> None:

		"""TB-303-style selective slide into specific notes.

		Like ``portamento()`` but only applies to flagged destination notes.
		Specify target notes by index (``notes=[1, 3]``) or by step grid
		position (``steps=[4, 12]``).  If ``extend=True`` (default) the
		preceding note's duration is extended to meet the slide target, matching
		the 303's behaviour where slide notes do not retrigger.

		Call this *after* ``legato()`` / ``staccato()`` so that note durations
		are final.

		Parameters:
			notes: List of note indices to slide *into* (0 = first).
				Supports negative indexing.  Mutually exclusive with *steps*.
			steps: List of step grid indices to slide *into*.
				Converted to pulse positions using ``self._default_grid``.
				Mutually exclusive with *notes*.
			time: Fraction of the preceding note's duration used for the glide.
			shape: Easing curve.  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.
			bend_range: Instrument's pitch wheel range in semitones
				(default 2.0).  Pairs with larger intervals are skipped.
				Pass ``None`` to disable range checking.
			wrap: If ``True`` (default), include a wrap-around slide from the
				last note back toward the first.
			extend: If ``True`` (default), extend the preceding note's duration
				to reach the slide target's onset — 303-style legato through
				the glide.

		Raises:
			ValueError: If neither *notes* nor *steps* is provided.

		Example:
			```python
			p.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])
			p.legato(0.95)

			# Slide into the 2nd and 4th notes
			p.slide(notes=[1, 3], time=0.2, shape="ease_in")

			# Same using step grid indices
			p.slide(steps=[4, 12], time=0.2, shape="ease_in")

			# Slide without extending the preceding note
			p.slide(notes=[1, 3], extend=False)
			```
		"""

		if notes is None and steps is None:
			raise ValueError("slide() requires either 'notes' or 'steps'")

		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		n = len(sorted_positions)

		# Resolve flagged pulse positions
		if notes is not None:
			flagged: typing.Set[int] = set()
			for idx in notes:
				flagged.add(sorted_positions[idx])
		else:
			# steps is not None
			step_pulses = total_pulses // self._default_grid
			flagged = set()
			for s in (steps or []):
				flagged.add(s * step_pulses)

		def _lowest_pitch (pos: int) -> int:
			return min(note.pitch for note in self._pattern.steps[pos].notes)

		def _longest_duration (pos: int) -> int:
			return max(note.duration for note in self._pattern.steps[pos].notes)

		for i in range(n):
			a_pos = sorted_positions[i]
			is_last = (i == n - 1)

			if is_last:
				if not wrap:
					continue
				b_pos = sorted_positions[0]
			else:
				b_pos = sorted_positions[i + 1]

			# Only generate glide if the destination is flagged
			if b_pos not in flagged:
				continue

			interval = _lowest_pitch(b_pos) - _lowest_pitch(a_pos)

			if bend_range is not None and abs(interval) > bend_range:
				continue

			normaliser = bend_range if bend_range is not None else 2.0
			amount = max(-1.0, min(1.0, interval / normaliser))

			a_duration = _longest_duration(a_pos)

			# Optionally extend preceding note to meet the target onset (303 style)
			if extend:
				if is_last:
					gap = (total_pulses - a_pos) + sorted_positions[0]
				else:
					gap = b_pos - a_pos
				for note in self._pattern.steps[a_pos].notes:
					note.duration = gap

			glide_start_pulse = a_pos + int(a_duration * (1.0 - time))
			glide_end_pulse = a_pos + a_duration

			self._generate_bend_events(0.0, amount, glide_start_pulse, glide_end_pulse, resolution, shape)

			# Reset at the destination note's onset
			reset_pulse = b_pos if not is_last else 0
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = reset_pulse,
					message_type = 'pitchwheel',
					value = 0,
				)
			)


	def legato (self, ratio: float = 1.0) -> None:

		"""
		Adjust note durations to fill the gap until the next note.
		
		Parameters:
			ratio: How much of the gap to fill (0.0 to 1.0). 
				1.0 is full legato, < 1.0 is staccato.
		"""
		
		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		
		for i, position in enumerate(sorted_positions):
			
			# Calculate gap to next note
			if i < len(sorted_positions) - 1:
				gap = sorted_positions[i + 1] - position
			else:
				# Wrap around: gap is distance to end + distance to first note
				gap = (total_pulses - position) + sorted_positions[0]

			# Apply ratio and enforce minimum duration
			new_duration = max(1, int(gap * ratio))
			
			step = self._pattern.steps[position]
			for note in step.notes:
				note.duration = new_duration

	def staccato (self, ratio: float = 0.5) -> None:
		
		"""
		Set all note durations to a fixed proportion of a beat.
		
		This overrides any existing note durations, acting as a global 
		'gate time' relative to the beat.
		
		Parameters:
			ratio: Duration in beats (relative to a quarter note).
				0.5 = Eighth note duration
				0.25 = Sixteenth note duration
		"""
		
		if ratio <= 0:
			raise ValueError("Staccato ratio must be positive")
			
		duration_pulses = int(ratio * subsequence.constants.MIDI_QUARTER_NOTE)
		duration_pulses = max(1, duration_pulses)
		
		for step in self._pattern.steps.values():
			for note in step.notes:
				note.duration = duration_pulses

	def quantize (self, key: str, mode: str = "ionian") -> None:

		"""
		Snap all notes in the pattern to the nearest pitch in a scale.

		Useful after generative or sensor-driven pitch work (random walks,
		mapping data values to note numbers, etc.) to ensure every note lands
		on a musically valid scale degree.  The quantization is applied in
		place; notes already on a scale degree are left unchanged.

		When a note falls equidistant between two scale tones, the upward
		direction is preferred.

		Parameters:
			key: Root note name (e.g. ``"C"``, ``"F#"``, ``"Bb"``).
			mode: Scale mode.  Any key in :data:`subsequence.intervals.DIATONIC_MODE_MAP`
			      is accepted: ``"ionian"`` (default), ``"dorian"``, ``"minor"``,
			      ``"harmonic_minor"``, etc.

		Example:
			```python
			@composition.pattern(channel=1, length=4)
			def melody (p):
			    for beat in range(16):
			        pitch = 60 + random.randint(-5, 5)
			        p.note(pitch, beat=beat * 0.25)
			    p.quantize("G", "dorian")
			```
		"""

		key_pc = subsequence.chords.key_name_to_pc(key)
		scale_pcs = subsequence.intervals.scale_pitch_classes(key_pc, mode)

		for step in self._pattern.steps.values():
			for note in step.notes:
				note.pitch = subsequence.intervals.quantize_pitch(note.pitch, scale_pcs)


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

	def shift (self, steps: int, grid: typing.Optional[int] = None) -> None:

		"""
		Rotate the pattern by a number of grid steps.

		Parameters:
			steps: Positive values shift right, negative values shift left.
			grid: The grid resolution. Defaults to the pattern's
				``default_grid`` (derived from the decorator's ``length``
				and ``unit``).
		"""

		if grid is None:
			grid = self._default_grid

		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		pulses_per_step = total_pulses / grid
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
