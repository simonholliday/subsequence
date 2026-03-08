"""Mixin class providing algorithmic and generative pattern-building methods.

This module is not intended to be used directly. ``PatternAlgorithmicMixin``
is inherited by ``PatternBuilder`` in ``pattern_builder.py``.
"""

import random
import typing

import subsequence.constants
import subsequence.constants.velocity
import subsequence.melodic_state
import subsequence.pattern
import subsequence.sequence_utils
import subsequence.weighted_graph


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
	rng: random.Random
	cycle: int

	if typing.TYPE_CHECKING:
		# Cross-mixin method stubs: implemented by PatternBuilder,
		# called from methods in this mixin.
		def note (
			self,
			pitch: typing.Union[int, str],
			beat: float,
			velocity: int,
			duration: float,
		) -> "PatternAlgorithmicMixin": ...
		def _resolve_pitch (self, pitch: typing.Union[int, str]) -> int: ...

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

	def euclidean (self, pitch: typing.Union[int, str], pulses: int, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, dropout: float = 0.0, no_overlap: bool = False, rng: typing.Optional[random.Random] = None) -> "PatternAlgorithmicMixin":

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
		return self

	def bresenham (self, pitch: typing.Union[int, str], pulses: int, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: float = 0.1, dropout: float = 0.0, no_overlap: bool = False, rng: typing.Optional[random.Random] = None) -> "PatternAlgorithmicMixin":

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
		return self

	def bresenham_poly (
		self,
		parts: typing.Dict[typing.Union[int, str], float],
		velocity: typing.Union[int, typing.Dict[typing.Union[int, str], int]] = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: float = 0.1,
		grid: typing.Optional[int] = None,
		dropout: float = 0.0,
		no_overlap: bool = False,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""
		Distribute multiple drum voices across the pattern using weighted Bresenham.

		Each step is assigned to exactly one voice - voices never overlap, producing
		interlocking rhythmic patterns. Density weights control how frequently each
		voice fires. If the weights sum to less than 1.0, the remainder becomes
		evenly-distributed rests (silent steps).

		Because notes are placed via ``self.note()``, all post-placement transforms
		(``groove``, ``randomize``, ``velocity_shape``, ``shift``, etc.) work normally.

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
		return self

	@staticmethod
	def build_ghost_bias (grid: int, bias: str) -> typing.List[float]:

		"""Build probability weights for ghost notes or other generative functions.

		Generates a list of probability weights (values between 0.0 and 1.0) spanning
		a given grid size. These curves shape probability over a beat,
		assigning higher or lower chances of an event occurring based on the rhythmic
		position within the beat (downbeat, offbeat, syncopated 16th note, etc).

		Can be passed back into the `bias` argument of :meth:`ghost_fill()`. Exposing
		this method allows users to generate a standard curve and then manually
		modify specific probabilities on specific steps before passing it
		to generative methods.

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

		Returns:
			A list of floats with length equal to `grid`, where each value
			is a probability multiplier from 0.0 to 1.0.
		"""

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

	def ghost_fill (
		self,
		pitch: typing.Union[int, str],
		density: float = 0.3,
		velocity: typing.Union[
			int,
			typing.Tuple[int, int],
			typing.Sequence[typing.Union[int, float]],
			typing.Callable[[int], typing.Union[int, float]]
		] = 35,
		bias: typing.Union[str, typing.List[float]] = "uniform",
		no_overlap: bool = True,
		grid: typing.Optional[int] = None,
		duration: float = 0.1,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""Fill the pattern with probability-biased ghost notes.

		A single method for generating musically-aware ghost note layers.
		Combines density control, velocity randomisation, and rhythmic bias
		to produce the micro-detail layering heard in dense electronic
		music production.

		Parameters:
			pitch: MIDI note number or drum name.
			density: Overall density (0.0–1.0).  How many available steps
				receive ghost notes.  0.3 = roughly 30% of steps at peak bias.
			velocity: Single velocity, ``(low, high)`` tuple for random range,
				a list/sequence of values (indexed by step), or a callable
				that takes the step index ``i`` and returns a velocity.
				Allows dynamic values like Perlin noise curves.
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
			             bias="sixteenths", no_overlap=True)
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
			weights = self.build_ghost_bias(grid, bias)

		max_weight = max(weights) if weights else 1.0

		if max_weight <= 0:
			return self

		midi_pitch = self._resolve_pitch(pitch)
		step_duration = self._pattern.length / grid

		for i in range(grid):
			prob = density * weights[i] / max_weight

			if rng.random() >= prob:
				continue

			if no_overlap:
				pulse = int(round(i * step_duration * subsequence.constants.MIDI_QUARTER_NOTE))
				if pulse in self._pattern.steps:
					if any(n.pitch == midi_pitch for n in self._pattern.steps[pulse].notes):
						continue

			if callable(velocity):
				vel = int(velocity(i))
			elif isinstance(velocity, tuple) and len(velocity) == 2:
				vel = rng.randint(int(velocity[0]), int(velocity[1]))
			elif isinstance(velocity, (list, tuple)):
				vel = int(velocity[i % len(velocity)])
			else:
				vel = int(typing.cast(typing.Union[int, float], velocity))

			self.note(pitch=pitch, beat=i * step_duration, velocity=vel, duration=duration)
		return self

	def cellular_1d (
		self,
		pitch: typing.Union[int, str],
		rule: int = 30,
		generation: typing.Optional[int] = None,
		velocity: int = 60,
		duration: float = 0.1,
		no_overlap: bool = False,
		dropout: float = 0.0,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

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
			velocity: MIDI velocity.
			duration: Note duration in beats.
			no_overlap: If True, skip where same pitch already exists.
			dropout: Probability (0.0–1.0) of skipping each hit.
			rng: Random generator for dropout.

		Example:
			```python
			p.hit_steps("kick_1", [0, 8], velocity=100)
			p.cellular_1d("kick_1", rule=30, velocity=40, no_overlap=True)
			```
		"""

		if generation is None:
			generation = self.cycle

		if rng is None:
			rng = self.rng

		steps = self._default_grid
		sequence = subsequence.sequence_utils.generate_cellular_automaton_1d(
			steps=steps, rule=rule, generation=generation
		)

		self._place_rhythm_sequence(
			sequence, pitch, velocity, duration, dropout, rng, no_overlap=no_overlap
		)
		return self

	cellular = cellular_1d

	def cellular_2d (
		self,
		pitches: typing.List[typing.Union[int, str]],
		rule: str = "B368/S245",
		generation: typing.Optional[int] = None,
		velocity: typing.Union[int, typing.List[int]] = 60,
		duration: float = 0.1,
		no_overlap: bool = False,
		dropout: float = 0.0,
		seed: typing.Union[int, typing.List[typing.List[int]]] = 1,
		density: float = 0.5,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""Generate polyphonic patterns using a 2D Life-like cellular automaton.

		Evolves a 2D grid where rows map to pitches or instruments and columns
		map to time steps.  Live cells in the final generation become note
		onsets, producing patterns with spatial structure that evolves each bar.

		The default rule B368/S245 (Morley/"Move") produces chaotic, active
		patterns.  B3/S23 is Conway's Life; B36/S23 is HighLife.

		Parameters:
			pitches: MIDI note numbers or drum names, one per row.  Row 0
			         maps to the first pitch.
			rule: Birth/Survival notation, e.g. ``"B3/S23"`` for Conway's
			      Life, ``"B368/S245"`` for Morley.
			generation: CA generation to render.  Defaults to ``self.cycle``
			    so the grid evolves each bar automatically.
			velocity: Single MIDI velocity for all rows, or a list with one
			          value per row.
			duration: Note duration in beats.
			no_overlap: If True, skip notes where same pitch already exists.
			dropout: Probability (0.0–1.0) of skipping each live cell.
			seed: Initial grid state.  ``1`` places a single live cell at
			      the centre.  Any other ``int`` uses a seeded RNG with
			      *density*.  A ``list[list[int]]`` provides an explicit
			      rows × cols grid.
			density: Fill probability when *seed* is a random int (0.0–1.0).
			rng: Random generator for dropout.  Uses ``self.rng`` if None.

		Example:
			```python
			pitches = [36, 38, 42, 46]  # kick, snare, hihat, open hihat
			p.cellular_2d(pitches, rule="B3/S23", seed=7, density=0.3)
			```
		"""

		if generation is None:
			generation = self.cycle

		if rng is None:
			rng = self.rng

		cols = self._default_grid
		rows = len(pitches)

		grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
			rows=rows,
			cols=cols,
			rule=rule,
			generation=generation,
			seed=seed,
			density=density,
		)

		for row_idx, pitch in enumerate(pitches):
			row_velocity: int

			if isinstance(velocity, list):
				row_velocity = int(velocity[row_idx % len(velocity)])
			else:
				row_velocity = int(velocity)

			self._place_rhythm_sequence(
				grid[row_idx], pitch, row_velocity, duration, dropout, rng, no_overlap=no_overlap
			)
		return self

	def markov (
		self,
		transitions: typing.Dict[str, typing.List[typing.Tuple[str, int]]],
		pitch_map: typing.Dict[str, int],
		velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: float = 0.1,
		spacing: float = 0.25,
		start: typing.Optional[str] = None,
	) -> "PatternAlgorithmicMixin":

		"""Generate a sequence by walking a first-order Markov chain.

		Builds a :class:`~subsequence.weighted_graph.WeightedGraph` from
		``transitions`` and walks it, placing one note per ``step`` beats.
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
			velocity: MIDI velocity for all placed notes (default 100).
			duration: Note duration in beats (default 0.1).
			spacing: Time between note onsets in beats (default 0.25 = 16th note).
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
			    spacing=0.5,
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

		n_steps = int(self._pattern.length / spacing)

		state = start
		beat = 0.0

		for _ in range(n_steps):

			if state in pitch_map:
				self.note(pitch=pitch_map[state], beat=beat, velocity=velocity, duration=duration)

			state = graph.choose_next(state, self.rng)
			beat += spacing
		return self

	def melody (
		self,
		state: subsequence.melodic_state.MelodicState,
		spacing: float = 0.25,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 90,
		duration: float = 0.2,
		chord_tones: typing.Optional[typing.List[int]] = None,
	) -> "PatternAlgorithmicMixin":

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

		Example:
			```python
			melody_state = subsequence.MelodicState(
			    key="A", mode="aeolian",
			    low=60, high=84,
			    nir_strength=0.6,
			    chord_weight=0.4,
			)

			@composition.pattern(channel=4, length=4, chord=True)
			def lead (p, chord):
			    tones = chord.tones(72) if chord else None
			    p.melody(melody_state, spacing=0.5, velocity=(70, 100), chord_tones=tones)
			```
		"""

		n_steps = int(self._pattern.length / spacing)
		beat = 0.0

		for _ in range(n_steps):

			pitch = state.choose_next(chord_tones, self.rng)

			if pitch is not None:
				vel = (
					self.rng.randint(velocity[0], velocity[1])
					if isinstance(velocity, tuple)
					else velocity
				)
				self.note(pitch=pitch, beat=beat, velocity=vel, duration=duration)

			beat += spacing
		return self

	def lsystem (
		self,
		pitch_map: typing.Dict[str, typing.Union[int, str]],
		axiom: str,
		rules: typing.Dict[str, typing.Union[str, typing.List[typing.Tuple[str, float]]]],
		generations: int = 3,
		spacing: typing.Optional[float] = None,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 80,
		duration: float = 0.2,
	) -> "PatternAlgorithmicMixin":

		"""Generate a note sequence using L-system string rewriting.

		Expands ``axiom`` by applying ``rules`` for ``generations``
		iterations, then walks the resulting string placing a note for
		each character found in ``pitch_map``.  Unmapped characters are
		silent rests - they advance time but produce no note.

		The defining musical property is self-similarity: patterns repeat
		at different time scales.  The Fibonacci rule (``A → AB``,
		``B → A``) places hits at golden-ratio spacings.  Koch and dragon
		curve rules produce fractal melodic contours.

		With ``spacing=None`` (default) the entire expanded string is fitted
		into the bar: each generation makes notes twice as dense while
		preserving the overall shape.  With a fixed ``spacing`` the string is
		truncated to fit and the density stays constant.

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

		Example:
			```python
			# Fibonacci kick rhythm - self-similar hit spacing
			p.lsystem(
			    pitch_map={"A": "kick_1"},
			    axiom="A",
			    rules={"A": "AB", "B": "A"},
			    generations=6,
			    velocity=80,
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

		expanded = subsequence.sequence_utils.lsystem_expand(
			axiom=axiom,
			rules=rules,
			generations=generations,
			rng=self.rng,
		)

		if not expanded:
			return self

		if spacing is None:
			auto_step = self._pattern.length / len(expanded)
			symbols = expanded
		else:
			auto_step = spacing
			n_steps = int(self._pattern.length / spacing)
			symbols = expanded[:n_steps]

		beat = 0.0

		for symbol in symbols:
			if symbol in pitch_map:
				vel = (
					self.rng.randint(velocity[0], velocity[1])
					if isinstance(velocity, tuple)
					else int(velocity)
				)
				self.note(
					pitch=pitch_map[symbol],
					beat=beat,
					velocity=vel,
					duration=duration,
				)
			beat += auto_step
		return self

	def thue_morse (
		self,
		pitch: typing.Union[int, str],
		velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY,
		duration: float = 0.1,
		pitch_b: typing.Optional[typing.Union[int, str]] = None,
		velocity_b: typing.Optional[int] = None,
		no_overlap: bool = False,
		dropout: float = 0.0,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""Place notes using the Thue-Morse aperiodic binary sequence.

		The Thue-Morse sequence (0 1 1 0 1 0 0 1 1 0 0 1 0 1 1 0 …) is
		perfectly balanced, overlap-free, and self-similar but never periodic.
		It produces rhythmic patterns that feel structured yet never settle into
		a simple repeating loop - a quality distinct from Euclidean rhythms
		(evenly spaced) and cellular automata (rule-driven evolution).

		In **single-pitch mode** (default), notes are placed at positions where
		the sequence is 1.  In **two-pitch mode** (``pitch_b`` given), ``pitch``
		is placed at 0-positions and ``pitch_b`` at 1-positions - useful for
		alternating two drums or two chord tones.

		Parameters:
			pitch: Pitch (MIDI note number or drum name) for sequence-1 positions.
			velocity: MIDI velocity for ``pitch``.
			duration: Note duration in beats.
			pitch_b: Optional second pitch placed at sequence-0 positions.
			    When set, all steps produce a note (no rests).
			velocity_b: Velocity for ``pitch_b``.  Defaults to ``velocity``.
			no_overlap: Skip steps where ``pitch`` is already sounding.
			dropout: Probability [0.0–1.0] of randomly skipping any active step.
			rng: Random number generator.  Defaults to ``self.rng``.

		Example:
			```python
			# Single-pitch Thue-Morse kick
			p.thue_morse("kick_1", velocity=100)

			# Two-pitch mode: alternate kick and snare
			p.thue_morse("kick_1", pitch_b="snare_1", velocity=100)
			```
		"""

		if rng is None:
			rng = self.rng

		sequence = subsequence.sequence_utils.thue_morse(self._default_grid)

		if pitch_b is None:
			self._place_rhythm_sequence(sequence, pitch, velocity, duration, dropout, rng, no_overlap)
		else:
			if velocity_b is None:
				velocity_b = velocity
			step_dur = self._pattern.length / len(sequence)
			for i, val in enumerate(sequence):
				if dropout > 0 and rng.random() < dropout:
					continue
				if val == 0:
					self.note(pitch=pitch, beat=i * step_dur, velocity=velocity, duration=duration)
				else:
					self.note(pitch=pitch_b, beat=i * step_dur, velocity=velocity_b, duration=duration)
		return self

	def de_bruijn (
		self,
		pitches: typing.List[typing.Union[int, str]],
		window: int = 2,
		spacing: typing.Optional[float] = None,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 80,
		duration: float = 0.2,
	) -> "PatternAlgorithmicMixin":

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
			    notes.  Keep small (2–4) for practical bar lengths.
			spacing: Time between notes in beats.  ``None`` auto-fits the sequence
			    into the bar; a float uses fixed spacing and truncates.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.

		Example:
			```python
			# All 2-note combinations of a pentatonic scale
			p.de_bruijn([60, 62, 64, 67, 69], window=2, velocity=(60, 100))
			```
		"""

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		k = len(pitches)
		sequence = subsequence.sequence_utils.de_bruijn(k, window)

		if not sequence:
			return self

		if spacing is None:
			auto_step = self._pattern.length / len(sequence)
			symbols = sequence
		else:
			auto_step = spacing
			n_steps = int(self._pattern.length / spacing)
			symbols = sequence[:n_steps]

		beat = 0.0

		for idx in symbols:
			vel = (
				self.rng.randint(velocity[0], velocity[1])
				if isinstance(velocity, tuple)
				else int(velocity)
			)
			self.note(pitch=pitches[idx], beat=beat, velocity=vel, duration=duration)
			beat += auto_step
		return self

	def fibonacci (
		self,
		pitch: typing.Union[int, str],
		steps: int,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 80,
		duration: float = 0.2,
	) -> "PatternAlgorithmicMixin":

		"""Place notes at golden-ratio-spaced beat positions (Fibonacci spiral timing).

		Uses the golden angle method - ``position_i = (i × φ) mod bar_length`` -
		to distribute ``steps`` events across the bar.  The result is sorted
		into ascending time order.  Unlike a Euclidean rhythm (maximally even
		spacing on a fixed grid), Fibonacci timing is irrational and places
		events off-grid in a way that sounds organic and avoids metronomic
		repetition.

		Parameters:
			pitch: MIDI note number or drum name.
			steps: Number of notes to place.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.

		Example:
			```python
			# 11 hi-hat hits with golden-ratio spacing
			p.fibonacci("hi_hat_closed", steps=11, velocity=(60, 90))
			```
		"""

		beats = subsequence.sequence_utils.fibonacci_rhythm(steps, self._pattern.length)

		for beat in beats:
			vel = (
				self.rng.randint(velocity[0], velocity[1])
				if isinstance(velocity, tuple)
				else int(velocity)
			)
			self.note(pitch=pitch, beat=beat, velocity=vel, duration=duration)
		return self

	def lorenz (
		self,
		pitches: typing.List[typing.Union[int, str]],
		spacing: float = 0.25,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 80,
		duration: float = 0.2,
		dt: float = 0.01,
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
	) -> "PatternAlgorithmicMixin":

		"""Generate a note sequence driven by the Lorenz strange attractor.

		Integrates the Lorenz system to produce a trajectory of (x, y, z) points,
		each normalised to [0, 1].  The three axes provide correlated but
		independent modulation sources: by default x drives pitch selection,
		y drives velocity, and z drives duration.

		The Lorenz attractor is deterministic but extremely sensitive to initial
		conditions: changing ``x0`` by even 0.001 produces a divergent trajectory
		over time.  This makes it ideal for cycle-by-cycle variation - pass
		``x0=p.cycle * 0.001`` to generate a unique but slowly evolving phrase
		each bar.

		A custom ``mapping`` callable can override the default x/y/z → pitch/vel/dur
		assignment, or return ``None`` for a rest.

		Parameters:
			pitches: Pitch pool.  The x-axis selects an index: ``int(x * len(pitches)) % len(pitches)``.
			spacing: Time between notes in beats.  Default 0.25 (16th note).
			velocity: Fixed velocity or ``(low, high)`` tuple.  Overridden by ``mapping``.
			duration: Maximum note duration.  z is scaled to ``[0.05, duration]``.
			    Overridden by ``mapping``.
			dt: Integration time step.  Default 0.01.
			sigma, rho, beta: Lorenz parameters.  Defaults produce the classic
			    butterfly attractor (chaotic regime).
			x0, y0, z0: Initial conditions.  Use ``x0=p.cycle * small_delta``
			    for slowly evolving variation.
			mapping: Optional callable ``(x, y, z) -> (pitch, velocity, duration)``
			    or ``None`` for rest.

		Example:
			```python
			scale = [60, 62, 64, 65, 67, 69, 71, 72]
			p.lorenz(scale, spacing=0.25, velocity=(50, 110), x0=p.cycle * 0.002)
			```
		"""

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		n_steps = int(self._pattern.length / spacing)
		points = subsequence.sequence_utils.lorenz_attractor(
			n_steps, dt=dt, sigma=sigma, rho=rho, beta=beta, x0=x0, y0=y0, z0=z0
		)

		beat = 0.0

		for x, y, z in points:

			if mapping is not None:
				result = mapping(x, y, z)
				if result is not None:
					p_pitch, p_vel, p_dur = result
					self.note(pitch=p_pitch, beat=beat, velocity=p_vel, duration=p_dur)
			else:
				pitch_idx = int(x * len(pitches)) % len(pitches)
				p_pitch = pitches[pitch_idx]
				if isinstance(velocity, tuple):
					p_vel = int(velocity[0] + y * (velocity[1] - velocity[0]))
				else:
					p_vel = int(40 + y * 87)
				p_dur = 0.05 + z * max(0.0, duration - 0.05)
				self.note(pitch=p_pitch, beat=beat, velocity=p_vel, duration=p_dur)

			beat += spacing
		return self

	def reaction_diffusion (
		self,
		pitch: typing.Union[int, str],
		threshold: float = 0.5,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 80,
		duration: float = 0.1,
		feed_rate: float = 0.055,
		kill_rate: float = 0.062,
		steps: int = 1000,
		no_overlap: bool = False,
		dropout: float = 0.0,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""Generate a rhythm from a 1D Gray-Scott reaction-diffusion simulation.

		Simulates the Gray-Scott model on a ring of ``_default_grid`` cells,
		then thresholds the final V-concentration to produce a binary hit
		pattern.  Cells where concentration exceeds ``threshold`` become note
		events.

		Unlike cellular automata - where rules are discrete and the state is
		binary - reaction-diffusion evolves a continuous concentration field
		governed by diffusion rates and chemical reactions.  The resulting
		spatial patterns (spots, stripes, travelling waves) have an organic,
		biological character that maps naturally to rhythm.

		The ``feed_rate`` and ``kill_rate`` parameters control pattern type:
		typical values that produce spots (useful rhythms) range from 0.020–0.062
		for feed and 0.045–0.069 for kill.  The defaults (F=0.055, k=0.062)
		produce a stable spotted pattern.

		Parameters:
			pitch: MIDI note number or drum name.
			threshold: V-concentration threshold for note placement (0.0–1.0).
			    Lower values produce denser patterns.
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per step.
			duration: Note duration in beats.
			feed_rate: Rate of U replenishment.  Default 0.055.
			kill_rate: Rate of V removal.  Default 0.062.
			steps: Number of simulation iterations.  More = more developed
			    pattern.  Default 1000.
			no_overlap: Skip steps where ``pitch`` is already sounding.
			dropout: Probability [0.0–1.0] of randomly skipping any active step.
			rng: Random number generator.  Defaults to ``self.rng``.

		Example:
			```python
			# Organic kick pattern from reaction-diffusion
			p.reaction_diffusion("kick_1", threshold=0.4, feed_rate=0.037, kill_rate=0.060)
			```
		"""

		if rng is None:
			rng = self.rng

		concentrations = subsequence.sequence_utils.reaction_diffusion_1d(
			width=self._default_grid,
			steps=steps,
			feed_rate=feed_rate,
			kill_rate=kill_rate,
		)

		sequence = [1 if c > threshold else 0 for c in concentrations]

		if isinstance(velocity, tuple):
			# Map concentration to velocity range for active steps.
			step_dur = self._pattern.length / len(sequence)
			midi_vel_lo, midi_vel_hi = velocity
			for i, (hit, conc) in enumerate(zip(sequence, concentrations)):
				if hit == 0:
					continue
				if dropout > 0 and rng.random() < dropout:
					continue
				vel = int(midi_vel_lo + conc * (midi_vel_hi - midi_vel_lo))
				self.note(pitch=pitch, beat=i * step_dur, velocity=vel, duration=duration)
		else:
			self._place_rhythm_sequence(sequence, pitch, int(velocity), duration, dropout, rng, no_overlap)
		return self

	def self_avoiding_walk (
		self,
		pitches: typing.List[typing.Union[int, str]],
		spacing: float = 0.25,
		velocity: typing.Union[int, typing.Tuple[int, int]] = 80,
		duration: float = 0.2,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""Generate a melody using a self-avoiding random walk.

		A self-avoiding walk moves ±1 step through a pitch index space, tracking
		visited positions and refusing to revisit them.  When the walk is trapped
		(all neighbours visited), the visited set resets and the walk continues
		from the current position - creating natural phrase boundaries.

		Compared to :func:`random_walk`, the self-avoiding variant guarantees
		pitch diversity within each phrase: no pitch repeats until the walk
		resets.  The contiguous step motion (never skipping pitches) gives
		melodies a smooth, step-wise quality with occasional direction reversals.

		Parameters:
			pitches: Ordered list of MIDI note numbers or note strings.  The walk
			    moves through indices ``[0, len(pitches) - 1]``, mapping each to
			    the corresponding pitch.
			spacing: Time between notes in beats.  Default 0.25 (16th note).
			velocity: MIDI velocity.  An ``(low, high)`` tuple randomises per note.
			duration: Note duration in beats.
			rng: Random number generator.  Defaults to ``self.rng``.

		Example:
			```python
			scale = subsequence.scale_notes("C", "ionian", low=60, high=72)
			p.self_avoiding_walk(scale, spacing=0.25, velocity=(60, 100))
			```
		"""

		if rng is None:
			rng = self.rng

		if not pitches:
			raise ValueError("pitches list cannot be empty")

		n_steps = int(self._pattern.length / spacing)
		indices = subsequence.sequence_utils.self_avoiding_walk(
			n=n_steps,
			low=0,
			high=len(pitches) - 1,
			rng=rng,
		)

		beat = 0.0

		for idx in indices:
			vel = (
				rng.randint(velocity[0], velocity[1])
				if isinstance(velocity, tuple)
				else int(velocity)
			)
			self.note(pitch=pitches[idx], beat=beat, velocity=vel, duration=duration)
			beat += spacing
		return self

	def thin (
		self,
		pitch: typing.Optional[typing.Union[int, str]] = None,
		strategy: typing.Union[str, typing.List[float]] = "strength",
		amount: float = 0.5,
		grid: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
	) -> "PatternAlgorithmicMixin":

		"""
		Remove notes from the pattern based on their rhythmic position.

		This is the musical inverse of :meth:`ghost_fill()`.  Where ``ghost_fill``
		uses bias weights to decide where to *add* ghost notes, ``thin`` uses the
		same position vocabulary to decide where to *remove* notes.  A high
		strategy weight on a position means that position is dropped first.

		The strategy names match those in :meth:`build_ghost_bias()` and carry the
		same rhythmic meaning:

		- ``"sixteenths"`` - removes 16th-note subdivisions (e/a), keeps beats and &.
		- ``"offbeat"``    - removes the & position, straightens the groove.
		- ``"e_and_a"``    - removes all non-downbeat positions, keeps only beats.
		- ``"downbeat"``   - removes beat positions (floating/displaced effect).
		- ``"upbeat"``     - removes only the & position.
		- ``"uniform"``    - removes from all positions equally (per-instrument dropout).
		- ``"strength"``   - progressive thinning: weakest positions (e/a) drop first,
		  strongest (downbeat) last. Useful for Perlin-driven density control.

		When ``pitch`` is given, only notes of that instrument are affected -
		useful for drum layers.  When ``pitch`` is ``None`` (the default), all
		notes regardless of pitch are candidates.  This makes ``thin`` a
		rhythm-aware generalisation of :meth:`dropout()`, and is ideal for
		tonal patterns such as arpeggios where each step carries a different pitch.

		Position classification is **zone-based**: each grid step owns the pulse range
		``[N * step_pulses, (N + 1) * step_pulses)``, so notes shifted by swing or
		groove are still classified correctly regardless of call order.

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
			rng: Random number generator. Defaults to ``self.rng``.

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

		if rng is None:
			rng = self.rng

		if grid is None:
			grid = self._default_grid

		midi_pitch = self._resolve_pitch(pitch) if pitch is not None else None

		# Build the per-step drop-priority weights.
		#
		# Strategy names are shared with ghost_fill's bias vocabulary.  The per-step
		# weights from build_ghost_bias() are reused directly, with semantics inverted:
		#   ghost_fill:  high weight → place a note here
		#   thin:        high weight → drop a note from here
		#
		# "strength" is defined only for thin() - it expresses a thinning hierarchy
		# (weakest positions drop first) which has no meaningful ghost_fill equivalent.
		if strategy == "strength":
			# Per-beat drop priorities: e/a (1.0) > & (0.6) > downbeat (0.05).
			# As `amount` rises, progressively weaker positions are removed first.
			steps_per_beat = max(1, grid // 4)
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
			# Reuse build_ghost_bias() weights for all shared strategy names.
			# The positions that ghost_fill prefers to add to are the same
			# positions that thin() will prefer to remove from.
			priorities = self.build_ghost_bias(grid, strategy)

		# Zone-based pulse classification.
		# Zone N owns pulses in [ N * step_pulses, (N+1) * step_pulses ).
		# Notes shifted by swing or groove remain in their original zone.
		total_pulses = self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE
		step_pulses = total_pulses / grid

		pulses_to_remove: typing.List[int] = []

		for pulse, step in list(self._pattern.steps.items()):

			zone = int(pulse / step_pulses)
			if zone >= grid:
				zone = grid - 1

			priority = priorities[zone]
			if priority <= 0.0:
				continue

			# Separate target notes from protected notes at this pulse.
			if midi_pitch is None:
				remaining = []
				targets   = list(step.notes)
			else:
				remaining = [n for n in step.notes if n.pitch != midi_pitch]
				targets   = [n for n in step.notes if n.pitch == midi_pitch]

			for note in targets:
				if rng.random() >= priority * amount:
					remaining.append(note)
				# else: note is dropped

			if not remaining:
				pulses_to_remove.append(pulse)
			else:
				step.notes = remaining

		for pulse in pulses_to_remove:
			del self._pattern.steps[pulse]
		return self
