"""Mixin class providing algorithmic and generative pattern-building methods.

This module is not intended to be used directly. ``PatternAlgorithmicMixin``
is inherited by ``PatternBuilder`` in ``pattern_builder.py``.
"""

import dataclasses
import random
import typing
import warnings
import subsequence.declarations
import subsequence.constants
import subsequence.constants.velocity
import subsequence.easing
import subsequence.melodic_state
import subsequence.pattern
import subsequence.sequence_utils
import subsequence.weighted_graph


import logging


logger = logging.getLogger(__name__)


# The most symbols a generator may build in one rebuild.
#
# de_bruijn's output is len(pitches) ** window, so its cost is combinatorial in
# BOTH arguments — window=6 is 64 symbols on two pitches and 262,144 on eight.
# A Span cannot say that: the safe maximum for one argument depends on the
# other, so the bound has to be computed where both are known.
#
# With the default spacing=None every symbol is placed, so an unguarded call
# does not merely take a quarter of a second — it puts a quarter of a million
# notes in one bar and hands them to the scheduler.  The number is a runaway
# guard rather than a musical judgement, and it is generous: 4096 notes is far
# past what a MIDI port can carry in a bar, and de_bruijn's own docstring
# already advises a window of 2 to 4 for practical bar lengths.
_MAX_GENERATED_SYMBOLS = 4096

# How much thin("offbeat") thins the e and a: lightly, so it straightens the
# groove where "upbeat" removes only the & (#3462).
_OFFBEAT_THINS_THE_SIXTEENTHS = 0.3

# Which budget overruns have already been warned about: de_bruijn's (verb,
# pitch-pool size, window) and lsystem's (verb, axiom, rules, generations).
# A rebuild runs every bar, so warning per call would fill the log for as long
# as a control sat past the bound — the first one is the useful one, exactly as
# in declarations.bounded.
_warned_budgets: typing.Set[typing.Tuple[typing.Any, ...]] = set()

# The reaction_diffusion settings already warned about as holding no pattern:
# (grid, steps, feed_rate, kill_rate).  Once each, for the same reason (#3464).
_warned_no_pattern: typing.Set[typing.Tuple[int, int, float, float]] = set()

# Which way the rates were off, by what happened to the field.  Only which way:
# the band that forms a pattern moves with the grid, so there is no one step to
# advise, and at a low feed_rate on 16 steps no kill_rate at all lands in it
# (#3464).  The warning points at the defaults instead, which form one on every
# grid of 8 steps or more.
_NO_PATTERN_CAUSE = {
	"died out": "too much kill for the feed",
	"evened out": "too little kill for the feed",
}


def _fit_to_budget (verb: str, alphabet: int, window: int) -> int:

	"""Return *window*, reduced until ``alphabet ** window`` fits the budget.

	Clamping rather than raising, for the reason the bounds elsewhere clamp: a
	rebuild runs every bar and a failing one costs its pattern that cycle, so a
	control nudged past the bound would silence a part mid-performance.  A
	smaller window is still a complete de Bruijn sequence - just a shorter one -
	so the generator keeps the property it promises.
	"""

	if alphabet < 2:
		return window

	fitted = window

	while fitted > 1 and alphabet ** fitted > _MAX_GENERATED_SYMBOLS:
		fitted -= 1

	if fitted != window and (verb, alphabet, window) not in _warned_budgets:
		_warned_budgets.add((verb, alphabet, window))
		logger.warning(
			f"{verb}(window={window}) over {alphabet} pitches would generate "
			f"{alphabet ** window} notes; using window={fitted} "
			f"({alphabet ** fitted} notes). Use fewer pitches for a longer window."
		)

	return fitted


class PatternAlgorithmicMixin:

	"""Algorithmic and generative note-placement methods for PatternBuilder.

	All methods here operate on ``self._pattern`` (a ``Pattern`` instance)
	and ``self.rng`` (a ``random.Random`` instance), both of which are set
	by ``PatternBuilder.__init__``.
	"""

	# ── Instance attributes provided by PatternBuilder at runtime ────────
	# Declared here so mypy can type-check all methods in this mixin.

	_pattern: subsequence.pattern.Pattern
	_default_grid: int
	_cellular_2d_calls: int
	_self_avoiding_walk_calls: int
	rng: random.Random
	cycle: int
	data: typing.Dict[str, typing.Any]
	key: typing.Optional[str]
	scale: typing.Optional[str]

	if typing.TYPE_CHECKING:
		# Cross-mixin method stubs: implemented by PatternBuilder,
		# called from methods in this mixin.
		import subsequence.pattern_builder  # noqa: F401 — type-checking only
		def note (
			self,
			pitch: subsequence.declarations.Pitch,
			beat: subsequence.declarations.GridBeats,
			velocity: subsequence.declarations.VelocityValue,
			duration: subsequence.declarations.GateBeats,
		) -> "subsequence.pattern_builder.PatternBuilder": ...
		def _resolve_pitch (self, pitch: subsequence.declarations.Pitch) -> int: ...
		def _resolve_pitch_lenient (self, pitch: subsequence.declarations.Pitch) -> typing.Optional[int]: ...
		def _has_pitch_at_beat (self, pitch: subsequence.declarations.Pitch, beat: subsequence.declarations.GridBeats) -> bool: ...

	def _rng_from (self, seed: typing.Optional[int], rng: typing.Optional[random.Random]) -> random.Random:

		"""Resolve the effective random generator for a generative call.

		Determinism has one friendly knob - ``seed=`` (an int) - and one advanced
		form - ``rng=`` (a ``random.Random`` instance).  Precedence, most explicit
		first:

			1. ``rng=`` - an explicit generator you supplied (wins; warns if ``seed=`` was also given).
			2. ``seed=`` - a fresh ``random.Random(seed)``, fixed for this call.
			3. ``self.rng`` - the pattern's own generator (the default; reproducible under the composition seed).
		"""

		if rng is not None:
			if seed is not None:
				warnings.warn("seed= and rng= were both given - rng= wins; pass only one", stacklevel=3)
			return rng

		if seed is not None:
			return random.Random(seed)

		return self.rng

	def _resolve_velocity (self, velocity: subsequence.declarations.VelocityValue, rng: typing.Optional[random.Random] = None) -> int:

		"""Resolve a velocity argument to a single integer.

		Accepts a plain ``int`` (returned unchanged) or a ``(low, high)``
		tuple from which a random value is drawn via ``rng.randint``.
		Centralised here so every note-placement method offers the same
		idiom - ``velocity=(60, 90)`` works wherever ``velocity=`` is
		accepted.

		Raises ``TypeError`` for any other shape so a typo surfaces at
		the call site rather than as a malformed MIDI event later in
		the sequencer dispatch loop.

		Parameters:
			velocity: An int 0-127 or a ``(low, high)`` 2-tuple
				describing an inclusive random range.
			rng: Random generator.  Defaults to ``self.rng``.

		Returns:
			A single integer velocity.
		"""

		# A list counts as a pair.  The catalogue publishes velocity as a
		# "range" control, and a person's choice reaches here as a JSON array —
		# JSON has no tuple, so refusing one made every range control the
		# catalogue advertises impossible to drive (#2349).  A list and a tuple
		# mean the same thing; only the wire told them apart.
		if isinstance(velocity, (tuple, list)):
			if len(velocity) != 2:
				raise ValueError(f"velocity= takes one value or a (low, high) range; for one value per step or row use velocities= where the verb offers it, got {velocity!r}")

			low, high = int(velocity[0]), int(velocity[1])
			if low > high:
				raise ValueError(f"velocity range must be (low, high) with low <= high, got {velocity!r}")

			# Both ends, not just the draw: `hit_steps(velocity=(100, 160))`
			# dropped five notes of eight in one run, because every draw above
			# 127 was rejected at the send and the composer saw an intermittent
			# pattern rather than an error (#3004).  1 at the bottom, because a
			# velocity of 0 is a note-off and not a quiet note.
			subsequence.pattern.check_midi_range(low, "velocity range low", "velocity=", low = 1)
			subsequence.pattern.check_midi_range(high, "velocity range high", "velocity=", low = 1)

			if rng is None:
				rng = self.rng

			return rng.randint(low, high)
		if isinstance(velocity, bool):
			raise TypeError(f"velocity must be a number or a (low, high) pair, got bool: {velocity!r}")
		if isinstance(velocity, (int, float)):
			return int(velocity)
		raise TypeError(
			f"velocity must be a number or a (low, high) pair, got {type(velocity).__name__}: {velocity!r}"
		)

	def _place_gated_sequence (
		self,
		sequence: typing.Sequence[typing.Any],
		event_for: typing.Callable[[int, typing.Any], typing.Optional[typing.Tuple[typing.Union[int, str], subsequence.declarations.VelocityValue, float]]],
		probability: float,
		rng: random.Random,
		no_overlap: bool = False,
	) -> None:

		"""Place per-step events from a sequence, gated by probability and overlap.

		The shared placement kernel: steps are evenly spaced across the pattern
		length; for each step, ``event_for(index, value)`` returns either
		``None`` (a silent step - no probability draw is consumed) or a
		``(pitch, velocity, duration)`` event.  Surviving events pass the
		probability gate and, when ``no_overlap`` is set, the same-pitch check,
		then land via ``self.note()``.

		``(low, high)`` velocity tuples are resolved here, against the caller's
		``rng`` - not left to ``self.note()``, which would draw from the pattern's
		own RNG and silently ignore the ``seed=`` the caller passed.
		"""

		if not sequence:
			return	# nothing to place (e.g. a pattern shorter than one step)

		step_duration = self._pattern.length / len(sequence)

		for i, value in enumerate(sequence):

			event = event_for(i, value)

			if event is None:
				continue

			if probability < 1.0 and rng.random() < (1.0 - probability):
				continue

			pitch, velocity, duration = event

			if no_overlap and self._has_pitch_at_beat(pitch, i * step_duration):
				continue

			self.note(
				pitch=pitch,
				beat=i * step_duration,
				velocity=self._resolve_velocity(velocity, rng),
				duration=duration,
			)

	def _place_rhythm_sequence (
		self,
		sequence: typing.List[int],
		pitch: subsequence.declarations.Pitch,
		velocity: subsequence.declarations.VelocityValue,
		duration: subsequence.declarations.GateBeats,
		probability: float,
		rng: random.Random,
		no_overlap: bool = False
	) -> None:

		"""Place hits from a binary sequence into the pattern.

		Shared implementation for ``euclidean()``, ``bresenham()``, and the
		other single-voice binary-rhythm verbs.  Each active step (1) becomes
		a note; zeros are rests.
		"""

		def _event (i: int, hit_value: typing.Any) -> typing.Optional[typing.Tuple[typing.Union[int, str], subsequence.declarations.VelocityValue, float]]:
			if hit_value == 0:
				return None
			return (pitch, velocity, duration)

		self._place_gated_sequence(sequence, _event, probability, rng, no_overlap=no_overlap)

	def _fit_spacing (
		self,
		verb: str,
		length: int,
		spacing: typing.Optional[subsequence.declarations.GridBeats],
		noun: str = "notes",
	) -> typing.Tuple[float, int]:

		"""Resolve auto-fit or fixed spacing for a generated sequence (the shared core).

		With ``spacing`` None the sequence is spread evenly across the whole pattern,
		so every symbol is heard.  Given a spacing, events land that many beats apart
		and the sequence is truncated to whatever fits in the bar.  Callers slice with
		the returned count - ``sequence[:n_steps]`` - which is a no-op in the auto-fit
		case, so one code path serves both.

		Parameters:
			verb: Calling method name, for the error message.
			length: Number of symbols available to place.
			spacing: Beats between events, or None to auto-fit.
			noun: What the caller places, for the error message.

		Returns:
			A ``(step, n_steps)`` pair - beats between events, and how many to place.

		Raises:
			ValueError: If ``spacing`` is zero or negative.
		"""

		if spacing is None:
			return self._pattern.length / length, length

		if spacing <= 0:
			raise ValueError(f"{verb}() spacing is the time between {noun} in beats - it must be positive, got {spacing}")

		return spacing, int(self._pattern.length / spacing)

	@subsequence.declarations.bounded
	def euclidean (self, pitch: subsequence.declarations.Pitch, pulses: int, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: subsequence.declarations.GateBeats = 0.1, probability: subsequence.declarations.UnitInterval = 1.0, no_overlap: bool = False, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Generate a Euclidean rhythm.

		This distributes a fixed number of 'pulses' as evenly as possible
		across the pattern. This produces many of the world's most
		common musical rhythms.

		Parameters:
			pitch: MIDI note or drum name.
			pulses: Total number of notes to place.
			velocity: MIDI velocity, or a ``(low, high)`` tuple for a
				fresh random draw per hit.
			duration: Note duration.
			probability: Chance (0.0–1.0) that each pulse plays - 1.0 places them all, lower thins the rhythm.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).
			no_overlap: If True, skip steps where a note of the same pitch
				already exists. Useful for layering ghost notes around
				hand-placed anchors.

		Example:
			```python
			# A classic 3-against-16 rhythm
			p.euclidean("kick", pulses=3)
			```
		"""
		rng = self._rng_from(seed, rng)

		steps = self._default_grid
		sequence = subsequence.sequence_utils.generate_euclidean_sequence(steps=steps, pulses=pulses)
		self._place_rhythm_sequence(sequence, pitch, velocity, duration, probability, rng, no_overlap=no_overlap)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def bresenham (self, pitch: subsequence.declarations.Pitch, pulses: int, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: subsequence.declarations.GateBeats = 0.1, probability: subsequence.declarations.UnitInterval = 1.0, no_overlap: bool = False, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Generate a rhythm using the Bresenham line algorithm.

		This is an alternative to Euclidean rhythms that often results in
		slightly different (but still mathematically even) distributions.

		Parameters:
			pitch: MIDI note or drum name.
			pulses: Total number of notes to place.
			velocity: MIDI velocity, or a ``(low, high)`` tuple for a
				fresh random draw per hit.
			duration: Note duration.
			probability: Chance (0.0–1.0) that each pulse plays - 1.0 places them all, lower thins the rhythm.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).
			no_overlap: If True, skip steps where a note of the same pitch
				already exists. Useful for layering ghost notes around
				hand-placed anchors.
		"""
		rng = self._rng_from(seed, rng)

		steps = self._default_grid
		sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=steps, pulses=pulses)
		self._place_rhythm_sequence(sequence, pitch, velocity, duration, probability, rng, no_overlap=no_overlap)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def bresenham_poly (
		self,
		parts: typing.Dict[typing.Union[int, str], float],
		velocity: typing.Union[int, typing.Dict[typing.Union[int, str], int]] = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.1,
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
		probability: subsequence.declarations.UnitInterval = 1.0,
		no_overlap: bool = False,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Distribute multiple drum voices across the pattern using weighted Bresenham.

		Each step is assigned to exactly one voice - voices never overlap, producing
		interlocking rhythmic patterns. Density weights control how frequently each
		voice fires. If the weights sum to less than 1.0, the remainder becomes
		evenly-distributed rests (silent steps).  Weights adding up to more than
		1.0 are scaled down in proportion, so every voice keeps its share of the
		steps: ``{"kick_1": 1.0, "hi_hat_closed": 1.0, "snare_1": 0.1}`` still
		plays its snare.

		Because notes are placed via ``self.note()``, all post-placement transforms
		(``groove``, ``randomize``, ``velocity_shape``, ``rotate``, etc.) work normally.

		Parameters:
			parts: Mapping of pitch (MIDI note or drum name) to density weight.
				Higher weight means more hits per bar. Weights in the range (0, 1]
				are typical; a weight of 0.5 targets roughly one hit every two steps
				while the weights add up to 1 or less.
			velocity: Either a single MIDI velocity applied to all voices, or a dict
				mapping each pitch to its own velocity. Pitches absent from the dict
				fall back to the default velocity (100).
			duration: Note duration in beats (default 0.1).
			grid: Number of steps to divide the pattern into. Defaults to the
				pattern's ``default_grid``.
			probability: Chance (0.0–1.0) that each hit plays - 1.0 places them all, lower thins.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			no_overlap: If True, skip steps where a note of the same pitch already
				exists. Useful for layering ghost notes around hand-placed anchors.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			p.bresenham_poly(
				parts={"kick_1": 0.25, "snare_1": 0.125, "hi_hat_closed": 0.5},
				velocity={"kick_1": 100, "snare_1": 90, "hi_hat_closed": 70},
			)
			```

		Layering with hand-placed hits:
			```python
			# Algorithmic base - interlocking texture, no overlaps within this layer
			p.bresenham_poly(
				parts={"hi_hat_closed": 0.5, "snare_2": 0.1},
				velocity={"hi_hat_closed": 65, "snare_2": 40},
			)
			# Hand-placed anchors on top - these CAN overlap the algorithmic layer
			p.hit_steps("kick_1", [0, 8], velocity=110)
			p.hit_steps("snare_1", [4, 12], velocity=100)
			```

		Stable vs shifting patterns:
			Because the algorithm redistributes all positions when weights change,
			a single voice with a continuously ramping density will shift positions
			every bar. This is great for background texture (hats, shakers) but
			can sound jarring for prominent, distinctive sounds (claps, cowbells).

			**For stable patterns** - use ``bresenham()`` with integer pulses.
			Positions stay fixed until the pulse count steps up::

				pulses = max(1, round(density * 16))
				p.bresenham("hand_clap", pulses=pulses, velocity=95)

			**For shifting texture** - use ``bresenham_poly()`` with continuous
			density. Positions evolve every bar::

				p.bresenham_poly(parts={"hi_hat_closed": density}, velocity=70)

			**To stabilise a solo voice** - pair it with a second voice. More
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
		rng = self._rng_from(seed, rng)

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

		def _event (step_idx: int, voice_idx: typing.Any) -> typing.Optional[typing.Tuple[typing.Union[int, str], subsequence.declarations.VelocityValue, float]]:
			if voice_idx == rest_index:
				return None

			pitch = voice_names[voice_idx]

			if isinstance(velocity, dict):
				vel = velocity.get(pitch, subsequence.constants.velocity.DEFAULT_VELOCITY)
			else:
				vel = velocity

			return (pitch, vel, duration)

		self._place_gated_sequence(sequence, _event, probability, rng, no_overlap=no_overlap)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@staticmethod
	def _steps_per_beat (grid: int, beats: float) -> int:

		"""How many of *grid* steps fall in one beat when they span *beats* beats, at least one.

		From the length the grid really spans, not ``grid // 4``, which took
		every grid as four beats: a 12-step bar of 3/4 has four steps a beat,
		not three.
		"""

		return max(1, round(grid / beats)) if beats > 0 else 1

	@staticmethod
	def build_ghost_bias (grid: int, bias: subsequence.declarations.BiasCurve, beats: float = 4) -> typing.List[float]:

		"""Build probability weights for ghost notes or other generative functions.

		Generates a list of probability weights (values between 0.0 and 1.0) spanning
		a given grid size. These curves shape probability over a beat,
		assigning higher or lower chances of an event occurring based on the rhythmic
		position within the beat (downbeat, offbeat, syncopated 16th note, etc).

		This is a public escape hatch: call it yourself, manipulate the returned list,
		then pass the result as ``bias=`` to :meth:`ghost_fill()`.  This lets you pin
		specific steps, boost a weak position, or combine two named curves.

		Parameters:
			grid: The total number of steps in the sequence (usually 16 or 32).
			bias: The probability distribution shape to generate:

				- ``"uniform"``    - 1.0 everywhere.
				- ``"offbeat"``    - 1.0 on 8th note off-beats (&), 0.3 on 16ths (e/a), 0.05 on downbeats.
				- ``"sixteenths"`` - 1.0 on 16th notes (e/a), 0.3 on 8th off-beats (&), 0.05 on downbeats.
				- ``"before"``     - 1.0 preceding a beat, 0.25 on other 16ths, 0.05 on beats.
				- ``"after"``      - 1.0 following a beat, 0.25 on other 16ths, 0.05 on beats.
				- ``"downbeat"``   - 1.0 on downbeats, 0.15 on 8th off-beats, 0.05 on other 16ths.
				- ``"upbeat"``     - 1.0 on 8th note off-beats only, 0.05 everywhere else.
				- ``"e_and_a"``    - 1.0 on all non-downbeat 16th positions, 0.05 on downbeats.

			beats: How many beats the grid spans, which sets where each beat
				falls (default 4).  ``ghost_fill()`` and ``thin()`` pass their
				pattern's own length, so this matters only when building a
				curve yourself for a pattern that is not four beats long.

		Returns:
			A ``List[float]`` of length ``grid`` where each value is a probability
			multiplier from 0.0 to 1.0.  The list is a plain Python list - modify
			it freely before passing to ``ghost_fill(bias=...)``.

		Example:
			```python
			# Start from a named curve, then zero out beat 3 (step 8) entirely
			# and give the step before the snare (step 11) maximum weight.
			weights = p.build_ghost_bias(16, "sixteenths")
			weights[8] = 0.0   # silence around beat 3
			weights[11] = 1.0  # boost the "and" before beat 4
			p.ghost_fill("snare_1", density=0.25, velocity=(25, 45),
			             bias=weights, no_overlap=True)
			```
		"""

		steps_per_beat = PatternAlgorithmicMixin._steps_per_beat(grid, beats)
		weights: typing.List[float] = []

		for i in range(grid):
			pos = i % steps_per_beat

			if bias == "uniform":
				weights.append(1.0)
			elif bias == "offbeat":
				if pos == 0:
					weights.append(0.05)
				elif steps_per_beat > 1 and pos == steps_per_beat // 2:
					weights.append(1.0)
				else:
					weights.append(0.3)
			elif bias == "sixteenths":
				if pos == 0:
					weights.append(0.05)
				elif steps_per_beat > 1 and pos == steps_per_beat // 2:
					weights.append(0.3)
				else:
					weights.append(1.0)
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
			elif bias == "downbeat":
				if pos == 0:
					weights.append(1.0)
				elif steps_per_beat > 1 and pos == steps_per_beat // 2:
					weights.append(0.15)
				else:
					weights.append(0.05)
			elif bias == "upbeat":
				if steps_per_beat > 1 and pos == steps_per_beat // 2:
					weights.append(1.0)
				else:
					weights.append(0.05)
			elif bias == "e_and_a":
				if pos == 0:
					weights.append(0.05)
				else:
					weights.append(1.0)
			else:
				raise ValueError(
					f"Unknown ghost_fill bias {bias!r}. "
					f"Use 'uniform', 'offbeat', 'sixteenths', 'before', 'after', "
					f"'downbeat', 'upbeat', 'e_and_a', or a list of floats."
				)

		return weights

	@subsequence.declarations.bounded
	def ghost_fill (
		self,
		pitch: subsequence.declarations.Pitch,
		density: subsequence.declarations.UnitInterval = 0.3,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.GHOST_FILL_VELOCITY,
		velocities: typing.Optional[typing.Union[
			typing.Sequence[typing.Union[int, float]],
			typing.Callable[[int], typing.Union[int, float]]
		]] = None,
		bias: typing.Union[subsequence.declarations.BiasCurve, typing.List[float]] = "uniform",
		no_overlap: bool = True,
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
		duration: subsequence.declarations.GateBeats = 0.1,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Fill the pattern with probability-biased ghost notes.

		A single method for generating musically-aware ghost note layers.
		Combines density control, velocity randomisation, and rhythmic bias
		to produce the micro-detail layering heard in dense electronic
		music production.

		Parameters:
			pitch: MIDI note number or drum name.
			density: Overall density (0.0–1.0).  How many available steps
				receive ghost notes.  0.3 = roughly 30% of steps at peak bias.
			velocity: Single velocity, or a ``(low, high)`` range drawn per
				note.  A two-element list means the same range, since JSON
				has no tuple.
			velocities: One value per step, as a list read by step index or a
				callable taking the step index ``i``.  Allows dynamic values
				like Perlin noise curves.  Wins over ``velocity``.
			bias: Probability distribution shape:

				- ``"uniform"``    - equal probability everywhere
				- ``"offbeat"``    - prefer 8th-note off-beats (&)
				- ``"sixteenths"`` - prefer 16th-note subdivisions (e/a)
				- ``"before"``     - cluster just before beat positions
				- ``"after"``      - cluster just after beat positions
				- ``"downbeat"``   - reinforce the beat (inverse of offbeat)
				- ``"upbeat"``     - strictly 8th-note off-beats only
				- ``"e_and_a"``    - all non-downbeat 16th positions
				- Or: a list of floats (one per grid step) for a custom field.
				  Use :meth:`build_ghost_bias` to generate a named curve
				  and then modify specific steps before passing it here.

			no_overlap: If True (default), skip where same pitch already exists.
				Essential for layering ghosts around hand-placed anchors.
			grid: Grid resolution.  Defaults to the pattern's default grid.
			duration: Note duration in beats (default 0.1).
			seed: Fix the ghost layer for this call (an int); omit to use the
				pattern's RNG.

				**Tip - freeze the layer each cycle:**  ``seed=`` starts a fresh
				random stream on every rebuild, so the same steps - and the same
				``(low, high)`` velocity draws - are chosen on every cycle: the
				ghost layer is locked in place.  The default ``self.rng``
				advances state across rebuilds, so placement differs every cycle.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
			p.hit_steps("snare_1", [4, 12], velocity=95)

			# Different ghost placement each cycle (default)
			p.ghost_fill("kick_1", density=0.2, velocity=(30, 45),
			             bias="sixteenths", no_overlap=True)

			# The same ghost layer every cycle - placement frozen
			p.ghost_fill("snare_1", density=0.15, velocity=(25, 40),
			             bias="before", seed=42)
			```
		"""

		rng = self._rng_from(seed, rng)

		if grid is None:
			grid = self._default_grid

		if grid <= 0:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		if isinstance(bias, list):
			weights = list(bias)
			if len(weights) < grid:
				weights.extend([weights[-1] if weights else 0.0] * (grid - len(weights)))
			elif len(weights) > grid:
				weights = weights[:grid]
		else:
			weights = self.build_ghost_bias(grid, bias, beats = self._pattern.length)

		max_weight = max(weights) if weights else 1.0

		if max_weight <= 0:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		step_duration = self._pattern.length / grid

		for i in range(grid):
			prob = density * weights[i] / max_weight

			if rng.random() >= prob:
				continue

			if no_overlap and self._has_pitch_at_beat(pitch, i * step_duration):
				continue

			if velocities is None:
				vel = self._resolve_velocity(velocity, rng)
			elif callable(velocities):
				vel = int(velocities(i))
			else:
				vel = int(velocities[i % len(velocities)])

			self.note(pitch=pitch, beat=i * step_duration, velocity=vel, duration=duration)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def cellular_1d (
		self,
		pitch: subsequence.declarations.Pitch,
		rule: int = 30,
		generation: typing.Optional[int] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_CA_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.1,
		no_overlap: bool = False,
		probability: subsequence.declarations.UnitInterval = 1.0,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate an evolving rhythm using a 1D cellular automaton.

		Uses an elementary CA (1D binary cellular automaton) to produce
		rhythmic patterns that change organically each bar.  The CA state
		evolves by one generation per cycle, creating patterns that are
		deterministic yet surprising - structured chaos.

		Rule 30 is the default: it produces quasi-random patterns with hidden
		self-similarity.  Rule 90 produces fractal patterns.  Rule 110 is
		Turing-complete.

		Parameters:
			pitch: MIDI note number or drum name.
			rule: Wolfram rule number (0–255).  Default 30.
			generation: CA generation to render.  Defaults to ``self.cycle``
				so the pattern evolves each bar automatically.
			velocity: MIDI velocity, or a ``(low, high)`` tuple for a
				fresh random draw per hit.
			duration: Note duration in beats.
			no_overlap: If True, skip where same pitch already exists.
			probability: Chance (0.0–1.0) that each hit plays - 1.0 places them all, lower thins.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			p.hit_steps("kick_1", [0, 8], velocity=100)
			p.cellular_1d("kick_1", rule=30, velocity=40, no_overlap=True)
			```
		"""

		if generation is None:
			generation = self.cycle
		rng = self._rng_from(seed, rng)

		steps = self._default_grid
		sequence = subsequence.sequence_utils.generate_cellular_automaton_1d(
			steps=steps, rule=rule, generation=generation
		)

		self._place_rhythm_sequence(
			sequence, pitch, velocity, duration, probability, rng, no_overlap=no_overlap
		)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def _grid_seed_drawn_once (self, call: int, rng: random.Random) -> int:

		"""The seed call number *call* of cellular_2d() drew for its random start, drawn now if never.

		It used to be drawn afresh on every rebuild, so each bar was an unrelated
		random fill, the automaton never ran, and a bar at cycle 400 cost 40 ms to
		evolve from nothing (#3072).  The pattern keeps the draw beside the stream
		it came from: reroll() deals the pattern a new stream, which draws a new
		grid, and lock() re-deals the same stream every bar, which draws the same
		one again.  An unseeded composition gives its patterns no stream, so the
		draw is kept for the run.
		"""

		stream = getattr(self._pattern, "_rng", None)
		kept = self._pattern._drawn_grid_seeds.get(call)

		if kept is not None and kept[0] is stream:
			return kept[1]

		drawn = rng.randint(2, 2_147_483_646)
		self._pattern._drawn_grid_seeds[call] = (stream, drawn)

		return drawn

	@subsequence.declarations.bounded
	def cellular_2d (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		rule: str = "B368/S245",
		generation: typing.Optional[int] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_CA_VELOCITY,
		velocities: typing.Optional[typing.List[int]] = None,
		duration: subsequence.declarations.GateBeats = 0.1,
		no_overlap: bool = False,
		probability: subsequence.declarations.UnitInterval = 1.0,
		initial_state: typing.Union[subsequence.declarations.CellularSeed, typing.List[typing.List[int]]] = "random",
		density: subsequence.declarations.UnitInterval = 0.5,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate polyphonic patterns using a 2D Life-like cellular automaton.

		Evolves a 2D grid where rows map to pitches or instruments and columns
		map to time steps.  Live cells in the final generation become note
		onsets, producing patterns with spatial structure that evolves each bar.

		The default rule B368/S245 (Morley/"Move") produces chaotic, active
		patterns.  B3/S23 is Conway's Life; B36/S23 is HighLife.

		Left alone, most grids this small die out or settle into a loop within
		tens of bars.  So a random start, the default, is redrawn whenever it
		dies out or falls into a loop of one or two bars, and the part carries
		on with a fresh grid instead of falling silent for good.

		Parameters:
			pitches: MIDI note numbers or drum names, one per row.  Row 0
			         maps to the first pitch.
			rule: Birth/Survival notation, e.g. ``"B3/S23"`` for Conway's
			      Life, ``"B368/S245"`` for Morley.
			generation: CA generation to render.  Defaults to ``self.cycle``
			    so the grid evolves each bar automatically.
			velocity: Single MIDI velocity for every row, or a ``(low, high)``
			          range drawn per note.
			velocities: One value per row.  Wins over ``velocity``.
			duration: Note duration in beats.
			no_overlap: If True, skip notes where same pitch already exists.
			probability: Chance (0.0–1.0) that each live cell plays - 1.0 places them all, lower thins.
			initial_state: The generation-0 grid.  ``"random"`` (default) fills
			      cells with probability *density*.  The fill is drawn once for
			      the pattern, from the composition's seed when it has one, so a
			      seeded piece plays the same on every run, and it then evolves a
			      generation per bar, redrawn as described above.  ``"center"``
			      lights a single cell at the centre, which lives only under a
			      rule that can grow a lone cell (one with B1, B2 or S0); under the
			      rules above it plays once and falls silent.  An explicit
			      ``list[list[int]]`` (rows × cols) starts from that grid.  Neither
			      is ever redrawn.
			density: Fill probability for ``initial_state="random"`` (0.0–1.0).
			seed: An int that fixes the ``"random"`` fill, and every grid drawn
			      after it, whatever the composition's seed.  Ignored for
			      ``"center"`` or an explicit grid (a warning is emitted if
			      passed there).
			rng: Random generator for the probability thinning, and for the one
			     draw of a random start with no *seed*.  Defaults to
			     ``self.rng``.

		Example:
			```python
			pitches = [36, 38, 42, 46]  # kick, snare, hihat, open hihat
			p.cellular_2d(pitches, rule="B3/S23", initial_state="random", seed=7, density=0.3)
			```
		"""

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		if velocities is not None and not velocities:
			raise ValueError("velocities list cannot be empty")

		if generation is None:
			generation = self.cycle

		if rng is None:
			rng = self.rng

		# Which of this build's cellular_2d() calls this is, so a random start
		# finds the seed it drew in an earlier build (#3072).
		call = self._cellular_2d_calls
		self._cellular_2d_calls += 1

		# Translate (initial_state, seed) into the underlying generator's seed arg,
		# which stays int-or-grid: 1 = single centre cell, any other int = an
		# RNG-seeded fill at *density*, a grid = an explicit starting state.
		grid_seed: typing.Union[int, typing.List[typing.List[int]]]
		if isinstance(initial_state, list):
			grid_seed = initial_state
		elif initial_state == "center":
			grid_seed = 1
		elif initial_state == "random":
			if isinstance(seed, int):
				# The generator reserves 1 as its centre-cell sentinel, so remap
				# seed=1 to a fixed surrogate - every seed stays deterministic.
				grid_seed = seed if seed != 1 else -1
			else:
				grid_seed = self._grid_seed_drawn_once(call, rng)
		else:
			raise ValueError(f"cellular_2d(): initial_state must be \"center\", \"random\", or a grid - got {initial_state!r}")

		if seed is not None and initial_state != "random":
			warnings.warn(
				f"cellular_2d(): seed= only affects initial_state=\"random\" and is ignored for "
				f"initial_state={initial_state!r} - pass initial_state=\"random\" to seed the grid",
				UserWarning,
				stacklevel = 2,
			)

		cols = self._default_grid
		rows = len(pitches)

		if initial_state == "random" and isinstance(grid_seed, int):
			# Redrawn whenever it dies out or settles into a one- or two-bar loop,
			# so the part never falls silent for good (#3072, #3498).  "center" and
			# an explicit grid live or die as the rule decides.
			grid = subsequence.sequence_utils._ca_2d_redrawing(
				rows=rows,
				cols=cols,
				rule=rule,
				generation=generation,
				seed=grid_seed,
				density=density,
			)
		else:
			grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
				rows=rows,
				cols=cols,
				rule=rule,
				generation=generation,
				seed=grid_seed,
				density=density,
			)

		for row_idx, pitch in enumerate(pitches):
			row_velocity: subsequence.declarations.VelocityValue

			if velocities is not None:
				row_velocity = int(velocities[row_idx % len(velocities)])
			elif isinstance(velocity, (tuple, list)):
				# (low, high) range - resolved per placed note downstream.
				row_velocity = velocity
			else:
				row_velocity = int(velocity)

			self._place_rhythm_sequence(
				grid[row_idx], pitch, row_velocity, duration, probability, rng, no_overlap=no_overlap
			)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def markov (
		self,
		transitions: typing.Dict[str, typing.List[typing.Tuple[str, int]]],
		pitch_map: typing.Dict[str, int],
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.1,
		spacing: subsequence.declarations.GridBeats = 0.25,
		start: typing.Optional[str] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a sequence by walking a first-order Markov chain.

		Builds a :class:`~subsequence.weighted_graph.WeightedGraph` from
		``transitions`` and walks it, placing one note per ``spacing`` beats.
		The probability of each next state depends only on the current one -
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
			velocity: MIDI velocity for all placed notes (default 100),
				or a ``(low, high)`` tuple for a fresh random draw per step.
			duration: Note duration in beats (default 0.1).
			spacing: Time between note onsets in beats (default 0.25 = 16th note).
			start: Name of the starting state.  Defaults to the first key
				in ``transitions`` when not provided.
			seed: Fix the walk for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

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
			    spacing=0.5,
			)
			```
		"""

		rng = self._rng_from(seed, rng)

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

		if spacing <= 0:
			raise ValueError(f"markov() spacing is the time between notes in beats - it must be positive, got {spacing}")

		n_steps = int(self._pattern.length / spacing)

		state = start
		beat = 0.0

		for _ in range(n_steps):

			if state in pitch_map:
				vel = self._resolve_velocity(velocity, rng)
				self.note(pitch=pitch_map[state], beat=beat, velocity=vel, duration=duration)

			state = graph.choose_next(state, rng)
			beat += spacing
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def melody (
		self,
		state: subsequence.melodic_state.MelodicState,
		spacing: subsequence.declarations.GridBeats = 0.25,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		chord_tones: typing.Optional[typing.List[int]] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a melodic line by querying a persistent :class:`~subsequence.melodic_state.MelodicState`.

		Places one note (or rest) per ``spacing`` beats for the full pattern
		length.  Pitch selection is guided by the NIR cognitive model inside
		``state``: after a large leap the model expects a direction reversal;
		after a small step it expects continuation.  Chord tones, range
		gravity, and a pitch-diversity penalty further shape the output.

		Because ``state`` lives outside the pattern builder and persists
		across bar rebuilds, melodic continuity is maintained automatically -
		no manual history management is required.

		Parameters:
			state: Persistent :class:`~subsequence.melodic_state.MelodicState`
			    instance created once at module level.
			spacing: Time between note onsets in beats (default 0.25 = 16th note).
			velocity: MIDI velocity.  An ``int`` applies a fixed level; a
			    ``(low, high)`` tuple draws uniformly from that range each spacing.
			duration: Note duration in beats (default 0.2 - slightly shorter
			    than a 16th note, giving a crisp attack).
			chord_tones: Optional list of MIDI note numbers that are chord
			    tones this bar (e.g. from ``chord.tones(root)``).  Chord-tone
			    pitch classes receive a ``chord_weight`` bonus inside ``state``.
			seed: Fix the walk for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			melody_state = subsequence.MelodicState(
			    key="A", mode="aeolian",
			    low=60, high=84,
			    nir_strength=0.6,
			    chord_weight=0.4,
			)

			@composition.pattern(channel=4, beats=4)
			def lead (p, chord):
			    tones = chord.tones(72) if chord else None
			    p.melody(melody_state, spacing=0.5, velocity=(70, 100), chord_tones=tones)
			```
		"""

		rng = self._rng_from(seed, rng)

		# A state built without key/mode adopts the composition's here
		# (idempotent — explicit constructor arguments always win).
		state.configure_defaults(self.key, self.scale)

		if spacing <= 0:
			raise ValueError(f"melody() spacing is the time between notes in beats - it must be positive, got {spacing}")

		n_steps = int(self._pattern.length / spacing)
		beat = 0.0

		for _ in range(n_steps):

			pitch = state.choose_next(chord_tones, rng, beat=beat)

			if pitch is not None:
				vel = self._resolve_velocity(velocity, rng)
				self.note(pitch=pitch, beat=beat, velocity=vel, duration=duration)

			beat += spacing
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def lsystem (
		self,
		pitch_map: typing.Dict[str, typing.Union[int, str]],
		axiom: str,
		rules: typing.Dict[str, typing.Union[str, typing.List[typing.Tuple[str, float]]]],
		generations: int = 3,
		spacing: typing.Optional[subsequence.declarations.GridBeats] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		offset: typing.Annotated[int, subsequence.declarations.Span(0)] = 0,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a note sequence using L-system string rewriting.

		Expands ``axiom`` by applying ``rules`` for ``generations``
		iterations, then walks the resulting string placing a note for
		each character found in ``pitch_map``.  Unmapped characters are
		silent rests - they advance time but produce no note.

		The defining musical property is self-similarity: patterns repeat
		at different time scales.  The Fibonacci-word rule (``A → AB``,
		``B → A``) spaces hits evenly but never quite repeats within the
		string.  Koch and dragon curve rules produce fractal melodic
		contours.  (Hits land on the grid here - for events placed *off* the
		grid by the golden ratio, see :meth:`golden`.)

		With ``spacing=None`` (default) the entire expanded string is fitted
		into the bar: each generation makes the notes denser by as much as
		the rules lengthen the string - about 1.6 times for the Fibonacci
		word below - while preserving the overall shape.  With a fixed
		``spacing`` the string is truncated to fit and the density stays
		constant.

		On its own every bar plays the same string from its start.
		``offset=`` treats the string as a loop and starts the bar that many
		symbols in, wrapping round to its start.  With ``spacing=None`` the
		bar still holds the whole string, turned: ``offset=p.cycle`` turns it
		a symbol further each bar - 21 different bars for the six-generation
		Fibonacci word before it comes round again.  With a fixed
		``spacing``, ``offset=p.cycle * 16`` (sixteen quarter-beat symbols to
		a four-beat bar) walks on through the string a bar at a time; more
		generations make a longer walk before it wraps.

		Parameters:
			pitch_map: Maps single characters to MIDI notes or drum names.
				Characters absent from the map produce rests.
			axiom: Starting string (e.g. ``"A"``).
			rules: Production rules.  Deterministic: ``{"A": "AB"}``.
				Stochastic: ``{"A": [("AB", 3), ("BA", 1)]}``.
			generations: Rewriting iterations.  String length grows
				exponentially - keep this to 3–8 for practical use.
			spacing: Time between symbols in beats.  ``None`` (default)
				auto-fits the full expanded string into the bar.  A float
				uses fixed spacing and truncates excess symbols.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises
				per note.
			duration: Note duration in beats.
			offset: How many symbols into the string the bar starts, wrapping
				round to its start.  0 (the default) starts every bar at the
				beginning.
			seed: Fix the stochastic-rule choices and velocity draws for this
				call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Fibonacci-word kick rhythm - self-similar hit spacing
			p.lsystem(
			    pitch_map={"A": "kick_1"},
			    axiom="A",
			    rules={"A": "AB", "B": "A"},
			    generations=6,
			    velocity=80,
			)

			# The same word, turned a symbol further each bar
			p.lsystem(
			    pitch_map={"A": "kick_1"},
			    axiom="A",
			    rules={"A": "AB", "B": "A"},
			    generations=6,
			    velocity=80,
			    offset=p.cycle,
			)

			# Fractal melody over scale notes
			p.lsystem(
			    pitch_map={"F": 60, "G": 62, "+": 64, "-": 67},
			    axiom="F",
			    rules={"F": "F+G", "G": "-F"},
			    generations=4,
			    spacing=0.25,
			    velocity=(70, 100),
			)
			```
		"""

		rng = self._rng_from(seed, rng)

		# The kernel stops at the last whole generation that fits and reports
		# how many it applied, so a runaway rule set is bounded without the
		# kernel knowing anything about budgets or logging.
		expanded, applied = subsequence.sequence_utils._lsystem_expand_reporting(
			axiom = axiom,
			rules = rules,
			generations = generations,
			rng = rng,
			max_length = _MAX_GENERATED_SYMBOLS,
		)

		if applied < generations:
			# Keyed on the rule set itself: two sets of the same size are two
			# different things to be told about (#2966).
			key = ("lsystem", axiom, repr(sorted(rules.items())), generations)
			if key not in _warned_budgets:
				_warned_budgets.add(key)
				logger.warning(
					f"lsystem(generations={generations}) grows past the {_MAX_GENERATED_SYMBOLS}-note "
					f"budget; stopped at generation {applied} ({len(expanded)} notes). "
					"Use fewer generations, or a rule set that grows more slowly."
				)

		if not expanded:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		# The string is a loop and offset says where on it the bar starts, so
		# with spacing=None the bar still holds all of it, turned (#3470).
		turn = offset % len(expanded)
		expanded = expanded[turn:] + expanded[:turn]

		auto_step, n_steps = self._fit_spacing("lsystem", len(expanded), spacing, noun="symbols")
		symbols = expanded[:n_steps]

		beat = 0.0

		for symbol in symbols:
			if symbol in pitch_map:
				vel = self._resolve_velocity(velocity, rng)
				self.note(
					pitch=pitch_map[symbol],
					beat=beat,
					velocity=vel,
					duration=duration,
				)
			beat += auto_step
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def thue_morse (
		self,
		pitch: subsequence.declarations.Pitch,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.1,
		pitch_b: typing.Optional[subsequence.declarations.Pitch] = None,
		velocity_b: typing.Optional[subsequence.declarations.VelocityValue] = None,
		no_overlap: bool = False,
		probability: subsequence.declarations.UnitInterval = 1.0,
		offset: typing.Annotated[int, subsequence.declarations.Span(0)] = 0,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Place notes using the Thue-Morse aperiodic binary sequence.

		The Thue-Morse sequence (0 1 1 0 1 0 0 1 1 0 0 1 0 1 1 0 …) is
		perfectly balanced, overlap-free, and self-similar but never periodic.
		Within a bar it never settles into a simple repeating figure - a quality
		distinct from Euclidean rhythms (evenly spaced) and cellular automata
		(rule-driven evolution).

		On its own it plays the start of the sequence, so every bar is the
		same.  ``offset=`` starts further in, and ``offset=p.cycle * p.grid``
		carries the sequence on from bar to bar.  On 8, 16 or 32 steps that
		alternates the first bar with its mirror image - hits and rests
		swapped, or the two pitches - and the bars themselves fall in
		Thue-Morse order; on 12 or 24 steps it gives six different bars.
		``offset=p.cycle`` slides it on a step a bar instead, for far more
		variety: 46 different bars in 64 on 16 steps.

		In **single-pitch mode** (default), notes are placed at positions where
		the sequence is 1.  In **two-pitch mode** (``pitch_b`` given), ``pitch``
		flips to the 0-positions and ``pitch_b`` takes the 1-positions - useful
		for alternating two drums or two chord tones.

		Parameters:
			pitch: Pitch (MIDI note number or drum name).  Placed at the
			    sequence's 1-positions in single-pitch mode; at the
			    0-positions when ``pitch_b`` takes over the 1s.
			velocity: MIDI velocity for ``pitch``, or a ``(low, high)``
			    tuple for a fresh random draw per hit.
			duration: Note duration in beats.
			pitch_b: Optional second pitch placed at sequence-1 positions.
			    When set, all steps produce a note (no rests).
			velocity_b: Velocity for ``pitch_b`` (int or ``(low, high)``
			    tuple).  Defaults to ``velocity``.
			no_overlap: Skip steps where ``pitch`` is already sounding.
			probability: Chance (0.0–1.0) that each active step plays - 1.0 places them all, lower thins.
			offset: How many steps into the sequence the bar starts.  0 (the
			    default) plays its start every bar.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Single-pitch Thue-Morse kick
			p.thue_morse("kick_1", velocity=100)

			# Two-pitch mode: alternate kick and snare
			p.thue_morse("kick_1", pitch_b="snare_1", velocity=100)

			# Carried on from bar to bar: the first bar, then its mirror, in Thue-Morse order
			p.thue_morse("kick_1", pitch_b="snare_1", offset=p.cycle * p.grid)
			```
		"""
		rng = self._rng_from(seed, rng)

		sequence = subsequence.sequence_utils.thue_morse(self._default_grid, offset=offset)

		if not sequence:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		if pitch_b is None:
			self._place_rhythm_sequence(sequence, pitch, velocity, duration, probability, rng, no_overlap)
		else:
			if velocity_b is None:
				velocity_b = velocity

			# Every step sounds one of the two voices (no rests), and no_overlap
			# is honoured against whichever voice the step would place.
			second_pitch = pitch_b
			second_velocity = velocity_b

			def _event (i: int, val: typing.Any) -> typing.Optional[typing.Tuple[typing.Union[int, str], subsequence.declarations.VelocityValue, float]]:
				if val == 0:
					return (pitch, velocity, duration)
				return (second_pitch, second_velocity, duration)

			self._place_gated_sequence(sequence, _event, probability, rng, no_overlap=no_overlap)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def de_bruijn (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		window: int = 2,
		spacing: typing.Optional[subsequence.declarations.GridBeats] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a melody that exhaustively traverses all pitch subsequences.

		A de Bruijn sequence B(k, n) over an alphabet of size ``k`` with window
		``n`` contains every possible subsequence of length ``n`` exactly once
		(cyclically).  Mapping each symbol to a pitch produces a melody that
		systematically explores all possible ``n``-gram transitions - every
		permutation of ``window`` consecutive pitches appears exactly once.

		With ``spacing=None`` (default) the full sequence is auto-fitted into the
		bar, matching the behaviour of :meth:`lsystem`.  With a fixed ``spacing``
		the sequence is truncated to fill the available beats.

		Parameters:
			pitches: List of MIDI note numbers or note strings.  The alphabet
			    size ``k`` is ``len(pitches)``.
			window: Subsequence length ``n``.  The output has ``len(pitches) ** window``
			    notes.  Keep small (2–4) for practical bar lengths - the cost is
			    combinatorial in both arguments, so a window that is modest over
			    two pitches is enormous over eight.  A window whose output would
			    exceed the generated-note budget is reduced (warned once) to the
			    largest that fits, which is still a complete de Bruijn sequence.
			spacing: Time between notes in beats.  ``None`` auto-fits the sequence
			    into the bar; a float uses fixed spacing and truncates.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.
			seed: Fix the velocity draws for this call (an int) - the note order
			    itself is deterministic; omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# All 2-note combinations of a pentatonic scale
			p.de_bruijn([60, 62, 64, 67, 69], window=2, velocity=(60, 100))
			```
		"""

		rng = self._rng_from(seed, rng)

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		k = len(pitches)
		sequence = subsequence.sequence_utils.de_bruijn(k, _fit_to_budget("de_bruijn", k, window))

		if not sequence:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		auto_step, n_steps = self._fit_spacing("de_bruijn", len(sequence), spacing)
		symbols = sequence[:n_steps]

		beat = 0.0

		for idx in symbols:
			vel = self._resolve_velocity(velocity, rng)
			self.note(pitch=pitches[idx], beat=beat, velocity=vel, duration=duration)
			beat += auto_step
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def golden (
		self,
		pitches: typing.Union[subsequence.declarations.Pitch, typing.Sequence[subsequence.declarations.Pitch]],
		count: int,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Place notes at golden-ratio-spaced beat positions.

		Uses the golden angle method - ``position_i = frac(i × φ) × bar_length``,
		where ``frac`` keeps only the fractional part - to distribute ``count``
		events across the bar as a low-discrepancy (sunflower-seed) spread.
		The result is sorted into ascending time order.  Unlike a Euclidean rhythm (maximally even
		spacing on a fixed grid), golden-ratio timing is irrational and places
		events off-grid in a way that sounds organic and avoids metronomic
		repetition.

		Give a single pitch (or drum name) for one voice, or a list to cycle a pool
		through the placed notes in time order - the first note takes the first
		pitch, and the pool repeats once exhausted.  The positions themselves never
		change, so swapping one pitch for a pool re-voices a rhythm without moving it.

		This shapes *time* only - the pool is walked in order, not chosen by the
		golden ratio.  For the Fibonacci integer sequence as pitch material, see
		:meth:`fibonacci`.

		Parameters:
			pitches: A MIDI note number or drum name, or a list of them to cycle.
			count: Number of notes to place.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.
			seed: Fix the velocity draws for this call (an int) - the timing
				itself is deterministic; omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Raises:
			ValueError: If ``pitches`` is an empty list.

		Example:
			```python
			# 11 hi-hat hits with golden-ratio spacing
			p.golden("hi_hat_closed", count=11, velocity=(60, 90))

			# The same spread, cycling a pentatonic pool
			p.golden([60, 62, 65, 67, 70], count=11)
			```
		"""

		rng = self._rng_from(seed, rng)

		# A bool is an int to Python, so guard it explicitly — p.golden(True) would
		# otherwise place pitch 1 rather than telling the caller what went wrong.
		if isinstance(pitches, bool):
			raise TypeError(f"golden() pitches must be a note number, drum name, or list of them - got {pitches!r}")

		pool: typing.List[typing.Union[int, str]] = [pitches] if isinstance(pitches, (int, str)) else list(pitches)

		if not pool:
			raise ValueError("pitches list cannot be empty")

		beats = subsequence.sequence_utils.golden_rhythm(count, self._pattern.length)

		for i, beat in enumerate(beats):
			vel = self._resolve_velocity(velocity, rng)
			self.note(pitch=pool[i % len(pool)], beat=beat, velocity=vel, duration=duration)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def recaman (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		count: typing.Optional[int] = None,
		spacing: typing.Optional[subsequence.declarations.GridBeats] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		start: int = 0,
		skip: int = 0,
		octave_span: typing.Annotated[int, subsequence.declarations.Unit("octaves")] = 2,
		mapping: typing.Optional[
			typing.Callable[
				[int, int],
				typing.Optional[typing.Tuple[typing.Union[int, str], int, float]],
			]
		] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Play Recamán's sequence - a melody that wanders off and never repeats.

		The rule is *step back if you can, otherwise step forward*, by one at the first
		note, two at the second, and so on.  Because the steps keep growing, the line
		lurches ever wider, and the back-and-forth splits into **two voices**: alternate
		notes sink while the ones between them climb, so a single line is heard as two
		moving apart.  That wedge is the reason to reach for this - nothing else here
		produces it, and it is deterministic, so the same call always gives it back.

		It is at its best over one or two bars.  Left running much longer the sequence
		spreads out and starts to sound like a random walk.

		Because the numbers grow without limit, they are read as *scale degrees plus
		register*: each value picks a note from the pool and how many octaves up to put
		it, which is what turns the widening into an audible opening-out.  Give a pool
		of **one octave** - the degrees of your scale.  A multi-octave pool works, but
		it stacks octaves on octaves and the wedge gets very wide very fast.

		The sister generator :meth:`fibonacci` always returns home; this one never does.

		Parameters:
			pitches: One octave of pitches - the degrees values are drawn from.
			count: How many notes to place.  Defaults to the pattern's grid.
			spacing: Beats between notes.  Omit to spread them across the bar.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.
			start: The first value.  From 2 upward this is genuinely new material, and
				the higher it is the longer the melody's opening descent.  ``0`` and
				``1`` give the same shape, so step by more than one to hear a change -
				``start=2 + p.cycle * 3`` evolves the line every cycle.
			skip: Start further along the sequence, discarding this many values.
			octave_span: How many octaves the line may climb before it turns back.
				Set to 0 to keep everything in one octave.
			mapping: ``f(value, index)`` returning ``(pitch, velocity, duration)`` to
				place, or None for a rest - full control over how numbers become notes.
			seed: Fix the velocity draws for this call (an int) - the pitches and
				timing are deterministic; omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Raises:
			ValueError: If ``pitches`` is empty, ``spacing`` is not positive, or
				``skip`` is negative.

		Example:
			```python
			# The wedge, over one octave of C minor.
			p.recaman(subsequence.intervals.scale_notes("C", "minor", low=60, high=71))

			# A line that reinvents itself every cycle.
			p.recaman([60, 62, 63, 65, 67, 68, 71], start=2 + p.cycle * 3)
			```
		"""

		rng = self._rng_from(seed, rng)

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		resolved_opt = [self._resolve_pitch_lenient(p) if isinstance(p, str) else p for p in pitches]
		resolved = [r for r in resolved_opt if r is not None]

		if not resolved:
			# Every name was a voice this device lacks (each warned once).
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		values = subsequence.sequence_utils.recaman(
			count if count is not None else self._default_grid,
			start=start,
			skip=skip,
		)

		if not values:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		# Always rebase on the window's own lowest value.  Later windows sit high up the
		# sequence, and without this a slide of skip= would jump the register instead of
		# moving smoothly along.  At skip=0, start=0 the offset is zero and nothing moves.
		floor = min(values)
		values = [value - floor for value in values]

		degrees = [value % len(resolved) for value in values]
		octaves = [value // len(resolved) for value in values]

		# Turn the line around at the top of its range rather than pinning it there —
		# clamping would flatten the wedge into a held note, which is the whole point.
		if octave_span > 0:
			octaves = subsequence.sequence_utils.fold(octaves, 0, octave_span, mode="reflect")
		else:
			octaves = [0] * len(octaves)

		auto_step, n_steps = self._fit_spacing("recaman", len(values), spacing)

		beat = 0.0

		for index in range(min(n_steps, len(values))):

			if mapping is not None:
				result = mapping(values[index], index)
				if result is not None:
					m_pitch, m_velocity, m_duration = result
					self.note(pitch=m_pitch, beat=beat, velocity=m_velocity, duration=m_duration)
			else:
				vel = self._resolve_velocity(velocity, rng)
				self.note(
					pitch=resolved[degrees[index]] + 12 * octaves[index],
					beat=beat,
					velocity=vel,
					duration=duration,
				)

			beat += auto_step

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def fibonacci (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		modulus: typing.Optional[int] = None,
		count: typing.Optional[int] = None,
		spacing: typing.Optional[subsequence.declarations.GridBeats] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		a: int = 1,
		b: int = 1,
		mapping: typing.Optional[
			typing.Callable[
				[int, int],
				typing.Optional[typing.Tuple[typing.Union[int, str], int, float]],
			]
		] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Play the Fibonacci sequence as a repeating melodic cycle.

		Each number is the sum of the previous two, folded into your pitch pool.  The
		musical trick is that folding makes the sequence *repeat*, and the length it
		repeats after is decided by the size of the pool - so the number of notes you
		hand it chooses the phrase length: a triad gives 8 steps, a pentatonic 20, a
		seven-note scale 16, an octatonic 12, the full chromatic 24.  Called bare, it
		plays exactly one complete cycle, so the phrase closes on itself.

		Unlike :meth:`recaman`, which wanders off and never comes back, this always
		returns home - pair them when you want one voice looping against one that
		doesn't.  For golden-ratio *timing* (which has no Fibonacci numbers in it at
		all), see :meth:`golden`.

		Parameters:
			pitches: Pitch pool.  Values index into it, so its size sets the cycle
				length.  Ordered low-to-high it reads as a scale.
			modulus: Fold values into ``[0, modulus)``.  Defaults to the pool size,
				which is almost always what you want; set it larger than the pool to
				make the line wrap through the pool more than once per cycle.
			count: How many notes to place.  Omit for one complete cycle.
			spacing: Beats between notes.  Omit to spread the whole cycle across the
				bar, however long it is.  Setting a spacing fixes the note length
				instead, so a cycle longer than the bar is cut off where the bar ends -
				a 20-step cycle at ``spacing=0.25`` gets its first 16 notes.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.
			a: The first number.  Defaults to 1.
			b: The second number.  Defaults to 1.  ``(2, 1)`` gives the Lucas numbers,
				a different cycle through the same pool.  Note many pairs are that same
				cycle started elsewhere - ``(1, 3)`` is Lucas one step along.
			mapping: ``f(value, index)`` returning ``(pitch, velocity, duration)`` to
				place, or None for a rest - full control over how numbers become notes.
			seed: Fix the velocity draws for this call (an int) - the pitches and
				timing are deterministic; omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Raises:
			ValueError: If ``pitches`` is empty, or ``spacing`` is not positive.

		Example:
			```python
			# One full 16-step cycle over a minor scale, spread across the bar.
			p.fibonacci(subsequence.intervals.scale_notes("C", "minor", low=60, high=71))

			# The Lucas variant, as steady eighth notes.
			p.fibonacci([60, 62, 63, 65, 67], a=2, b=1, spacing=0.5)
			```
		"""

		rng = self._rng_from(seed, rng)

		# Guard the pool before it is used as the modulus, so an empty list reports
		# the musical problem rather than a ZeroDivisionError from deep inside.
		if not pitches:
			raise ValueError("pitches list cannot be empty")

		if modulus is None:
			modulus = len(pitches)

		sequence = subsequence.sequence_utils.fibonacci(count=count, a=a, b=b, modulus=modulus)

		if not sequence:
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		auto_step, n_steps = self._fit_spacing("fibonacci", len(sequence), spacing)
		symbols = sequence[:n_steps]

		beat = 0.0

		for index, value in enumerate(symbols):

			if mapping is not None:
				result = mapping(value, index)
				if result is not None:
					m_pitch, m_velocity, m_duration = result
					self.note(pitch=m_pitch, beat=beat, velocity=m_velocity, duration=m_duration)
			else:
				vel = self._resolve_velocity(velocity, rng)
				self.note(pitch=pitches[value % len(pitches)], beat=beat, velocity=vel, duration=duration)

			beat += auto_step

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def lorenz (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		spacing: subsequence.declarations.GridBeats = 0.25,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		dt: typing.Annotated[float, subsequence.declarations.Span(0.001, 0.5)] = 0.1,
		sigma: float = 10.0,
		rho: float = 28.0,
		beta: float = 8.0 / 3.0,
		x0: float = 0.1,
		y0: float = 0.0,
		z0: float = 0.0,
		mapping: typing.Optional[
			typing.Callable[
				[float, float, float],
				typing.Optional[typing.Tuple[typing.Union[int, str], int, float]],
			]
		] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a note sequence driven by the Lorenz strange attractor.

		Integrates the Lorenz system and walks one trajectory of (x, y, z)
		points, carried on from bar to bar: each bar plays the stretch after the
		last one's, so the line keeps moving instead of replaying one bar.  The
		three axes provide correlated but independent modulation sources: by
		default x drives pitch selection, y drives velocity, and z drives
		duration.

		Each axis is measured against the range the trajectory covers over its
		first sixty time units, the same for every bar, so a stretch that
		circles one wing of the butterfly stays on a few pitches and a swing to
		the other wing sweeps across the pool.  At the default ``dt`` about half the
		notes repeat the one before and most of the rest move to a neighbouring
		pitch; a bar spans a median of five steps of an eight-note pool.  A
		smaller ``dt`` lingers - at 0.05, 70% of notes repeat - and a larger one
		moves faster and leaps more.

		The system is extremely sensitive to where it starts: two lines whose
		``x0`` differ by a millionth part company by the second bar, so ``x0``
		picks a different line.  Turn ``rho`` down to calm it: at about 15 or
		below, the line spirals in and comes to rest on one pitch within 30
		bars at the default ``dt``.

		A custom ``mapping`` callable can override the default x/y/z → pitch/vel/dur
		assignment, or return ``None`` for a rest.

		Parameters:
			pitches: Pitch pool.  The x-axis selects an index, low to high: ``min(int(x * len(pitches)), len(pitches) - 1)``.
			spacing: Time between notes in beats.  Default 0.25 (16th note).
			velocity: Fixed velocity or ``(low, high)`` tuple.  Overridden by ``mapping``.
			duration: Maximum note duration.  z is scaled to ``[0.05, duration]``.
			    Overridden by ``mapping``.
			dt: Time along the trajectory between one note and the next, 0.001 to 0.5.
			    Longer steps move further round the attractor per note; any length is
			    integrated in steps of at most 0.01, so it never runs off.  Default 0.1.
			sigma, rho, beta: Lorenz parameters.  Defaults produce the classic
			    butterfly attractor (chaotic regime).
			x0, y0, z0: Where the trajectory starts.  A different start plays a
			    different line.
			mapping: Optional callable ``(x, y, z) -> (pitch, velocity, duration)``
			    or ``None`` for rest.

		Example:
			```python
			scale = [60, 62, 64, 65, 67, 69, 71, 72]
			p.lorenz(scale, spacing=0.25, velocity=(50, 110))
			```
		"""

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		if spacing <= 0:
			raise ValueError(f"lorenz() spacing is the time between notes in beats - it must be positive, got {spacing}")

		# One trajectory, carried on bar by bar: this cycle plays the stretch after
		# the last one's (#3472).
		n_steps = int(self._pattern.length / spacing)
		points = subsequence.sequence_utils.lorenz_attractor(
			n_steps, dt=dt, sigma=sigma, rho=rho, beta=beta, x0=x0, y0=y0, z0=z0, start=self.cycle * n_steps
		)

		beat = 0.0

		for x, y, z in points:

			if mapping is not None:
				result = mapping(x, y, z)
				if result is not None:
					p_pitch, p_vel, p_dur = result
					self.note(pitch=p_pitch, beat=beat, velocity=p_vel, duration=p_dur)
			else:
				# The trajectory's highest point is x = 1.0 exactly, and a modulo sent
				# it round to the lowest pitch (M17); it plays the highest instead.
				pitch_idx = min(int(x * len(pitches)), len(pitches) - 1)
				p_pitch = pitches[pitch_idx]
				if isinstance(velocity, (tuple, list)):
					p_vel = int(velocity[0] + y * (velocity[1] - velocity[0]))
				else:
					# A fixed int means FIXED - the y axis only drives velocity
					# when a (low, high) range invites it (or via mapping=).
					p_vel = int(velocity)
				p_dur = 0.05 + z * max(0.0, duration - 0.05)
				self.note(pitch=p_pitch, beat=beat, velocity=p_vel, duration=p_dur)

			beat += spacing
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def reaction_diffusion (
		self,
		pitch: subsequence.declarations.Pitch,
		threshold: subsequence.declarations.UnitInterval = 0.5,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.1,
		feed_rate: typing.Annotated[float, subsequence.declarations.Span(0.0, 0.2)] = 0.08,
		kill_rate: typing.Annotated[float, subsequence.declarations.Span(0.0, 0.07)] = 0.061,
		steps: typing.Annotated[int, subsequence.declarations.Span(1, 20000)] = 1000,
		no_overlap: bool = False,
		probability: subsequence.declarations.UnitInterval = 1.0,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a rhythm from a 1D Gray-Scott reaction-diffusion simulation.

		Simulates the Gray-Scott model on a ring of ``_default_grid`` cells,
		then thresholds the final V-concentration to produce a binary hit
		pattern.  Cells where concentration exceeds ``threshold`` become note
		events.

		Unlike cellular automata - where rules are discrete and the state is
		binary - reaction-diffusion evolves a continuous concentration field
		governed by diffusion rates and chemical reactions.  On a ring the size
		of a bar it settles into spots - runs of hits - and a ``(low, high)``
		velocity follows the chemical along each one: a short run swells to its
		middle, and a long one is loudest just inside each end.

		Only a narrow band of ``feed_rate`` and ``kill_rate`` forms a pattern.
		Too much kill for the feed and the chemical dies out; too little and it
		evens out around the whole bar.  Either way there is no pattern, so the
		call plays nothing, and the log says which happened, once per setting.
		Raising ``steps`` does not help: a setting with no pattern at 1000
		steps has none at 20000.

		The default rates form a pattern on any grid of 8 steps or more: a run
		of 4 on 8 steps, a run of 6 on 12 or 16, and two runs of 5 on 24 or 32.
		On 16 steps at the default kill, ``feed_rate`` sets how long the run
		is: 0.058 plays 12 steps, 0.066 plays 10, 0.072 plays 8, 0.08 plays 6
		and 0.088 plays 4, and below about 0.048 or above about 0.094 it dies
		out.  More kill shortens the runs too, over a narrower range; from
		about 0.065 every setting dies out.

		Parameters:
			pitch: MIDI note number or drum name.
			threshold: V-concentration threshold for note placement (0.0–1.0).
			    Lower values produce denser patterns.
			velocity: MIDI velocity.  An ``(low, high)`` tuple is NOT random:
			    each step's local V-concentration is mapped into the range
			    deterministically, so notes are louder where the chemical is
			    stronger and softest at the edges of each run.
			duration: Note duration in beats.
			feed_rate: How fast the chemical the pattern lives on is
			    replenished, 0 to 0.2.  Default 0.08.
			kill_rate: How fast the pattern's own chemical is removed, 0 to
			    0.07.  Default 0.061.
			steps: Number of simulation iterations.  More = more developed
			    pattern.  Default 1000, and bounded at 20000 - the cost is
			    linear (about 3 ms per thousand) and a rebuild that overruns
			    delays the whole pattern.  The pattern settles by about 2000
			    in any case; beyond that it drifts rather than develops.
			no_overlap: Skip steps where ``pitch`` is already sounding.
			probability: Chance (0.0–1.0) that each active step plays - 1.0 places them all, lower thins.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Six closed-hat sixteenths across the middle of the bar,
			# swelling to their centre
			p.reaction_diffusion("hi_hat_closed", velocity=(50, 110))

			# Ten, loudest just inside each end
			p.reaction_diffusion("hi_hat_closed", feed_rate=0.066, velocity=(50, 110))
			```
		"""
		rng = self._rng_from(seed, rng)

		concentrations, lost = subsequence.sequence_utils._reaction_diffusion_reporting(
			width = self._default_grid,
			steps = steps,
			feed_rate = feed_rate,
			kill_rate = kill_rate,
		)

		# Nothing clears the threshold in the zeros that come back with a
		# reason, so saying why is all that is left to do.
		if lost is not None and (self._default_grid, steps, feed_rate, kill_rate) not in _warned_no_pattern:
			_warned_no_pattern.add((self._default_grid, steps, feed_rate, kill_rate))
			logger.warning(
				f"reaction_diffusion(feed_rate={feed_rate:g}, kill_rate={kill_rate:g}) on {self._default_grid} steps: "
				f"the chemical {lost}, with {_NO_PATTERN_CAUSE[lost]}, so there is no pattern to play. "
				"The default rates form one on any grid of 8 steps or more."
			)

		sequence = [1 if c > threshold else 0 for c in concentrations]

		if isinstance(velocity, (tuple, list)):
			# Map concentration to velocity range for active steps: louder
			# where the pattern is denser (deterministic, not random).
			midi_vel_lo, midi_vel_hi = velocity

			def _event (i: int, hit: typing.Any) -> typing.Optional[typing.Tuple[typing.Union[int, str], subsequence.declarations.VelocityValue, float]]:
				if hit == 0:
					return None

				vel = int(midi_vel_lo + concentrations[i] * (midi_vel_hi - midi_vel_lo))
				return (pitch, vel, duration)

			self._place_gated_sequence(sequence, _event, probability, rng, no_overlap=no_overlap)
		else:
			self._place_rhythm_sequence(sequence, pitch, int(velocity), duration, probability, rng, no_overlap)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def _walk_resumes (
		self,
		state: typing.Optional[typing.Tuple[typing.Tuple[typing.Any, ...], typing.Tuple[int, ...]]],
		pool: typing.Tuple[typing.Any, ...],
	) -> typing.Optional[typing.Tuple[int, typing.List[int]]]:

		"""Where a walk over *pool* goes on from and what it heard there, or None to start in the middle.

		The same list goes on from the index it ended on, remembering the
		indices it heard.  A changed list goes on from its note nearest the one
		the walk ended on, the lower of two as near, and remembers only the
		notes it heard that the new list holds (#3500).  A list with a note that
		does not read as a pitch starts again in the middle.
		"""

		if state is None:
			return None

		walked, heard = state

		if walked == pool:
			return heard[-1], list(heard)

		old = [self._resolve_pitch_lenient(pitch) for pitch in walked]
		known = [pitch for pitch in (self._resolve_pitch_lenient(pitch) for pitch in pool) if pitch is not None]
		last = old[heard[-1]]

		if last is None or len(known) != len(pool):
			return None

		ended: int = last
		start = min(range(len(known)), key = lambda index: (abs(known[index] - ended), known[index]))
		remembered = [known.index(pitch) for pitch in (old[index] for index in heard) if pitch in known]

		return start, remembered

	def self_avoiding_walk (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		spacing: subsequence.declarations.GridBeats = 0.25,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a melody using a self-avoiding random walk.

		The walk moves through ``pitches`` in order, mostly a step at a time and
		now and then skipping one, and it remembers about the last half of the
		list: it goes only where it has not been lately, so a pitch never comes
		back sooner than three notes later, and the line keeps moving instead of
		trilling between two notes.  Where every neighbour was heard lately, as
		at the ends of a short list, it goes to the one heard longest ago.

		So the line stays step-wise and keeps finding new notes.  Over 500
		seeds, a bar of sixteenths on the eight notes of C major from 60 to 72
		gave 188 different melodies, with about a quarter of the moves skipping
		a note.  Two pitches can only alternate.

		It is one line, not a bar at a time.  The first bar starts on the middle
		of the list (65 in that scale), and each bar after it goes on from where
		the last one ended, still keeping clear of what it heard there.  If the
		list changes from one bar to the next, as it does when it follows the
		chord, the walk goes on from the note in the new list nearest the one
		it ended on.

		Parameters:
			pitches: Ordered list of MIDI note numbers or note strings.  The walk
			    moves through indices ``[0, len(pitches) - 1]``, mapping each to
			    the corresponding pitch.
			spacing: Time between notes in beats.  Default 0.25 (16th note).
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.
			seed: Fix the walk's choices (an int), so it plays the same on every
			    run; omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			scale = subsequence.scale_notes("C", "ionian", low=60, high=72)
			p.self_avoiding_walk(scale, spacing=0.25, velocity=(60, 100))
			```
		"""

		rng = self._rng_from(seed, rng)

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		if spacing <= 0:
			raise ValueError(f"self_avoiding_walk() spacing is the time between notes in beats - it must be positive, got {spacing}")

		n_steps = int(self._pattern.length / spacing)
		call = self._self_avoiding_walk_calls
		self._self_avoiding_walk_calls += 1
		pool = tuple(pitches)
		left_off = self._walk_resumes(self._pattern._walk_states.get(call), pool)

		if left_off is None:
			indices = subsequence.sequence_utils.self_avoiding_walk(n = n_steps, low = 0, high = len(pool) - 1, rng = rng)
			heard: typing.List[int] = indices
		else:
			# One step more than the bar holds, from where the last bar ended, and
			# that note itself dropped: it was the last bar's to play (#3500).
			start, remembered = left_off
			indices = subsequence.sequence_utils.self_avoiding_walk(
				n = n_steps + 1, low = 0, high = len(pool) - 1, rng = rng, start = start, heard = remembered,
			)[1:]
			heard = list(remembered) + indices

		if indices:
			self._pattern._walk_states[call] = (pool, tuple(heard[-len(pool):]))

		beat = 0.0

		for idx in indices:
			vel = self._resolve_velocity(velocity, rng)
			self.note(pitch=pitches[idx], beat=beat, velocity=vel, duration=duration)
			beat += spacing
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@staticmethod
	def _thin_priorities (grid: int, strategy: str, beats: float) -> typing.List[float]:

		"""thin()'s own table: 1 where a strategy removes a position, 0 where it keeps it (#3462).

		Positions are named as ``build_ghost_bias()`` names them - the beat, the
		& midway through it, the step just before or just after it - so the two
		vocabularies stay one.  Only ``"offbeat"`` weighs anything between: it
		thins the e and a lightly, which is what sets it apart from ``"upbeat"``.
		"""

		steps_per_beat = PatternAlgorithmicMixin._steps_per_beat(grid, beats)
		priorities: typing.List[float] = []

		for index in range(grid):

			position = index % steps_per_beat
			on_the_beat = position == 0
			on_the_and = steps_per_beat > 1 and position == steps_per_beat // 2

			if strategy == "uniform":
				priority = 1.0
			elif strategy == "sixteenths":
				priority = 0.0 if on_the_beat or on_the_and else 1.0
			elif strategy == "offbeat":
				priority = 0.0 if on_the_beat else 1.0 if on_the_and else _OFFBEAT_THINS_THE_SIXTEENTHS
			elif strategy == "e_and_a":
				priority = 0.0 if on_the_beat else 1.0
			elif strategy == "upbeat":
				priority = 1.0 if on_the_and else 0.0
			elif strategy == "downbeat":
				priority = 1.0 if on_the_beat else 0.0
			elif strategy == "before":
				priority = 1.0 if not on_the_beat and position == steps_per_beat - 1 else 0.0
			elif strategy == "after":
				priority = 1.0 if steps_per_beat > 1 and position == 1 else 0.0
			else:
				raise ValueError(
					f"Unknown thin() strategy {strategy!r}. Use 'strength', 'uniform', 'offbeat', "
					f"'sixteenths', 'before', 'after', 'downbeat', 'upbeat', 'e_and_a', or a list of floats."
				)

			priorities.append(priority)

		return priorities

	def _placed_zone (self, position: int, note: subsequence.pattern.Note, step_pulses: float, grid: int) -> int:

		"""The grid step *note* was placed on, as ``thin()`` and ``ratchet(steps=)`` count it.

		Step N owns the pulses from ``N * step_pulses`` up to the next step's,
		and a note is read where it was placed, not where swing, a groove or
		``randomize()`` has since moved it (#3447).  A note placed past the
		last step counts as the last.
		"""

		return min(int(self._pattern._placed_pulse(position, note) / step_pulses), grid - 1)

	@subsequence.declarations.bounded
	def thin (
		self,
		pitch: typing.Optional[subsequence.declarations.Pitch] = None,
		strategy: typing.Union[subsequence.declarations.ThinStrategy, typing.List[float]] = "strength",
		amount: subsequence.declarations.UnitInterval = 0.5,
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Remove notes from the pattern based on their rhythmic position.

		This is the musical inverse of :meth:`ghost_fill()`.  Where ``ghost_fill``
		uses bias weights to decide where to *add* ghost notes, ``thin`` uses the
		same position vocabulary to decide where to *remove* notes.

		The strategy names match those in :meth:`build_ghost_bias()` and carry the
		same rhythmic meaning, taken at its word: a position a strategy keeps is
		never touched, whatever the ``amount``, and a position it removes goes
		with probability ``amount``.

		- ``"sixteenths"`` - removes 16th-note subdivisions (e/a), keeps beats and &.
		- ``"offbeat"``    - removes the & position, straightens the groove, and
		  thins the e/a lightly, which sets it apart from ``"upbeat"``.
		- ``"e_and_a"``    - removes all non-downbeat positions, keeps only beats.
		- ``"downbeat"``   - removes beat positions (floating/displaced effect).
		- ``"upbeat"``     - removes only the & position.
		- ``"before"``     - removes only the step just before each beat.
		- ``"after"``      - removes only the step just after each beat.
		- ``"uniform"``    - removes from all positions equally (per-instrument dropout).
		- ``"strength"``   - progressive thinning: weakest positions (e/a) drop first,
		  strongest (downbeat) last. Useful for Perlin-driven density control.

		When ``pitch`` is given, only notes of that instrument are affected -
		useful for drum layers.  When ``pitch`` is ``None`` (the default), all
		notes regardless of pitch are candidates.  This makes ``thin`` a
		rhythm-aware generalisation of :meth:`dropout()`, and is ideal for
		tonal patterns such as arpeggios where each step carries a different pitch.

		Position classification is **zone-based**: each grid step owns the pulse range
		``[N * step_pulses, (N + 1) * step_pulses)``, and a note counts in the step
		it was placed on, however far ``swing()``, ``groove()`` or ``randomize()``
		has since moved it, early or late.  So ``thin`` can come before the feel
		or after it.

		Parameters:
			pitch: Drum name or MIDI note number to target, or ``None`` to thin
				all notes regardless of pitch. Defaults to ``None``.
			strategy: Named strategy string or a list of per-step drop-priority
				floats (0.0 = never drop, 1.0 = highest drop priority). Must have
				length equal to ``grid`` when a list is provided.
			amount: Overall thinning depth (0.0 = remove nothing, 1.0 = remove all
				qualifying). Effective drop probability = ``priority * amount``.
				Drive this with a Perlin field or section progress for smooth,
				organic thinning over time.
			grid: Step grid size. Defaults to the pattern's ``default_grid``.
			seed: Fix the thinning for this call (an int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example::

			# Thin 16th ghost notes from the kick, keep anchors and off-beats
			p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
			p.ghost_fill("kick_1", density=0.3, velocity=(25, 40), bias="sixteenths")
			p.thin("kick_1", "sixteenths", amount=0.8)

			# Perlin-driven progressive thinning of hi-hats
			sparseness = perlin_1d(p.cycle * 0.07, seed=42)
			p.thin("hi_hat_closed", "strength", amount=sparseness)

			# Thin an arpeggio (all pitches) - no pitch loop needed
			p.thin(strategy="strength", amount=sparseness)
		"""

		rng = self._rng_from(seed, rng)

		if grid is None:
			grid = self._default_grid

		if pitch is None:
			midi_pitch = None
		else:
			midi_pitch = self._resolve_pitch_lenient(pitch)
			if midi_pitch is None:
				# Named voice this device lacks (already warned once): there are
				# no such notes to thin, so this is a no-op rather than an error.
				return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		# Build the per-step drop-priority weights.
		#
		# Strategy names are shared with ghost_fill's bias vocabulary, but the
		# weights are thin's own (#3462): ghost_fill's floor of 0.05 on the beat
		# and 0.3 on the & suit placing a ghost note, and made thin drop what its
		# strategy said it kept.
		#
		# "strength" is defined only for thin() - it expresses a thinning hierarchy
		# (weakest positions drop first) which has no meaningful ghost_fill equivalent.
		if strategy == "strength":
			# Per-beat drop priorities: e/a (1.0) > & (0.6) > downbeat (0.05).
			# As `amount` rises, progressively weaker positions are removed first.
			steps_per_beat = self._steps_per_beat(grid, self._pattern.length)
			priorities: typing.List[float] = []
			for i in range(grid):
				pos = i % steps_per_beat
				if pos == 0:
					priorities.append(0.05)
				elif steps_per_beat > 1 and pos == steps_per_beat // 2:
					priorities.append(0.6)
				else:
					priorities.append(1.0)
		elif isinstance(strategy, list):
			if len(strategy) != grid:
				raise ValueError(
					f"thin() custom strategy list has {len(strategy)} values "
					f"but grid has {grid} steps."
				)
			priorities = list(strategy)
		else:
			priorities = self._thin_priorities(grid, strategy, self._pattern.length)

		# Zone-based classification: zone N owns pulses in
		# [ N * step_pulses, (N+1) * step_pulses ), and each note counts in the
		# zone it was placed in, however far the feel has moved it (#3447).
		total_pulses = self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE
		step_pulses = total_pulses / grid

		pulses_to_remove: typing.List[int] = []

		for pulse, step in list(self._pattern.steps.items()):

			# Separate target notes from protected notes at this pulse.
			if midi_pitch is None:
				remaining = []
				targets   = list(step.notes)
			else:
				remaining = [n for n in step.notes if n.pitch != midi_pitch]
				targets   = [n for n in step.notes if n.pitch == midi_pitch]

			# Per note, since two notes sharing a pulse may have been placed
			# on different steps: an early hat beside an unmoved kick.
			note_priorities = [priorities[self._placed_zone(pulse, note, step_pulses, grid)] for note in targets]

			if all(priority <= 0.0 for priority in note_priorities):
				continue

			for note, priority in zip(targets, note_priorities):
				if priority <= 0.0 or rng.random() >= priority * amount:
					remaining.append(note)
				# else: note is dropped

			if not remaining:
				pulses_to_remove.append(pulse)
			else:
				step.notes = remaining

		for pulse in pulses_to_remove:
			del self._pattern.steps[pulse]
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def ratchet (
		self,
		subdivisions: int = 2,
		pitch: typing.Optional[subsequence.declarations.Pitch] = None,
		probability: subsequence.declarations.UnitInterval = 1.0,
		velocity_start: subsequence.declarations.VelocityScale = 1.0,
		velocity_end: subsequence.declarations.VelocityScale = 1.0,
		shape: typing.Union[subsequence.declarations.EasingCurve, typing.Callable[[float], float]] = "linear",
		gate: subsequence.declarations.UnitInterval = 0.5,
		steps: typing.Optional[typing.List[subsequence.declarations.StepPosition]] = None,
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Subdivide existing notes into rapid repeated hits (rolls/ratchets).

		A post-placement transform: takes notes already in the pattern and
		replaces each one with ``subdivisions`` evenly-spaced sub-hits within
		the original note's duration window.  The velocity of each sub-hit is
		interpolated from ``velocity_start`` to ``velocity_end`` (as multipliers
		on the original velocity) using the ``shape`` easing curve, so crescendo
		rolls, decrescendo buzzes, and flat repeats are all one parameter apart.

		Call ``ratchet()`` after note-placement methods (``euclidean``,
		``hit_steps``, ``arpeggio``, etc.) and after ``swing`` or ``groove``,
		so that each roll moves with its note.  A groove moves only the notes
		that sit near a grid line, so a roll made before it has only its first
		sub-hit moved: the roll is squeezed, and with enough swing its sub-hits
		land on one pulse or play in the wrong order.

		Parameters:
			subdivisions: Number of sub-hits replacing each note (default 2).
				If the note's duration is shorter than ``subdivisions`` pulses,
				subdivisions are clamped to ``note.duration`` so they never
				stack on the same pulse.
			pitch: Only ratchet notes matching this pitch (MIDI number or drum
				name).  ``None`` (default) ratchets all notes regardless of
				pitch - useful for melodic patterns such as arpeggios.
			probability: Chance (0.0–1.0) that each note gets ratcheted.  Notes
				that fail the check are left completely unchanged.  Default 1.0
				(every note is ratcheted).
			velocity_start: Velocity multiplier for the first sub-hit (0.0–2.0).
				Default 1.0 (same as the original).
			velocity_end: Velocity multiplier for the last sub-hit (0.0–2.0).
				Default 1.0.  Set ``velocity_start=0.3, velocity_end=1.0`` for
				a crescendo roll; ``1.0, 0.2`` for a decrescendo buzz.
			shape: Easing curve applied to the velocity interpolation across
				sub-hits.  Accepts any name from ``subsequence.easing`` (e.g.
				``"ease_in"``, ``"ease_out"``, ``"s_curve"``) or a custom
				callable ``f(t) → t`` for t ∈ [0, 1].  Default ``"linear"``.
			gate: Sub-note duration as a fraction of each subdivision slot
				(0.0–1.0).  ``1.0`` = legato (sub-hits touch), ``0.5`` =
				staccato (half the slot).  Default 0.5.
			steps: Grid positions to ratchet (e.g. ``[0, 4, 12]``).  Each note
				counts as the step it was placed on, the same way ``thin()``
				counts it, however far swing, a groove or ``randomize()`` has
				moved it.  ``None`` (default) applies ratchet to all eligible
				notes.
			grid: Grid resolution used for ``steps`` zone classification.
				Defaults to the pattern's ``default_grid``.
			seed: Fix the probability gating for this call (an int); omit to
				use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Examples:
			```python
			# Subdivide every hi-hat into a triplet roll
			p.euclidean("hi_hat_closed", 8).ratchet(3, pitch="hi_hat_closed")

			# Crescendo roll into a snare
			p.hit_steps("snare", [12]).ratchet(4, velocity_start=0.3,
			                                      velocity_end=1.0,
			                                      shape="ease_in")

			# Probabilistic 2× ratchet on hi-hats only
			p.euclidean("hi_hat_closed", 12).ratchet(2, pitch="hi_hat_closed",
			                                            probability=0.4, gate=0.3)

			# Ratchet only steps 0 and 8 (downbeats)
			p.euclidean("kick_1", 6).ratchet(2, pitch="kick_1", steps=[0, 8])
			```
		"""

		rng = self._rng_from(seed, rng)

		if grid is None:
			grid = self._default_grid

		if pitch is None:
			midi_pitch = None
		else:
			midi_pitch = self._resolve_pitch_lenient(pitch)
			if midi_pitch is None:
				# Named voice this device lacks (already warned once): nothing
				# matches, so leave the pattern unchanged rather than raising.
				return typing.cast("subsequence.pattern_builder.PatternBuilder", self)
		ease_fn = subsequence.easing.get_easing(shape)

		# Build zone set for steps mask (zone-based, matching thin()'s approach).
		target_zones: typing.Optional[typing.Set[int]] = None
		if steps is not None:
			target_zones = set(steps)

		total_pulses = self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE
		step_pulses = total_pulses / grid

		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for pulse, step in self._pattern.steps.items():

			# Separate targeted notes from passthrough notes.  The steps mask
			# reads each note by the step it was placed on, as thin() does, so
			# an early or swung note is ratcheted as its own step's (#3447).
			targets: typing.List[subsequence.pattern.Note] = []
			passthrough: typing.List[subsequence.pattern.Note] = []

			for note in step.notes:
				if midi_pitch is not None and note.pitch != midi_pitch:
					passthrough.append(note)
				elif target_zones is not None and self._placed_zone(pulse, note, step_pulses, grid) not in target_zones:
					passthrough.append(note)
				else:
					targets.append(note)

			# Passthrough notes keep their original pulse position.
			if passthrough:
				if pulse not in new_steps:
					new_steps[pulse] = subsequence.pattern.Step()
				new_steps[pulse].notes.extend(passthrough)

			for note in targets:

				# Probability gate — failed notes are kept unchanged.
				if probability < 1.0 and rng.random() < (1.0 - probability):
					if pulse not in new_steps:
						new_steps[pulse] = subsequence.pattern.Step()
					new_steps[pulse].notes.append(note)
					continue

				# Clamp subdivisions so sub-hits never stack on the same pulse.
				effective_subdivs = min(subdivisions, note.duration)
				if effective_subdivs < 1:
					effective_subdivs = 1

				slot_pulses = note.duration / effective_subdivs

				for i in range(effective_subdivs):
					sub_pulse = pulse + int(round(i * slot_pulses))

					# Velocity interpolation via easing.
					if effective_subdivs == 1:
						t = 0.0
					else:
						t = i / (effective_subdivs - 1)
					eased_t = ease_fn(t)
					vel_mul = velocity_start + (velocity_end - velocity_start) * eased_t
					sub_velocity = max(1, min(127, int(round(note.velocity * vel_mul))))

					sub_duration = max(1, int(round(slot_pulses * gate)))

					# A copy of the note, so each sub-hit keeps its drum name
					# and primary_unmapped: a mirror re-resolves the name
					# through its own kit, and the primary stays silent for a
					# voice it lacks.  Built field by field, a mirror played
					# the primary's number and the primary sounded a
					# placeholder (#3448).
					sub_note = dataclasses.replace(note, velocity=sub_velocity, duration=sub_duration)

					if sub_pulse not in new_steps:
						new_steps[sub_pulse] = subsequence.pattern.Step()
					new_steps[sub_pulse].notes.append(sub_note)

		self._pattern.steps = new_steps
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def evolve (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		length: typing.Optional[int] = None,
		drift: subsequence.declarations.UnitInterval = 0.0,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		spacing: subsequence.declarations.GridBeats = 0.25,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Loop a pitch sequence that gradually mutates each cycle.

		On cycle 0, the sequence is locked to the initial ``pitches`` (truncated to
		``length`` if provided).  Each subsequent cycle, every step has a ``drift``
		probability of being replaced by a randomly-chosen value from the pool.
		When ``drift=0.0`` the loop never changes; when ``drift=1.0`` every step
		is redrawn every cycle.

		State is stored in ``p.data`` under a key derived from the pitch content, so the
		buffer persists across pattern rebuilds.  The buffer is reset whenever
		``cycle == 0`` so restarts produce deterministic output.

		Combine with ``p.snap_to_scale()`` to keep drifted pitches in key:

		```python
		p.evolve([60, 64, 67, 72], length=8, drift=0.12)
		p.snap_to_scale("C", "minor")
		```

		Parameters:
			pitches: Initial pitch pool.  The initial buffer is built from the first
			    ``length`` values (cycling if shorter than ``length``).  Mutation
			    also draws replacements from this pool.
			length: Number of steps in the loop.  Defaults to ``len(pitches)``.
			drift: Per-step mutation probability each cycle (0.0–1.0).
			    ``0.0`` = locked loop, ``1.0`` = fully random each cycle.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per step.
			duration: Note duration in beats.
			spacing: Beat interval between steps.
			seed: Fix the drift mutations and velocity draws for this call (an
			    int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# 8-step loop that slowly diverges from its seed
			p.evolve([60, 62, 64, 65, 67, 69], length=8, drift=0.1,
			         velocity=(70, 100), spacing=0.5)
			p.snap_to_scale("C", "dorian")
			```
		"""

		rng = self._rng_from(seed, rng)

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		resolved_opt = [self._resolve_pitch_lenient(p) if isinstance(p, str) else p for p in pitches]
		resolved = [r for r in resolved_opt if r is not None]
		if not resolved:
			# Every seed name was a voice this device lacks (each warned once).
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)
		n = length if length is not None else len(resolved)

		# Stable key derived from the seed *content* (not object identity).  The
		# documented idiom passes a fresh list literal every cycle; keying on
		# ``id(pitches)`` gave that literal a new address each cycle, so the
		# buffer re-seeded every cycle (drift never accumulated) and a dict key
		# leaked per cycle.  Content keying makes the buffer persist so the walk
		# actually evolves, and scoping by the owning pattern's builder name keeps
		# two patterns' identical seeds from sharing one walk.  ``resolved`` (the
		# post-lenient ints) and ``n`` are folded in so a changed step count or a
		# seed whose unknown names were dropped still keys stably.
		builder_fn = getattr(self._pattern, '_builder_fn', None)
		scope = getattr(builder_fn, '__name__', '') if builder_fn is not None else ''
		data_key = f"_evolve_{scope}_{n}_{tuple(resolved)}"

		# Initialise or reset the buffer on cycle 0.
		if data_key not in self.data or self.cycle == 0:
			self.data[data_key] = [resolved[i % len(resolved)] for i in range(n)]

		buffer = self.data[data_key]

		# Mutate the buffer in place for this cycle (skipped on cycle 0 — seed plays first).
		if self.cycle > 0 and drift > 0.0:
			for i in range(n):
				if rng.random() < drift:
					buffer[i] = rng.choice(resolved)

		# Place notes.
		for i, pitch in enumerate(buffer):
			vel = self._resolve_velocity(velocity, rng)
			self.note(pitch=pitch, beat=i * spacing, velocity=vel, duration=duration)

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	@subsequence.declarations.bounded
	def branch (
		self,
		pitches: typing.Sequence[subsequence.declarations.Pitch],
		depth: int = 2,
		path: int = 0,
		mutation: subsequence.declarations.UnitInterval = 0.0,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_GENERATIVE_VELOCITY,
		duration: subsequence.declarations.GateBeats = 0.2,
		spacing: subsequence.declarations.GridBeats = 0.25,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Generate a melodic variation by navigating a fractal tree of transforms.

		The ``pitches`` sequence is the "trunk".  At each branch level, two musical
		transforms are assigned deterministically (derived from the original
		sequence), and the ``path`` index selects left or right at each level.
		After ``depth`` levels the result is a variation that is always
		structurally related to the input ``pitches``.

		Use ``path=p.cycle`` to step through all ``2 ** depth`` variations in
		order; the index wraps automatically.

		**Transforms** (assigned deterministically per level):

		- *Retrograde* - reverse the sequence.
		- *Invert* - mirror each pitch around the first note.
		- *Transpose* - shift all pitches by the interval between the first
		  two notes.
		- *Rotate* - shift the starting position by one step.
		- *Scale intervals* - multiply intervals from the first note by 0.5
		  (compress) or 2.0 (expand), rounded to the nearest semitone.

		An optional ``mutation`` layer randomly substitutes individual notes
		with other input pitches on top of the deterministic branching.

		Parameters:
			pitches: Original pitch sequence.  All variations are derived from this.
			depth: Branching levels.  ``2 ** depth`` unique variations are
			    available before the path wraps.
			path: Which variation to play (0-based).  ``path=p.cycle`` advances
			    automatically.  Values wrap modulo ``2 ** depth``.
			mutation: Probability that any step is replaced by a random input
			    pitch after branching (0.0 = none, 1.0 = fully random).
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per step.
			duration: Note duration in beats.
			spacing: Beat interval between steps.
			seed: Fix the mutation substitutions and velocity draws for this
			    call (an int) - the variation tree itself is deterministic;
			    omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Cycle through 8 variations (depth=3) of a 4-note motif
			p.branch([60, 64, 67, 72], depth=3, path=p.cycle,
			         velocity=85, spacing=0.5)
			p.snap_to_scale("C", "minor")
			```
		"""

		rng = self._rng_from(seed, rng)

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		resolved_opt = [self._resolve_pitch_lenient(p) if isinstance(p, str) else p for p in pitches]
		resolved = [r for r in resolved_opt if r is not None]
		if not resolved:
			# Every seed name was a voice this device lacks (each warned once).
			return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

		# The variation tree itself lives in sequence_utils.branch_sequence —
		# a reusable pure kernel (feed its output to Motif.notes() for a
		# storable variation).  This verb resolves drum names, derives the
		# variation, and places it on the grid.
		sequence = subsequence.sequence_utils.branch_sequence(
			resolved,
			depth = depth,
			path = path,
			mutation = mutation,
			rng = rng,
		)

		# Place notes.
		for i, pitch in enumerate(sequence):
			vel = self._resolve_velocity(velocity, rng)
			self.note(pitch=pitch, beat=i * spacing, velocity=vel, duration=duration)

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)
