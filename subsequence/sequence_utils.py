"""Utility functions for generating and transforming step sequences.

Provides algorithms for rhythm generation (Euclidean, Bresenham, van der Corput),
sequence manipulation (roll, legato, probability gate), and general-purpose
generative helpers (random walk, weighted choice, shuffled choices, scale/clamp).
"""

import math
import random
import typing

T = typing.TypeVar("T")


def generate_euclidean_sequence (steps: int, pulses: int) -> typing.List[int]:

	"""
	Generate a Euclidean rhythm using Bjorklund's algorithm.
	"""

	if pulses == 0:
		return [0] * steps

	if pulses > steps:
		raise ValueError(f"Pulses ({pulses}) cannot be greater than steps ({steps})")

	sequence = []
	counts = []
	remainders = []
	divisor = steps - pulses

	remainders.append(pulses)
	level = 0

	while True:
		counts.append(divisor // remainders[level])
		remainders.append(divisor % remainders[level])
		divisor = remainders[level]
		level += 1
		if remainders[level] <= 1:
			break

	counts.append(divisor)

	def build (level: int) -> None:
		if level == -1:
			sequence.append(0)
		elif level == -2:
			sequence.append(1)
		else:
			for i in range(counts[level]):
				build(level - 1)
			if remainders[level] != 0:
				build(level - 2)

	build(level)
	i = sequence.index(1)
	return sequence[i:] + sequence[:i]


def generate_bresenham_sequence (steps: int, pulses: int) -> typing.List[int]:

	"""
	Generate a rhythm using Bresenham's line algorithm.
	"""

	sequence = [0] * steps
	error = 0
	
	for i in range(steps):
		error += pulses
		if error >= steps:
			sequence[i] = 1
			error -= steps
			
	return sequence


def generate_bresenham_sequence_weighted (steps: int, weights: typing.List[float]) -> typing.List[int]:

	"""
	Generate a sequence that distributes weighted indices across steps.
	"""

	if steps <= 0:
		raise ValueError("Steps must be positive")

	if not weights:
		raise ValueError("Weights cannot be empty")

	acc = [0.0] * len(weights)
	sequence: typing.List[int] = []

	for _ in range(steps):

		for i, weight in enumerate(weights):
			acc[i] += weight

		chosen = max(range(len(weights)), key=lambda i: acc[i])
		sequence.append(chosen)
		acc[chosen] -= 1.0

	return sequence


def generate_van_der_corput_sequence (n: int, base: int = 2) -> typing.List[float]:

	"""
	Generate a sequence of n numbers using the van der Corput sequence.
	"""

	sequence = []
	
	for i in range(n):
		value = 0.0
		f = 1.0 / base
		k = i
		while k > 0:
			value += (k % base) * f
			k //= base
			f /= base
		sequence.append(value)
		
	return sequence


def sequence_to_indices (sequence: typing.List[int]) -> typing.List[int]:

	"""Extract step indices where hits occur in a binary sequence."""

	return [i for i, v in enumerate(sequence) if v]


def roll (indices: typing.List[int], shift: int, length: int) -> typing.List[int]:

	"""Circularly shift step indices by the specified amount."""

	return [(i + shift) % length for i in indices]


def generate_legato_durations (hits: typing.List[int]) -> typing.List[int]:

	"""
	Convert a hit list into per-step legato durations.
	"""

	if not hits:
		return []

	note_on_indices = [idx for idx, hit in enumerate(hits) if hit]
	note_on_indices.append(len(hits))

	durations = [0] * len(hits)

	for idx, next_idx in zip(note_on_indices[:-1], note_on_indices[1:]):
		durations[idx] = max(1, next_idx - idx)

	return durations


def weighted_choice (options: typing.List[typing.Tuple[T, float]], rng: random.Random) -> T:

	"""Pick one item from a list of (value, weight) pairs.

	Weights are relative - they don't need to sum to 1.0. Higher weight means
	higher probability of selection.

	Parameters:
		options: List of `(value, weight)` tuples
		rng: Random number generator instance

	Example:
		```python
		density = subsequence.sequence_utils.weighted_choice([
			(3, 0.5),   # 3 hits: 50%
			(5, 0.3),   # 5 hits: 30%
			(7, 0.2),   # 7 hits: 20%
		], p.rng)
		p.euclidean("snare", pulses=density)
		```
	"""

	if not options:
		raise ValueError("Options list cannot be empty")

	values, weights = zip(*options)
	total = sum(weights)

	if total <= 0:
		raise ValueError("Total weight must be positive")

	threshold = rng.random() * total
	cumulative = 0.0

	for value, weight in options:
		cumulative += weight
		if cumulative >= threshold:
			return value

	return options[-1][0]


def shuffled_choices (pool: typing.List[T], n: int, rng: random.Random) -> typing.List[T]:

	"""Choose N items from a pool with no immediate repetition.

	Within each pass through the pool, every item appears before any repeats.
	Across reshuffles, the last item of one pass is never the first of the next.
	Similar to Max/MSP's ``urn`` object.

	Parameters:
		pool: Items to choose from
		n: Number of items to return
		rng: Random number generator instance

	Example:
		```python
		# 16 velocity values with no adjacent repeats
		vels = subsequence.sequence_utils.shuffled_choices([70, 85, 100, 110], 16, p.rng)
		```
	"""

	if not pool:
		raise ValueError("Pool cannot be empty")

	if n <= 0:
		return []

	result: typing.List[T] = []
	last: typing.Optional[T] = None

	while len(result) < n:

		deck = list(pool)
		rng.shuffle(deck)

		# Prevent adjacent repeat across reshuffles.
		if last is not None and len(deck) > 1 and deck[0] == last:
			# Swap with a random later position.
			swap_idx = rng.randint(1, len(deck) - 1)
			deck[0], deck[swap_idx] = deck[swap_idx], deck[0]

		for item in deck:

			if len(result) >= n:
				break

			result.append(item)
			last = item

	return result


def random_walk (n: int, low: int, high: int, step: int, rng: random.Random, start: typing.Optional[int] = None) -> typing.List[int]:

	"""Generate values that drift by small steps within a range.

	Each value moves up or down by at most ``step`` from the previous,
	clamped to ``[low, high]``. Similar to Max/MSP's ``drunk`` object.

	Parameters:
		n: Number of values to generate
		low: Minimum value (inclusive)
		high: Maximum value (inclusive)
		step: Maximum change per step
		rng: Random number generator instance
		start: Starting value (default: midpoint of range)

	Example:
		```python
		# Wandering velocity for 16 hi-hat steps
		walk = subsequence.sequence_utils.random_walk(16, low=50, high=110, step=15, rng=p.rng)
		```
	"""

	if n <= 0:
		return []

	if low > high:
		raise ValueError(f"low ({low}) must be <= high ({high})")

	if start is not None:
		current = max(low, min(high, start))
	else:
		current = (low + high) // 2

	result = [current]

	for _ in range(n - 1):
		delta = rng.randint(-step, step)
		current = max(low, min(high, current + delta))
		result.append(current)

	return result


def probability_gate (sequence: typing.List[int], probability: typing.Union[float, typing.List[float]], rng: random.Random) -> typing.List[int]:

	"""Filter a binary sequence by probability.

	Each active step (value > 0) is kept with the given probability.
	Inactive steps (value == 0) are never promoted.

	Parameters:
		sequence: Binary sequence (0s and 1s)
		probability: Chance of keeping each hit (0.0–1.0). A single float applies
			uniformly; a list assigns per-step probability.
		rng: Random number generator instance

	Example:
		```python
		seq = subsequence.sequence_utils.generate_euclidean_sequence(16, 7)
		gated = subsequence.sequence_utils.probability_gate(seq, 0.7, p.rng)
		p.hit_steps("hh", subsequence.sequence_utils.sequence_to_indices(gated))
		```
	"""

	result: typing.List[int] = []

	for i, value in enumerate(sequence):

		if value == 0:
			result.append(0)
			continue

		if isinstance(probability, list):
			prob = probability[i] if i < len(probability) else 1.0
		else:
			prob = probability

		result.append(value if rng.random() < prob else 0)

	return result



def scale_clamp (value: float, in_min: float, in_max: float, out_min: float = 0.0, out_max: float = 1.0) -> float:

	"""Scale a value from an input range to an output range and clamp the result.

	Maps a value from [in_min, in_max] to [out_min, out_max]. If the result
	falls outside the output range, it is clamped to the nearest bound.
	Correctly handles reversed ranges (where min > max).

	Parameters:
		value: The number to scale and clamp.
		in_min: The start of the input range.
		in_max: The end of the input range.
		out_min: The start of the target output range (default: 0.0).
		out_max: The end of the target output range (default: 1.0).

	Example:
		```python
		# Scale sensor data (0-1023) to a probability (0.0-1.0)
		prob = subsequence.sequence_utils.scale_clamp(sensor_val, 0, 1023)

		# Invert a MIDI CC (0-127) to a volume multiplier (1.0-0.0)
		vol = subsequence.sequence_utils.scale_clamp(cc_val, 0, 127, 1.0, 0.0)
		```
	"""

	if in_min == in_max:

		raise ValueError(f"Input range cannot be zero-width ({in_min} == {in_max})")

	percentage = (value - in_min) / (in_max - in_min)
	scaled = out_min + percentage * (out_max - out_min)

	# Handle regular and reversed ranges
	if out_min < out_max:
		return max(out_min, min(out_max, scaled))
	else:
		return max(out_max, min(out_min, scaled))


def perlin_1d (x: float, seed: int = 0) -> float:

	"""Generate smooth 1D noise at position *x*.

	Returns a value in [0.0, 1.0] that varies smoothly as *x* changes.
	Same *x* and *seed* always produce the same output.  Use to drive
	density, velocity, or probability parameters that should wander
	organically over time — the "parameter wandering within boundaries"
	quality of generative electronic music systems.

	Parameters:
		x: Position along the noise field.  Use ``bar * scale`` where
			``scale`` controls the rate of change (smaller = slower).
			0.05–0.1 is good for bar-level wandering.
		seed: Seed for the hash function.  Different seeds produce
			different but equally smooth noise fields.

	Example:
		```python
		# Smooth density that wanders over bars
		density = subsequence.sequence_utils.perlin_1d(p.cycle * 0.08, seed=42)
		p.bresenham("snare_1", pulses=max(1, round(density * 6)),
		            velocity=35, no_overlap=True)
		```
	"""

	x0 = math.floor(x)
	x1 = x0 + 1
	t = x - x0

	def _grad (pos: int) -> float:
		# Hash function using Linear Congruential Generator (LCG) constants.
		# The "magic numbers" (e.g. 1103515245) distribute bits evenly and are 
		# drawn from standard C library rand() implementations to ensure high 
		# quality pseudo-randomness quickly.
		h = ((pos * 1103515245 + seed * 374761393 + 12345) & 0x7FFFFFFF)
		return (h / 0x3FFFFFFF) - 1.0

	# Smootherstep fade (6t^5 - 15t^4 + 10t^3) — same polynomial as easing.s_curve(),
	# inlined here to avoid function-call overhead in tight loops.
	fade = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

	d0 = _grad(x0) * t
	d1 = _grad(x1) * (t - 1.0)

	value = d0 + fade * (d1 - d0)

	# Normalize from roughly [-0.5, 0.5] to [0, 1]
	return max(0.0, min(1.0, value + 0.5))


def perlin_2d (x: float, y: float, seed: int = 0) -> float:

	"""Generate smooth 2D noise at position *(x, y)*.

	Returns a value in [0.0, 1.0] that varies smoothly as *x* and *y* change.
	Same coordinates and *seed* always produce the same output. Use to drive
	correlated parameters that should weave around each other organically over time,
	or for spatialized parameter wandering.

	Parameters:
		x: Position along the X axis of the noise field.
		y: Position along the Y axis of the noise field.
		seed: Seed for the hash function. Different seeds produce
			different but equally smooth noise fields.

	Example:
		```python
		# Two parameters wandering smoothly but with related movement.
		# By locking X to time and slightly separating Y, the two values
		# will move in a correlated, organic dance over the bars.
		density = subsequence.sequence_utils.perlin_2d(p.cycle * 0.08, 0.0, seed=42)
		velocity = subsequence.sequence_utils.perlin_2d(p.cycle * 0.08, 0.5, seed=42)
		```
	"""

	x0 = math.floor(x)
	y0 = math.floor(y)
	x1 = x0 + 1
	y1 = y0 + 1

	tx = x - x0
	ty = y - y0

	def _grad (pos_x: int, pos_y: int) -> float:
		# Note: The math here (smootherstep fade and hash function) is deliberately 
		# duplicated from perlin_1d rather than extracted into helper functions.
		# This avoids Python function call overhead, maximizing execution speed for
		# dense sequences. See perlin_1d for details on the LCG hash constants.
		h = ((pos_x * 1103515245 + pos_y * 741103597 + seed * 374761393 + 12345) & 0x7FFFFFFF)
		# 4 diagonal gradients
		h4 = h & 3
		dx = x - pos_x
		dy = y - pos_y
		if h4 == 0: return  dx + dy
		if h4 == 1: return -dx + dy
		if h4 == 2: return  dx - dy
		return -dx - dy

	# Smootherstep fade (6t^5 - 15t^4 + 10t^3) — same polynomial as easing.s_curve(),
	# inlined here to avoid function-call overhead in tight loops.
	fadex = tx * tx * tx * (tx * (tx * 6.0 - 15.0) + 10.0)
	fadey = ty * ty * ty * (ty * (ty * 6.0 - 15.0) + 10.0)

	d00 = _grad(x0, y0)
	d10 = _grad(x1, y0)
	d01 = _grad(x0, y1)
	d11 = _grad(x1, y1)

	# Interpolate along x
	ix0 = d00 + fadex * (d10 - d00)
	ix1 = d01 + fadex * (d11 - d01)

	# Interpolate along y
	value = ix0 + fadey * (ix1 - ix0)

	# Normalize from roughly [-1.0, 1.0] to [0.0, 1.0]
	return max(0.0, min(1.0, (value + 1.0) / 2.0))


def perlin_1d_sequence (start: float, step: float, count: int, seed: int = 0) -> typing.List[float]:

	"""Generate a sequence of smooth 1D noise values.

	Equivalent to calling :func:`perlin_1d` *count* times at evenly-spaced
	positions, but expressed as a single call.  Every value is in [0.0, 1.0].

	Parameters:
		start: Position of the first sample in the noise field.
			Typically ``p.bar * p.grid * scale`` to anchor the sequence
			to an absolute position in the piece.
		step: Distance between consecutive samples.  Matches the
			``scale`` factor used in single calls — e.g. ``0.1`` gives
			the same per-step change as ``perlin_1d(i * 0.1, seed)``.
		count: Number of values to return.
		seed: Noise field seed.  Same seed as a matching :func:`perlin_1d`
			call produces identical values at the same positions.

	Example:
		```python
		# 16 smoothly-varying velocities for hi-hat ghost notes
		noise = subsequence.sequence_utils.perlin_1d_sequence(
		    start = p.bar * p.grid * 0.1,
		    step  = 0.1,
		    count = p.grid,
		    seed  = 10
		)
		hat_velocities = [
		    int(subsequence.easing.map_value(n, out_min=50, out_max=75, shape="ease_in"))
		    for n in noise
		]
		```
	"""

	return [perlin_1d(start + i * step, seed) for i in range(count)]


def perlin_2d_grid (
	x_start: float,
	y_start: float,
	x_step: float,
	y_step: float,
	x_count: int,
	y_count: int,
	seed: int = 0
) -> typing.List[typing.List[float]]:

	"""Generate a 2D grid of smooth noise values.

	Returns a list of ``y_count`` rows, each containing ``x_count`` values
	in [0.0, 1.0].  Access as ``grid[row][col]``.  Equivalent to calling
	:func:`perlin_2d` for every *(x, y)* position in the grid.

	Parameters:
		x_start: Starting X position.
		y_start: Starting Y position.
		x_step: Spacing between columns.
		y_step: Spacing between rows.
		x_count: Number of columns (samples along X).
		y_count: Number of rows (samples along Y).
		seed: Noise field seed.

	Example:
		```python
		# 4x4 noise grid — rows are bars, columns are steps
		grid = subsequence.sequence_utils.perlin_2d_grid(
		    x_start = p.bar * 0.1,
		    y_start = 0.0,
		    x_step  = 0.1,
		    y_step  = 0.25,
		    x_count = 4,
		    y_count = 4,
		    seed    = 5,
		)
		# e.g. drive density of four voices independently
		for row, voice in enumerate(["kick", "snare", "hi_hat_closed", "clap"]):
		    density = sum(grid[row]) / len(grid[row])
		    p.ghost_fill(voice, density=density, velocity=(20, 50))
		```
	"""

	return [
		[perlin_2d(x_start + xi * x_step, y_start + yi * y_step, seed) for xi in range(x_count)]
		for yi in range(y_count)
	]



def logistic_map (r: float, steps: int, x0: float = 0.5) -> typing.List[float]:

	"""Generate a deterministic chaos sequence using the logistic map.

	A single parameter ``r`` controls behaviour from stability to chaos:
	``r < 3.0`` converges to a fixed point; ``r`` 3.0–3.57 produces
	periodic oscillations (period-2, -4, -8…); ``r > 3.57`` enters chaos.
	At ``r ≈ 3.83`` a stable period-3 window briefly returns.

	Complements :func:`perlin_1d` — use Perlin for smooth organic
	wandering and logistic_map when you need controllable order-to-chaos
	behaviour.  Feeding logistic_map values into ``hit_steps`` probability
	or ghost note velocity gives ghost notes that are "the same but never
	exactly the same."

	Parameters:
		r: Growth rate, typically 0.0–4.0.  Values outside [0, 4] will
			cause ``x`` to diverge; clamp externally if needed.
		steps: Number of values to generate.
		x0: Seed value in the open interval (0, 1).  Default 0.5.

	Example:
		```python
		# Ghost snare density that hovers at the edge of chaos
		chaos = subsequence.sequence_utils.logistic_map(r=3.7, steps=16)
		for i, v in enumerate(chaos):
		    if v > 0.5:
		        p.hit_steps("snare_2", [i], velocity=round(30 + 50 * v), no_overlap=True)
		```
	"""

	if steps <= 0:
		return []

	x = x0
	result: typing.List[float] = []

	for _ in range(steps):
		x = r * x * (1.0 - x)
		result.append(x)

	return result


def pink_noise (steps: int, sources: int = 16, seed: int = 0) -> typing.List[float]:

	"""Generate a 1/f (pink) noise sequence using the Voss-McCartney algorithm.

	Pink noise has equal energy per octave — it contains both slow drift
	and fast jitter in a single signal, matching how musical parameters
	naturally vary.  Voss and Clarke (1978) showed that pitch and loudness
	fluctuations in real music follow 1/f statistics.

	Sits between :func:`perlin_1d` (smooth, predictable) and
	:func:`logistic_map` (chaos, controllable order-to-randomness): use
	pink noise when you want statistically "natural" variation without
	tuning octave weights manually.

	Parameters:
		steps: Number of output samples.
		sources: Number of independent random sources.  More sources extend
			the low-frequency range.  Default 16 is a good general value.
		seed: RNG seed.  Same seed always produces the same sequence.

	Returns:
		List of floats in [0.0, 1.0].

	Example:
		```python
		# Humanise hi-hat velocity with pink noise
		noise = subsequence.sequence_utils.pink_noise(steps=p.grid, seed=p.bar)
		for i, level in enumerate(noise):
		    if level > 0.3:
		        p.hit_steps("hi_hat_closed", [i], velocity=round(40 + 50 * level), no_overlap=True)
		```
	"""

	if steps <= 0:
		return []

	rng = random.Random(seed)

	source_values = [rng.random() for _ in range(sources)]
	total = sum(source_values)

	result: typing.List[float] = []

	for i in range(steps):
		# Count trailing zeros of i+1 to select which source to update.
		# This distributes updates so lower-indexed sources change less
		# frequently, creating the 1/f spectral slope.
		counter = i + 1
		trailing = 0
		while counter & 1 == 0 and trailing < sources - 1:
			trailing += 1
			counter >>= 1

		old_val = source_values[trailing]
		new_val = rng.random()
		source_values[trailing] = new_val
		total = total - old_val + new_val

		result.append(total / sources)

	# Normalise to [0.0, 1.0].
	lo = min(result)
	hi = max(result)
	if hi > lo:
		result = [(v - lo) / (hi - lo) for v in result]

	return result


def lsystem_expand (
	axiom: str,
	rules: typing.Dict[str, typing.Union[str, typing.List[typing.Tuple[str, float]]]],
	generations: int,
	rng: typing.Optional[random.Random] = None,
) -> str:

	"""Expand an L-system string by applying production rules.

	An L-system rewrites every symbol in the current string simultaneously,
	each generation replacing symbols according to ``rules``.  After enough
	generations the string exhibits self-similarity: its large-scale structure
	mirrors its small-scale structure — the same property found in natural
	music, where motifs recur at phrase, section, and movement level.

	Symbols not present in ``rules`` pass through unchanged (identity rule).
	Symbols are single characters; each character in the string is one symbol.

	Rules may be deterministic (a single replacement string) or stochastic
	(a list of ``(replacement, weight)`` pairs).  Stochastic rules require
	``rng`` to be provided.

	.. note::
		String length can grow exponentially.  A doubling rule applied for
		30 generations produces ~1 billion characters.  Keep ``generations``
		to 3–8 for practical use.

	Parameters:
		axiom: Initial string (e.g. ``"A"``).
		rules: Production rules.  Deterministic: ``{"A": "AB", "B": "A"}``.
			Stochastic: ``{"A": [("AB", 3), ("BA", 1)]}`` — weights are
			relative and do not need to sum to 1.
		generations: Number of rewriting iterations.
		rng: Random number generator.  Required when any rule is stochastic;
			ignored for fully deterministic rule sets.

	Returns:
		Expanded string after ``generations`` iterations.

	Raises:
		ValueError: If stochastic rules are present but ``rng`` is ``None``.

	Example:
		```python
		# Fibonacci rhythm — hits distributed at golden-ratio spacing
		expanded = subsequence.sequence_utils.lsystem_expand(
		    axiom="A", rules={"A": "AB", "B": "A"}, generations=6
		)
		# expanded is "ABAABABAABAABABAABABA..." (length 13)

		# Stochastic — different output each bar
		expanded = subsequence.sequence_utils.lsystem_expand(
		    axiom="A",
		    rules={"A": [("AB", 3), ("BA", 1)]},
		    generations=4,
		    rng=rng,
		)
		```
	"""

	# Validate: stochastic rules need an rng.
	for production in rules.values():
		if isinstance(production, list):
			if rng is None:
				raise ValueError(
					"lsystem_expand: rng is required when rules contain stochastic productions"
				)
			break

	current = axiom

	for _ in range(generations):
		parts: typing.List[str] = []

		for symbol in current:
			if symbol not in rules:
				parts.append(symbol)
				continue

			production = rules[symbol]

			if isinstance(production, str):
				parts.append(production)
			else:
				# Stochastic: pick one replacement weighted by the float weights.
				chosen = weighted_choice(production, rng)  # type: ignore[arg-type]
				parts.append(chosen)

		current = "".join(parts)

	return current


def generate_cellular_automaton_1d (steps: int, rule: int = 30, generation: int = 0, seed: int = 1) -> typing.List[int]:

	"""Generate a binary sequence using an elementary cellular automaton.

	Evolves a 1D CA from an initial state for the specified number of
	generations, returning the final state as a binary rhythm.  Each
	generation the pattern evolves — use ``p.cycle`` as the generation
	to get a rhythm that changes every bar.

	Rule 30 produces "structured chaos" — patterns that look random but
	have hidden self-similarity.  Rule 90 produces fractal (Sierpiński
	triangle) patterns.  Rule 110 is Turing-complete.

	Parameters:
		steps: Length of the output sequence.
		rule: Wolfram rule number (0–255).  Default 30.
		generation: Number of generations to evolve from the initial state.
		seed: Initial state as a bit field.  Default 1 (single centre cell).

	Returns:
		Binary list of length *steps* (0s and 1s).

	Example:
		```python
		seq = subsequence.sequence_utils.generate_cellular_automaton_1d(
			16, rule=30, generation=p.cycle
		)
		indices = subsequence.sequence_utils.sequence_to_indices(seq)
		p.hit_steps("snare_1", indices, velocity=35)
		```
	"""

	if steps <= 0:
		return []

	state = [0] * steps

	if seed == 1:
		state[steps // 2] = 1
	else:
		for i in range(min(steps, seed.bit_length())):
			if seed & (1 << i):
				state[i] = 1

	for _ in range(generation):
		new_state = [0] * steps
		for i in range(steps):
			left = state[(i - 1) % steps]
			center = state[i]
			right = state[(i + 1) % steps]
			neighborhood = (left << 2) | (center << 1) | right
			new_state[i] = (rule >> neighborhood) & 1
		state = new_state

	return state


generate_cellular_automaton = generate_cellular_automaton_1d


def _parse_life_rule (rule: str) -> typing.Tuple[typing.Set[int], typing.Set[int]]:

	"""Parse a Life-like rule string in Birth/Survival notation.

	Parameters:
		rule: Rule string in the form ``"B<digits>/S<digits>"``, e.g.
		      ``"B3/S23"`` for Conway's Life or ``"B368/S245"`` for Morley.

	Returns:
		``(birth_set, survival_set)`` — sets of neighbour counts that
		trigger birth or survival respectively.

	Raises:
		ValueError: If the rule string is not valid Birth/Survival notation.
	"""

	rule = rule.strip().upper()
	parts = rule.split("/")

	if len(parts) != 2:
		raise ValueError(f"Invalid Life rule: {rule!r} — expected 'B.../S...' format")

	birth_part, survival_part = parts

	if not birth_part.startswith("B") or not survival_part.startswith("S"):
		raise ValueError(f"Invalid Life rule: {rule!r} — expected 'B.../S...' format")

	try:
		birth_set: typing.Set[int] = {int(c) for c in birth_part[1:]}
		survival_set: typing.Set[int] = {int(c) for c in survival_part[1:]}
	except ValueError:
		raise ValueError(f"Invalid Life rule: {rule!r} — neighbour counts must be digits 0–8")

	for n in birth_set | survival_set:
		if n > 8:
			raise ValueError(f"Invalid Life rule: {rule!r} — neighbour count {n} exceeds maximum of 8")

	return birth_set, survival_set


def generate_cellular_automaton_2d (
	rows: int,
	cols: int,
	rule: str = "B368/S245",
	generation: int = 0,
	seed: typing.Union[int, typing.List[typing.List[int]]] = 1,
	density: float = 0.5,
) -> typing.List[typing.List[int]]:

	"""Generate a 2D cellular automaton grid using Life-like rules.

	Evolves a 2D grid of cells from an initial state using Birth/Survival
	notation rules.  The resulting grid maps rows to pitches or instruments
	and columns to time steps, producing polyphonic rhythmic patterns.

	The default rule B368/S245 (Morley/"Move") produces chaotic, active
	patterns well-suited to generative music.  B3/S23 is Conway's Life.

	Parameters:
		rows: Number of rows (maps to pitches or instruments).
		cols: Number of columns (maps to time steps / rhythm grid).
		rule: Birth/Survival notation, e.g. ``"B3/S23"`` for Conway's Life,
		      ``"B368/S245"`` for Morley.
		generation: Number of evolution steps to run from the initial seed.
		seed: Initial grid state.  ``1`` places a single live cell at the
		      centre.  Any other ``int`` seeds a :class:`random.Random` and
		      fills cells with probability *density*.  A
		      ``list[list[int]]`` provides an explicit starting grid (must be
		      rows × cols).
		density: Fill probability when *seed* is a random int (0.0–1.0).

	Returns:
		2D grid as a list of lists (rows × cols), each cell 0 or 1.

	Example:
		```python
		grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
			rows=4, cols=16, rule="B3/S23", generation=p.cycle, seed=42
		)
		for row_idx, pitch in enumerate([60, 62, 64, 67]):
			hits = [c for c, v in enumerate(grid[row_idx]) if v]
			p.hit_steps(pitch, hits, velocity=80)
		```
	"""

	birth_set, survival_set = _parse_life_rule(rule)

	# Build initial grid.
	if isinstance(seed, list):
		grid = [[int(bool(seed[r][c])) for c in range(cols)] for r in range(rows)]
	elif seed == 1:
		grid = [[0] * cols for _ in range(rows)]
		grid[rows // 2][cols // 2] = 1
	else:
		rng = random.Random(seed)
		grid = [[1 if rng.random() < density else 0 for _ in range(cols)] for _ in range(rows)]

	# Evolve for the requested number of generations.
	for _ in range(generation):
		new_grid = [[0] * cols for _ in range(rows)]

		for r in range(rows):
			for c in range(cols):
				neighbours = 0

				for dr in (-1, 0, 1):
					for dc in (-1, 0, 1):
						if dr == 0 and dc == 0:
							continue
						neighbours += grid[(r + dr) % rows][(c + dc) % cols]

				alive = grid[r][c]

				if alive:
					new_grid[r][c] = 1 if neighbours in survival_set else 0
				else:
					new_grid[r][c] = 1 if neighbours in birth_set else 0

		grid = new_grid

	return grid
