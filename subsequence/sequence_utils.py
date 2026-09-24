"""Utility functions for generating and transforming step sequences.

Provides algorithms for rhythm generation (Euclidean, Bresenham, van der Corput),
sequence manipulation (rotate, legato, probability gate), and general-purpose
generative helpers (random walk, weighted choice, shuffled choices, scale/clamp).
"""

import collections
import functools
import itertools
import math
import random
import typing

import subsequence.easing
import subsequence.metre
import subsequence.weighted_graph

T = typing.TypeVar("T")

# The public surface, so ``from subsequence.sequence_utils import *`` brings the
# kernels and nothing else — without this it also drags in itertools, math, random
# and typing, which can then shadow the importer's own names.
__all__ = [
	"Sieve", "branch_sequence", "build_metric_weights", "choke", "clamp", "combine_densities",
	"constrained_walk", "cseg", "csim", "de_bruijn", "density_spread", "density_to_steps",
	"density_warp", "displace", "fibonacci", "flip", "fold", "fold_to_midi_range",
	"generate_bresenham_sequence",
	"generate_bresenham_sequence_weighted", "generate_cellular_automaton_1d",
	"generate_cellular_automaton_2d", "generate_euclidean_sequence", "generate_legato_durations",
	"generate_van_der_corput_sequence", "golden_rhythm", "logistic_map", "lorenz_attractor",
	"lsystem_expand", "mask", "morse_code", "offbeatness", "perlin_1d", "perlin_1d_sequence",
	"perlin_2d", "perlin_2d_grid", "pink_noise", "probability_gate", "random_walk",
	"reaction_diffusion_1d", "recaman", "residual_class", "rhythmic_evenness", "rotate",
	"scale_clamp", "self_avoiding_walk", "sequence_to_indices", "shuffled_choices", "sieve",
	"syncopation", "threshold", "thue_morse", "tile", "vl_distance", "warp_stack",
	"weighted_choice",
]


def generate_euclidean_sequence (steps: int, pulses: int) -> typing.List[int]:

	"""
	Generate a Euclidean rhythm using Bjorklund's algorithm.
	"""

	if pulses < 0:
		raise ValueError(f"Pulses must be zero or positive - got {pulses}")

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

	if pulses < 0:
		raise ValueError(f"Pulses must be zero or positive - got {pulses}")

	sequence = [0] * steps
	error = 0

	# The accumulator starts at 0, so each group of steps fills up before it
	# overflows — placing hits LATE in each group BY DESIGN.  This is the
	# documented difference from generate_euclidean_sequence, which rotates
	# its result to start on a hit.
	for i in range(steps):
		error += pulses
		if error >= steps:
			sequence[i] = 1
			error -= steps

	return sequence


def generate_bresenham_sequence_weighted (steps: int, weights: typing.List[float]) -> typing.List[int]:

	"""
	Generate a sequence that distributes weighted indices across steps.

	Every step goes to exactly one index, and each index takes a share of
	the steps in proportion to its weight: ``[0.5, 0.25]`` gives the first
	index two steps for each one of the second's, and so does ``[2, 1]``.
	There are no rests here; to leave steps silent, give the silence an index
	of its own, as ``PatternBuilder.bresenham_poly()`` does.

	Raises ``ValueError`` for a negative weight, or when every weight is zero.
	"""

	if steps <= 0:
		raise ValueError("Steps must be positive")

	if not weights:
		raise ValueError("Weights cannot be empty")

	if any(weight < 0 for weight in weights):
		raise ValueError(f"Weights cannot be negative - got {weights}")

	# Each chosen index pays back one whole step, which divides the steps in
	# proportion only when the weights add up to 1.  Otherwise every index
	# drifts by the same amount each step: above 1 a light weight fell
	# further behind every step and never played, and below 1 the shares
	# flattened towards equal (#3450).  fsum() is correctly rounded on every
	# Python, and a total within rounding of 1 is left alone: on 3.10 the rest
	# voice bresenham_poly() adds can leave 0.9999999999999999, and dividing
	# by that would change 540 typed splits' patterns.
	total = math.fsum(weights)

	if total <= 0:
		raise ValueError("Weights cannot all be zero")

	if not math.isclose(total, 1.0):
		weights = [weight / total for weight in weights]

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

	# base 1 never shrinks k (infinite loop) and base 0 divides by zero.
	if base < 2:
		raise ValueError(f"van der Corput base must be at least 2 - got {base}")

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


def rotate (indices: typing.List[int], shift: int, length: int) -> typing.List[int]:

	"""Circularly rotate step indices by the specified amount, wrapping at *length*."""

	return [(i + shift) % length for i in indices]


def displace (sequence: typing.List[T], amount: int) -> typing.List[T]:

	"""Phase-shift a per-step pattern by a whole number of steps, wrapping.

	Moves every element of ``sequence`` along by ``amount`` positions and wraps
	the steps that fall off one end back round to the other - the classic rhythm
	*necklace* rotation (metric displacement).  A **positive** ``amount`` pushes
	the pattern **later** (to the right): the hit at step 0 in ``[1, 0, 0, 0]``
	lands on step 1.  A negative ``amount`` pulls it earlier.  ``amount`` is taken
	modulo the length, so a whole revolution (or zero) returns the pattern
	unchanged and an over-length shift simply wraps.

	Works on any per-step data - a 0/1 rhythm, a density profile, a velocity or
	note list - since it only reorders the existing values.  This is a different
	operation from :func:`rotate`, which adds ``shift`` to the integer *values*
	of a step-index list; ``displace`` moves the *positions* within a value list.

	Parameters:
		sequence: The per-step pattern to phase-shift.
		amount: Steps to move later (positive) or earlier (negative); reduced
			modulo ``len(sequence)``.

	Returns:
		A new list the same length as ``sequence`` (the input is never mutated),
		or ``[]`` when ``sequence`` is empty.

	Example:
		```python
		# Push a Euclidean kick one step later in the bar.
		kick = subsequence.sequence_utils.generate_euclidean_sequence(8, 3)
		delayed = subsequence.sequence_utils.displace(kick, 1)
		steps = subsequence.sequence_utils.sequence_to_indices(delayed)
		```
	"""

	if not sequence:
		return []

	k = amount % len(sequence)
	return sequence[-k:] + sequence[:-k]


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


def tile (sequence: typing.List[T], length: int) -> typing.List[T]:

	"""Cycle a sequence to an exact length.

	Repeats ``sequence`` end-to-end and truncates so the result is exactly
	``length`` items long - ``tile([1, 0, 0], 8)`` gives ``[1, 0, 0, 1, 0, 0, 1,
	0]``.  Reach for it when the target length is not a whole multiple of the
	pattern; for an exact multiple, plain ``[1, 0, 0] * 3`` reads more clearly.

	Works on any per-step data - a rhythm, a density profile, notes, velocities.

	Parameters:
		sequence: The pattern to repeat.  Must be non-empty when ``length > 0``.
		length: The exact length of the result.

	Returns:
		A new list of exactly ``length`` items, or ``[]`` when ``length <= 0``.

	Raises:
		ValueError: If ``sequence`` is empty and ``length > 0`` - there is
			nothing to cycle.

	Example:
		```python
		# Stretch a three-step kick cell across a 16-step bar.
		bar = subsequence.sequence_utils.tile([1, 0, 0], 16)
		```
	"""

	if length <= 0:
		return []

	if not sequence:
		raise ValueError("cannot tile an empty sequence")

	return [sequence[i % len(sequence)] for i in range(length)]


def _select_mask (
	sequence: typing.List[T],
	against: typing.Optional[typing.Sequence[typing.Any]],
	steps: typing.Optional[typing.Iterable[int]],
	off: typing.Any,
	keep_active: bool,
) -> typing.List[T]:

	"""Gate ``sequence`` against an active selector (the shared mask/choke core).

	Exactly one of ``against`` (a parallel part, active where ``against[i]`` is
	truthy) or ``steps`` (a collection of step indices, active at those positions)
	must be given.  With ``keep_active`` True each step is kept where the selector
	is active and set to ``off`` elsewhere; with False the sense is inverted.  An
	``against`` part shorter than ``sequence`` repeats its last value; an empty one
	is inactive everywhere; indices in ``steps`` outside the sequence are ignored.
	"""

	if (against is None) == (steps is None):
		raise ValueError("pass exactly one of against= or steps=")

	if against is not None:
		active = (
			[bool(against[i]) if i < len(against) else bool(against[-1]) for i in range(len(sequence))]
			if against else [False] * len(sequence)
		)
	else:
		index_set = set(steps if steps is not None else [])
		active = [i in index_set for i in range(len(sequence))]

	return [value if (flag == keep_active) else off for value, flag in zip(sequence, active)]


def mask (
	sequence: typing.List[T],
	against: typing.Optional[typing.Sequence[typing.Any]] = None,
	steps: typing.Optional[typing.Iterable[int]] = None,
	zero: typing.Any = 0,
) -> typing.List[T]:

	"""Keep the steps where a selector is active, zeroing the rest.

	Gates ``sequence`` against a selector, keeping ``sequence[i]`` where the
	selector is **active** and replacing every other step with ``zero``.  Give the
	selector as **exactly one** of:

		- ``against`` - a parallel part, active where ``against[i]`` is truthy
			(non-zero).  Shorter than ``sequence`` it repeats its last value; an
			empty one is inactive everywhere.
		- ``steps`` - a collection of step indices, active at exactly those
			positions.  Indices outside the sequence are ignored.

	Works on any per-step data - densities, 0/1 gates, notes, velocities - since
	the kept steps keep their value.  Off steps take ``zero`` (default ``0``); pass
	``zero=0.0`` to keep a float density profile float.

	Parameters:
		sequence: The per-step data to gate.
		against: A parallel part, active where truthy.  Mutually exclusive with
			``steps``.
		steps: Step indices at which the selector is active.  Mutually exclusive
			with ``against``.
		zero: The value written to inactive steps (default ``0``).

	Returns:
		A new list the length of ``sequence``.

	Raises:
		ValueError: If neither or both of ``against`` and ``steps`` are given.

	Example:
		```python
		# Keep the open hat only on the backbeat accents.
		accent = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]
		open_hat = subsequence.sequence_utils.mask(open_hat_density, against=accent)

		# Or keep only the downbeats, by step index.
		downs = subsequence.sequence_utils.mask(open_hat_density, steps=[0, 4, 8, 12])
		```
	"""

	return _select_mask(sequence, against, steps, zero, keep_active=True)


def choke (
	sequence: typing.List[T],
	against: typing.Optional[typing.Sequence[typing.Any]] = None,
	steps: typing.Optional[typing.Iterable[int]] = None,
	floor: typing.Any = 0,
) -> typing.List[T]:

	"""Suppress the steps where a selector is active, keeping the rest.

	The complement of :func:`mask`: replaces ``sequence[i]`` with ``floor`` where
	the selector is **active**, and keeps it everywhere else.  This is the classic
	drum *choke* - one voice silences another on the steps it sounds.  Give the
	selector as **exactly one** of ``against`` (a parallel part, active where
	truthy) or ``steps`` (a collection of active step indices), with the same
	repeat-last / ignore-out-of-range / empty rules as :func:`mask`.

	``choke(seq, against=other)`` is the same as masking by the complement of
	``other``.

	Parameters:
		sequence: The per-step data to gate.
		against: A parallel part; steps are suppressed where it is truthy.
			Mutually exclusive with ``steps``.
		steps: Step indices to suppress.  Mutually exclusive with ``against``.
		floor: The value written to suppressed steps (default ``0``).

	Returns:
		A new list the length of ``sequence``.

	Raises:
		ValueError: If neither or both of ``against`` and ``steps`` are given.

	Example:
		```python
		# Closed hat chokes the open hat wherever the closed hat sounds.
		open_hat = subsequence.sequence_utils.choke(open_hat_density, against=closed_hat_density)

		# Drum 2 ducks out on the steps drum 1 already fired.
		drum_2 = subsequence.sequence_utils.choke(drum_2_density, steps=fired_steps)
		```
	"""

	return _select_mask(sequence, against, steps, floor, keep_active=False)


def weighted_choice (options: typing.List[typing.Tuple[T, float]], rng: random.Random) -> T:

	"""Pick one item from a list of (value, weight) pairs.

	Weights are relative - they don't need to sum to 1.0. Higher weight means
	higher probability of selection.

	Parameters:
		options: List of ``(value, weight)`` tuples
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

	The no-immediate-repeat guarantee assumes the pool values are distinct -
	a pool containing duplicates (e.g. ``[100, 100, 80]``) can still place
	equal values back to back.

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
			uniformly; a list assigns per-step probability.  Steps beyond the
			end of a short list are always kept (probability 1.0).
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


@typing.overload
def density_to_steps (density: float, rng: random.Random, length: int) -> typing.List[int]: ...
@typing.overload
def density_to_steps (density: typing.List[float], rng: random.Random, length: typing.Optional[int] = None) -> typing.List[int]: ...


def density_to_steps (
	density: typing.Union[float, typing.List[float]],
	rng: random.Random,
	length: typing.Optional[int] = None,
) -> typing.List[int]:

	"""Roll each step against its density and return the fired step indices.

	Walks the grid and, for each step, draws a fresh random number and keeps
	that step when the draw falls below the step's density - an independent
	weighted coin per step.  Returns the **list of fired step indices**, ready
	to feed ``p.sequence(steps=...)`` or ``hit_steps`` and per-step
	comprehensions over those indices.  This is the named form of the
	hand-written ``[i for i in range(n) if rng.random() < density[i]]``.

	It is the *stochastic* member of the density-gate family: :func:`threshold`
	is the deterministic gate, :func:`probability_gate` thins an already-binary
	sequence and returns a parallel 0/1 list, and ``density_to_steps`` takes a
	pure density profile (floats in ``[0, 1]``) and emits the sparse set of
	survivors as indices - no ``[1] * n`` base and no :func:`sequence_to_indices`
	bridge needed.

	``density`` may be a per-step list (its length sets the grid) or a single
	float applied uniformly, in which case ``length`` is **required** - a bare
	probability has no grid of its own.  A density at or above ``1.0`` always
	fires; at or below ``0.0`` never fires.  Pass a seeded ``random.Random`` (or
	the pattern's ``p.rng``) for reproducible output.

	Parameters:
		density: A per-step density list (floats in ``[0, 1]``), or a single
			float applied to every step (then ``length`` is required).
		rng: The seeded random generator - pass the pattern's ``p.rng``.
		length: The grid size when ``density`` is a scalar.  Ignored for a list
			density (the list's own length is used).

	Returns:
		The fired step indices in ascending order - possibly empty.  An empty
		result is normal: a sparse profile may fire nothing on a given cycle.

	Raises:
		ValueError: If ``density`` is a scalar and ``length`` is not given -
			there is no grid to roll against.

	Example:
		```python
		# A per-step kick profile rolled into concrete hits.
		profile = [0.9, 0.1, 0.5, 0.1, 0.8, 0.1, 0.4, 0.1]
		steps = subsequence.sequence_utils.density_to_steps(profile, p.rng)
		velocities = [40 + int(profile[i] * 30) for i in steps]
		p.sequence(steps=steps, pitches="kick", velocities=velocities)

		# A uniform 30% across a 16-step bar needs an explicit length.
		ghosts = subsequence.sequence_utils.density_to_steps(0.3, p.rng, length=16)
		```
	"""

	if isinstance(density, list):
		return [i for i in range(len(density)) if rng.random() < density[i]]

	if length is None:
		raise ValueError("density_to_steps needs a length when density is a scalar")

	return [i for i in range(length) if rng.random() < density]


def _density_warp_scalar (p: float, d: float) -> float:

	"""Warp a single probability ``p`` by knob ``d`` (the scalar core).

	Returns ``(p*d) / (p*d + (1-p)*(1-d))`` with hard guards at the edges so the
	warp reaches exact ``0.0`` / ``1.0`` and never divides by zero.
	"""

	if p <= 0.0:
		return 0.0

	if p >= 1.0:
		return 1.0

	if d <= 0.0:
		return 0.0

	if d >= 1.0:
		return 1.0

	pd = p * d
	return pd / (pd + (1.0 - p) * (1.0 - d))


@typing.overload
def density_warp (value: float, amount: float) -> float: ...
@typing.overload
def density_warp (value: typing.List[float], amount: typing.Union[float, typing.List[float]]) -> typing.List[float]: ...
@typing.overload
def density_warp (value: float, amount: typing.List[float]) -> typing.List[float]: ...


def density_warp (
	value: typing.Union[float, typing.List[float]],
	amount: typing.Union[float, typing.List[float]],
) -> typing.Union[float, typing.List[float]]:

	"""Warp a probability/density by a single denser/sparser knob.

	Pushes a probability ``value`` in ``[0, 1]`` toward 1.0 (denser) or toward
	0.0 (sparser) with one knob ``amount`` in ``[0, 1]``.  ``amount = 0.5`` is
	the identity and returns ``value`` unchanged; above 0.5 thickens, below 0.5
	thins.  The output is always in ``[0, 1]``.

	The map is ``W = (value*amount) / (value*amount + (1-value)*(1-amount))`` -
	the logistic of ``logit(value) + logit(amount)``.  Because the log-odds add,
	warps **stack**: two warps equal one whose knobs combine by summing their
	log-odds.  ``amount = 1`` forces a full ``1.0`` and ``amount = 0`` a full
	``0.0`` for any ``value`` strictly between 0 and 1.

	``value`` may be a single float or a list; the return matches that shape.
	``amount`` may likewise be a single float (applied to every element) or a
	per-step list (e.g. a Perlin density field).  The result is a list whenever
	either argument is a list; when both are lists of unequal length the result
	has the length of the longer, the shorter extended by repeating its last
	value.  An empty list yields an empty list.

	Parameters:
		value: A probability/density in ``[0, 1]``, or a list of them.
		amount: The warp knob in ``[0, 1]`` - ``0.5`` is identity, ``>0.5``
			denser, ``<0.5`` sparser.  A float warps every element uniformly;
			a list warps per step.

	Returns:
		A float when both arguments are floats, otherwise a list of floats.

	Example:
		```python
		# A per-step kick profile, thickened by one density knob.
		profile = [0.9, 0.1, 0.5, 0.1, 0.8, 0.1, 0.4, 0.1]
		dense = subsequence.sequence_utils.density_warp(profile, 0.7)
		# dense is a list in [0, 1] - use as per-step probabilities or velocities.
		```
	"""

	if isinstance(value, list):

		if isinstance(amount, list):

			# Both lists: an empty operand yields []; otherwise pad the shorter
			# by repeating its last element (the _expand_sequence_param rule).
			if not value or not amount:
				return []

			n = max(len(value), len(amount))
			vs = value if len(value) == n else value + [value[-1]] * (n - len(value))
			amt = amount if len(amount) == n else amount + [amount[-1]] * (n - len(amount))
			return [_density_warp_scalar(v, a) for v, a in zip(vs, amt)]

		return [_density_warp_scalar(v, amount) for v in value]

	if isinstance(amount, list):
		return [_density_warp_scalar(value, a) for a in amount]

	return _density_warp_scalar(value, amount)


def _sigmoid (x: float) -> float:

	"""Logistic sigmoid, evaluated so ``exp`` only ever sees a non-positive argument.

	Splitting on the sign of ``x`` keeps the exponent ``<= 0`` in both branches,
	so the result saturates gracefully to ``1.0`` / ``0.0`` at large magnitude
	instead of raising ``OverflowError`` or producing ``nan``.
	"""

	if x >= 0.0:
		z = math.exp(-x)
		return 1.0 / (1.0 + z)

	z = math.exp(x)
	return z / (1.0 + z)


def _density_spread_scalar (p: float, amount: float, m: float) -> float:

	"""Contrast a single probability ``p`` about anchor ``m`` by knob ``amount`` (the scalar core).

	Maps ``out = sigmoid(logit(m) + k*(logit(p) - logit(m)))`` with
	``k = amount/(1-amount)``, so ``odds(out) = odds(p)**k * odds(m)**(1-k)``.
	Hard guards keep the result in ``[0, 1]`` and avoid log/exp blow-ups;
	``amount = 0.5`` returns ``p`` exactly (the general path round-trips through
	``log``/``exp`` and would otherwise drift by up to one ULP).
	"""

	if p <= 0.0:
		return 0.0

	if p >= 1.0:
		return 1.0

	if amount <= 0.0:                                           # k = 0 -> collapse onto the anchor
		return m

	if amount >= 1.0:                                          # k -> inf -> push to the nearest rail across m
		if p < m:
			return 0.0
		if p > m:
			return 1.0
		return m

	if amount == 0.5:                                          # k = 1 -> exact identity, no log/exp round-trip
		return p

	k = amount / (1.0 - amount)
	lm = math.log(m / (1.0 - m))
	lp = math.log(p / (1.0 - p))
	return _sigmoid(lm + k * (lp - lm))


@typing.overload
def density_spread (value: float, amount: float, midpoint: float = 0.5) -> float: ...
@typing.overload
def density_spread (value: typing.List[float], amount: typing.Union[float, typing.List[float]], midpoint: float = 0.5) -> typing.List[float]: ...
@typing.overload
def density_spread (value: float, amount: typing.List[float], midpoint: float = 0.5) -> typing.List[float]: ...


def density_spread (
	value: typing.Union[float, typing.List[float]],
	amount: typing.Union[float, typing.List[float]],
	midpoint: float = 0.5,
) -> typing.Union[float, typing.List[float]]:

	"""Expand or contract a probability/density about a fixed anchor.

	Where :func:`density_warp` *shifts* a value denser or sparser, this *scales*
	the spread of values around an anchor ``midpoint`` - the contrast twin of the
	warp.  ``amount = 0.5`` is the identity; above 0.5 **expands** the spread
	(pushes values away from the anchor, toward 0 and 1); below 0.5 **contracts**
	it (pulls values toward the anchor).  A ``value`` equal to ``midpoint`` never
	moves, and the output is always in ``[0, 1]``.

	The map scales each value's log-odds deviation from the anchor by a gain
	``k = amount/(1-amount)``, so the odds compound as
	``odds(out) = odds(value)**k * odds(midpoint)**(1-k)``.  Handy points:
	``amount = 0.75`` triples the spread (``k = 3``), ``0.25`` thirds it
	(``k = 1/3``); ``amount`` and ``1 - amount`` are exact inverses (contract
	then expand-by-complement returns the input).

	The spread is even in log-odds, not in linear distance: it stretches the
	mid-range most and barely moves values already near 0 or 1, and a strong
	expand pins near-rail values onto the rails (the same saturation
	:func:`density_warp` has at ``amount`` near 0 or 1).

	``value`` may be a single float or a list; the return matches that shape.
	``amount`` may likewise be a single float (applied to every element) or a
	per-step list.  The result is a list whenever either is a list; on unequal
	lengths the shorter repeats its last value, and an empty list yields an empty
	list.  ``midpoint`` is a single anchor in the open interval ``(0, 1)``.

	Parameters:
		value: A probability/density in ``[0, 1]``, or a list of them.
		amount: The spread knob in ``[0, 1]`` - ``0.5`` is identity, ``>0.5``
			expands, ``<0.5`` contracts.  A float spreads every element
			uniformly; a list spreads per step.
		midpoint: The fixed anchor in ``(0, 1)`` that the spread pivots around
			(default ``0.5``).  Values stay on their own side of it.

	Returns:
		A float when ``value`` and ``amount`` are both floats, otherwise a list
		of floats.

	Raises:
		ValueError: If ``midpoint`` is not strictly between 0 and 1 (an anchor on
			a rail has no defined log-odds).

	Example:
		```python
		# Sharpen the contrast of a per-step accent profile around 0.5.
		accents = [0.55, 0.3, 0.7, 0.45, 0.8, 0.25, 0.6, 0.4]
		sharp = subsequence.sequence_utils.density_spread(accents, 0.75)
		# values above 0.5 pushed up, below pushed down - same centre, wider spread.
		```
	"""

	if not 0.0 < midpoint < 1.0:
		raise ValueError(f"midpoint must be strictly between 0 and 1, got {midpoint}")

	if isinstance(value, list):

		if isinstance(amount, list):

			# Both lists: an empty operand yields []; otherwise pad the shorter
			# by repeating its last element (the _expand_sequence_param rule).
			if not value or not amount:
				return []

			n = max(len(value), len(amount))
			vs = value if len(value) == n else value + [value[-1]] * (n - len(value))
			amt = amount if len(amount) == n else amount + [amount[-1]] * (n - len(amount))
			return [_density_spread_scalar(v, a, midpoint) for v, a in zip(vs, amt)]

		return [_density_spread_scalar(v, amount, midpoint) for v in value]

	if isinstance(amount, list):
		return [_density_spread_scalar(value, a, midpoint) for a in amount]

	return _density_spread_scalar(value, amount, midpoint)


def _combine_geomean (values: typing.List[float]) -> float:

	"""Geometric mean of ``values`` - the Nth root of their product."""

	return math.prod(values) ** (1.0 / len(values))


_combine_reducers: typing.Dict[str, typing.Callable[[typing.List[float]], float]] = {
	"geomean": _combine_geomean,
	"min":     min,
	"mean":    lambda values: sum(values) / len(values),
	"product": math.prod,
}


def combine_densities (
	layers: typing.List[typing.Union[float, typing.List[float]]],
	strategy: str = "geomean",
) -> typing.Union[float, typing.List[float]]:

	"""Blend several density layers into one consensus density.

	Takes a list of density ``layers`` - each a single value in ``[0, 1]`` or a
	per-step list in ``[0, 1]`` - and reduces them, step by step, to one density
	value or list.  This is the "agree on how busy this bar should be" stage; its
	output is meant to feed the ``amount`` of :func:`density_warp`.

	The ``strategy`` picks the reducer (all preserve ``[0, 1]`` for valid inputs,
	so no clamping is applied):

		- ``"geomean"`` (default) - the geometric mean, ``prod(values) ** (1/N)``.
			A gentle consensus where any near-zero layer pulls the result down.
		- ``"min"`` - the most restrictive layer wins (a strict gate).
		- ``"mean"`` - the plain arithmetic average (a balanced vote).
		- ``"product"`` - multiply them all (stacks toward sparse fast).

	Broadcasting generalises the rule in :func:`density_warp`: if every layer is
	a single value the result is a single value; if any layer is a list the
	result is a list as long as the longest layer, with scalar layers applied to
	every step and shorter lists extended by repeating their last value.  An
	empty list layer yields ``[]``.

	Parameters:
		layers: The density layers to blend.  Each entry is a value in
			``[0, 1]`` or a per-step list of such values.  Must be non-empty.
		strategy: Reducer name - ``"geomean"`` (default), ``"min"``, ``"mean"``,
			or ``"product"``.

	Returns:
		A float when every layer is a float, otherwise a list of floats.

	Raises:
		ValueError: If ``layers`` is empty, or ``strategy`` is unknown.

	Example:
		```python
		# Blend a metric accent curve, an intensity envelope, and a global knob
		# into a consensus, then warp a base probability by it.
		accent = subsequence.sequence_utils.build_metric_weights((4, 4), 16)
		envelope = subsequence.easing.ramp(16, 0.2, 0.9, "ease_in_out")
		consensus = subsequence.sequence_utils.combine_densities(
			[accent, envelope, 0.6], strategy="geomean")
		probs = subsequence.sequence_utils.density_warp(0.5, consensus)
		```
	"""

	if not layers:
		raise ValueError("Layers cannot be empty")

	if strategy not in _combine_reducers:
		available = ", ".join(f'"{k}"' for k in sorted(_combine_reducers))
		raise ValueError(
			f"Unknown combine strategy {strategy!r}. Available strategies: {available}"
		)

	reduce = _combine_reducers[strategy]

	if all(not isinstance(layer, list) for layer in layers):
		return reduce([layer for layer in layers if not isinstance(layer, list)])

	lengths = [len(layer) for layer in layers if isinstance(layer, list)]

	if 0 in lengths:
		return []

	n = max(lengths)
	result: typing.List[float] = []

	for i in range(n):

		step: typing.List[float] = []

		for layer in layers:
			if isinstance(layer, list):
				step.append(layer[i] if i < len(layer) else layer[-1])
			else:
				step.append(layer)

		result.append(reduce(step))

	return result


@typing.overload
def warp_stack (value: float, amounts: typing.List[float]) -> float: ...
@typing.overload
def warp_stack (value: float, amounts: typing.List[typing.Union[float, typing.List[float]]]) -> typing.Union[float, typing.List[float]]: ...
@typing.overload
def warp_stack (value: typing.List[float], amounts: typing.List[typing.Union[float, typing.List[float]]]) -> typing.List[float]: ...


def warp_stack (
	value: typing.Union[float, typing.List[float]],
	amounts: typing.Sequence[typing.Union[float, typing.List[float]]],
) -> typing.Union[float, typing.List[float]]:

	"""Apply several density knobs to ``value`` so they compound.

	Folds :func:`density_warp` over ``amounts``: it starts from ``value`` and
	warps by each knob in turn.  Because :func:`density_warp` adds log-odds,
	stacking knobs equals one warp whose knobs sum in log-odds, so the order of
	``amounts`` does not matter and the neutral knob ``0.5`` is a no-op.

	Each knob may itself be a single value or a per-step list (it inherits
	:func:`density_warp`'s broadcasting), so you can mix a global knob with
	per-step envelopes.  An empty ``amounts`` list returns ``value`` unchanged.

	Stacking saturates fast: every knob above ``0.5`` pushes harder toward
	``1.0`` (and below toward ``0.0``), so a few strong knobs can pin a sequence
	almost fully on or off.  Treat it like gain-staging - prefer a few gentle
	knobs, or blend control layers first with :func:`combine_densities` and apply
	the consensus as one knob.

	Parameters:
		value: A probability/density in ``[0, 1]``, or a list of them.
		amounts: The knobs to compound, each a value in ``[0, 1]`` (``0.5``
			neutral, ``>0.5`` denser, ``<0.5`` sparser) or a per-step list.

	Returns:
		A float when ``value`` and every knob are floats, otherwise a list.

	Example:
		```python
		# Compound a global swell, a humanised drift, and a per-step accent.
		accent = subsequence.easing.ramp(16, 0.4, 0.8, "ease_in")
		probs = subsequence.sequence_utils.warp_stack([0.5] * 16, [0.7, 0.55, accent])
		```
	"""

	result = value

	for amount in amounts:
		result = density_warp(result, amount)

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


@typing.overload
def flip (value: float, low: float = 0.0, high: float = 1.0) -> float: ...
@typing.overload
def flip (value: typing.List[float], low: float = 0.0, high: float = 1.0) -> typing.List[float]: ...


def flip (
	value: typing.Union[float, typing.List[float]],
	low: float = 0.0,
	high: float = 1.0,
) -> typing.Union[float, typing.List[float]]:

	"""Reflect a value within a range - its complement about the mid-point.

	Returns ``low + high - value``, mirroring ``value`` to the opposite side of the
	range ``[low, high]``.  With the default ``[0, 1]`` this is ``1 - value`` - the
	density/probability complement, and a logical NOT for a 0/1 list.  Being
	range-aware it also flips other scales: ``flip(100, 0, 127)`` is ``27``,
	mirroring a velocity within the MIDI range.

	``flip`` is its own inverse and assumes ``value`` lies within ``[low, high]``;
	it does **not** clamp (compose with :func:`clamp` if the input may stray).

	``value`` may be a single float or a list; the return matches that shape.
	``low`` and ``high`` are single scalars applied to every element.  An empty
	list yields an empty list.

	Parameters:
		value: A number to reflect, or a list of them.
		low: The lower bound of the range (default ``0.0``).
		high: The upper bound of the range (default ``1.0``).

	Returns:
		A float when ``value`` is a float, otherwise a list of floats.

	Example:
		```python
		# Turn a kick density into its "everywhere the kick isn't" field.
		gaps = subsequence.sequence_utils.flip(kick_density)

		# Mirror a velocity within the MIDI range.
		soft = subsequence.sequence_utils.flip(100, 0, 127)
		```
	"""

	if isinstance(value, list):
		return [low + high - v for v in value]

	return low + high - value


@typing.overload
def clamp (value: float, low: float = 0.0, high: float = 1.0) -> float: ...
@typing.overload
def clamp (value: typing.List[float], low: float = 0.0, high: float = 1.0) -> typing.List[float]: ...


def clamp (
	value: typing.Union[float, typing.List[float]],
	low: float = 0.0,
	high: float = 1.0,
) -> typing.Union[float, typing.List[float]]:

	"""Bound a value (or list) to the range ``[low, high]``.

	Returns ``max(low, min(high, value))`` element-wise.  This is the plain,
	list-aware clamp - distinct from :func:`scale_clamp`, which *rescales* from one
	range to another before clamping.  Defaults to ``[0, 1]``, the usual
	density range; pass ``low``/``high`` for any other scale.  Assumes
	``low <= high``.

	``value`` may be a single float or a list; the return matches that shape.
	``low`` and ``high`` are single scalars.  An empty list yields an empty list.

	Parameters:
		value: A number to bound, or a list of them.
		low: The lower bound (default ``0.0``).
		high: The upper bound (default ``1.0``).

	Returns:
		A float when ``value`` is a float, otherwise a list of floats.

	Example:
		```python
		# Keep a hand-scaled density field inside [0, 1] after arithmetic.
		safe = subsequence.sequence_utils.clamp([d * 1.4 for d in kick_density])

		# Bound a computed velocity to the MIDI range.
		vel = subsequence.sequence_utils.clamp(raw_velocity, 0, 127)
		```
	"""

	if isinstance(value, list):
		return [max(low, min(high, v)) for v in value]

	return max(low, min(high, value))


def threshold (sequence: typing.List[float], cutoff: float = 0.5) -> typing.List[int]:

	"""Gate a per-step field into a deterministic 0/1 sequence.

	Returns ``1`` where ``sequence[i] > cutoff`` (strict) and ``0`` otherwise - the
	deterministic counterpart to :func:`probability_gate`'s random roll, matching
	the idiom ``cutoff < x``.  Pair with :func:`sequence_to_indices` to turn the
	result into the firing step indices.

	This is a sequence operation: it takes a list and returns a list of ints.  An
	empty sequence yields an empty list.

	Parameters:
		sequence: A per-step field (e.g. a density profile in ``[0, 1]``).
		cutoff: The exclusive threshold; steps strictly above it fire (default
			``0.5``).

	Returns:
		A list of ``0`` / ``1`` ints the length of ``sequence``.

	Example:
		```python
		# Place closed-hat hits wherever the density clears the half-way line.
		gate = subsequence.sequence_utils.threshold(hh_closed_density, 0.5)
		steps = subsequence.sequence_utils.sequence_to_indices(gate)
		```
	"""

	return [1 if value > cutoff else 0 for value in sequence]


def fold (sequence: typing.Sequence[int], low: int, high: int, mode: str = "wrap") -> typing.List[int]:

	"""Bring out-of-range whole numbers back into a range, keeping their movement.

	Where :func:`clamp` flattens everything beyond the bounds onto the bounds, ``fold``
	keeps travelling - so a line that runs off the top comes back in rather than
	sticking.  That matters for generators whose values grow without limit (Recamán's
	sequence, raw Fibonacci): clamping turns their shape into a held note, folding
	preserves it.  Two ways to come back:

		- ``"wrap"`` - reappear at the opposite end, the octave-style ``%`` most
			musicians expect.  Yields ``[low, high)``: ``high`` itself lands on ``low``.
		- ``"reflect"`` - turn around at the boundary and travel back, so movement
			reverses instead of jumping.  Yields ``[low, high]`` inclusive, and is
			:func:`flip` applied over and over rather than once.

	Note the ranges differ: wrapping treats the bounds as the same point (as octaves
	are), reflecting treats them as walls, so ``high`` is reachable only under
	``"reflect"``.

	Parameters:
		sequence: The whole numbers to bring into range.
		low: Lower bound (always reachable).
		high: Upper bound - reachable under ``"reflect"``, excluded under ``"wrap"``.
		mode: ``"wrap"`` or ``"reflect"`` (default ``"wrap"``).

	Returns:
		A new list the length of ``sequence``.  An empty sequence yields ``[]``.

	Raises:
		ValueError: If ``high`` is not above ``low``, or ``mode`` is unknown.

	Example:
		```python
		# Keep a runaway melodic line inside one octave, bouncing at the edges.
		degrees = subsequence.sequence_utils.recaman(16)
		bounded = subsequence.sequence_utils.fold(degrees, 0, 12, mode="reflect")
		```
	"""

	if high <= low:
		raise ValueError(f"fold() needs a range to fold into - high ({high}) must be above low ({low})")

	if mode not in ("wrap", "reflect"):
		raise ValueError(f'Unknown fold mode {mode!r}. Available modes: "reflect", "wrap"')

	span = high - low

	if mode == "wrap":
		return [low + (value - low) % span for value in sequence]

	# Reflect: a full there-and-back cycle is twice the span, and the second half of
	# each cycle is the first half travelling in reverse.
	period = 2 * span
	folded = []

	for value in sequence:
		offset = (value - low) % period
		folded.append(low + offset if offset <= span else low + period - offset)

	return folded


def fold_to_midi_range (pitch: int, low: int = 0, high: int = 127) -> int:

	"""Bring a pitch inside 0–127 by octaves, keeping its pitch class.

	A generator that computes pitches can run off either end - ``branch_sequence``
	transposing a trunk upward, a chord stacked past the top of the keyboard -
	and a pitch MIDI cannot carry is dropped at every send, logged as a device
	fault (#3004).  Moving it by octaves keeps the note it is and puts it where
	it can sound; the alternative, clamping, turns a melody into a wall at 127.

	A range narrower than an octave cannot always hold a pitch class, so the
	result is clamped as a last resort.
	"""

	folded = int(pitch)

	while folded < low:
		folded += 12

	while folded > high:
		folded -= 12

	return max(low, min(high, folded))


def _noise_hash (*values: int) -> int:

	"""Mix lattice coordinates and a seed into 32 well-spread bits.

	The Perlin functions used ``(a*pos + b*seed + 12345) & 0x7FFFFFFF``, which
	is not a hash - it is a straight line.  Every multiplier was ≡ 1 (mod 4),
	so the bottom two bits of the result were the bottom two bits of the
	input.  ``perlin_2d`` picks its gradient with ``h & 3``, so the whole
	field was decided by ``seed % 4``: four fields in total, and the same
	noise back again every four seeds.  ``perlin_1d`` came out an alternation
	rather than a wander, with a lag-2 autocorrelation of −0.945 at
	half-integer steps (#3011).

	Each value is folded in with a multiply by an odd constant, then the whole
	thing goes through murmur3's finaliser - shift, multiply, xor, twice.  The
	finaliser is the part that earns its keep: a multiply only carries bits
	*upward*, so without it the top bit of an input moves one output bit on
	average instead of sixteen, and the bottom bits stay a copy of the input's.
	Flipping any one input bit now moves about half the output bits.
	"""

	h = 0x9E3779B9

	for value in values:
		h = ((h ^ (value & 0xFFFFFFFF)) * 0x85EBCA6B) & 0xFFFFFFFF

	h ^= h >> 16
	h = (h * 0x85EBCA6B) & 0xFFFFFFFF
	h ^= h >> 13
	h = (h * 0xC2B2AE35) & 0xFFFFFFFF
	h ^= h >> 16

	return h


def perlin_1d (x: float, seed: int = 0) -> float:

	"""Generate smooth 1D noise at position *x*.

	Returns a value in [0.0, 1.0] that varies smoothly as *x* changes.
	Both ends are genuinely reached - the value is exactly 0.5 at every whole
	*x* and swings furthest between them - and the values cluster around the
	middle, so about one in a hundred is above 0.92.  Pick a threshold with
	that in mind: 0.65 fires often, 0.92 rarely.
	Same *x* and *seed* always produce the same output.  Use to drive
	density, velocity, or probability parameters that should wander
	organically over time - the "parameter wandering within boundaries"
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
		# Eight evenly spaced slopes from −1 to +1, the two ends included.
		# A CONTINUOUS gradient — the old `(h / 0x3FFFFFFF) - 1.0` — is why
		# the output never reached its documented ends: 0 and 1 need two
		# adjacent lattice points sloping at exactly +1 and −1, which a
		# continuous draw hits with probability zero, so the real span was
		# [0.22, 0.77] (#3011).  Eight is chosen, not arbitrary: with two
		# slopes the noise saturates and piles 8% of its values into the top
		# tenth, and past sixteen the ends go rare again.  Eight both reaches
		# 0 and 1 and keeps the bell the middle of the range deserves.
		return (_noise_hash(pos, seed) & 7) / 3.5 - 1.0

	fade = subsequence.easing.s_curve(t)

	d0 = _grad(x0) * t
	d1 = _grad(x1) * (t - 1.0)

	value = d0 + fade * (d1 - d0)

	# The raw value spans exactly [−0.5, +0.5] — its ends are reached where
	# adjacent lattice gradients oppose — so this covers a true [0, 1].  The
	# clamp is belt and braces against floating-point drift at the very edge.
	return max(0.0, min(1.0, value + 0.5))


def perlin_2d (x: float, y: float, seed: int = 0) -> float:

	"""Generate smooth 2D noise at position *(x, y)*.

	Returns a value in [0.0, 1.0] that varies smoothly as *x* and *y* change.
	Both ends are genuinely reached, at a cell centre whose four corners all
	slope away from it, and the values cluster around the middle - about one
	in a hundred is above 0.9.
	Same coordinates and *seed* always produce the same output. Use to drive
	correlated parameters that should weave around each other organically over time,
	or for spatialised parameter wandering.

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
		# Note: the smootherstep fade is deliberately duplicated from perlin_1d
		# rather than extracted, to avoid a function call per corner on dense
		# sequences.  The hash is shared, because getting it wrong here is what
		# left this field with four variations in total (#3011).
		h4 = _noise_hash(pos_x, pos_y, seed) & 3
		dx = x - pos_x
		dy = y - pos_y
		if h4 == 0: return  dx + dy
		if h4 == 1: return -dx + dy
		if h4 == 2: return  dx - dy
		return -dx - dy

	fadex = subsequence.easing.s_curve(tx)
	fadey = subsequence.easing.s_curve(ty)

	d00 = _grad(x0, y0)
	d10 = _grad(x1, y0)
	d01 = _grad(x0, y1)
	d11 = _grad(x1, y1)

	# Interpolate along x
	ix0 = d00 + fadex * (d10 - d00)
	ix1 = d01 + fadex * (d11 - d01)

	# Interpolate along y
	value = ix0 + fadey * (ix1 - ix0)

	# The raw value spans exactly [−1, +1] — both ends are reached at a cell
	# centre whose four corner gradients all point away from it — so this
	# covers a true [0, 1].  The clamp guards floating-point drift at the edge.
	return max(0.0, min(1.0, (value + 1.0) / 2.0))


def perlin_1d_sequence (start: float, spacing: float, count: int, seed: int = 0) -> typing.List[float]:

	"""Generate a sequence of smooth 1D noise values.

	Equivalent to calling :func:`perlin_1d` *count* times at evenly-spaced
	positions, but expressed as a single call.  Every value is in [0.0, 1.0].

	Parameters:
		start: Position of the first sample in the noise field.
			Typically ``p.bar * p.grid * scale`` to anchor the sequence
			to an absolute position in the piece.
		spacing: Distance between consecutive samples.  Matches the
			``scale`` factor used in single calls - e.g. ``0.1`` gives
			the same per-sample change as ``perlin_1d(i * 0.1, seed)``.
		count: Number of values to return.
		seed: Noise field seed.  Same seed as a matching :func:`perlin_1d`
			call produces identical values at the same positions.

	Example:
		```python
		# 16 smoothly-varying velocities for hi-hat ghost notes
		noise = subsequence.sequence_utils.perlin_1d_sequence(
		    start   = p.bar * p.grid * 0.1,
		    spacing = 0.1,
		    count   = p.grid,
		    seed    = 10
		)
		hat_velocities = [
		    int(subsequence.easing.map_value(n, out_min=50, out_max=75, shape="ease_in"))
		    for n in noise
		]
		```
	"""

	return [perlin_1d(start + i * spacing, seed) for i in range(count)]


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
		# 4x4 noise grid - rows are bars, columns are steps
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

	Complements :func:`perlin_1d` - use Perlin for smooth organic
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
		        p.hit_steps("snare_2", [i], velocity=round(30 + 50 * v))
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

	Pink noise has equal energy per octave - it contains both slow drift
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
		        p.hit_steps("hi_hat_closed", [i], velocity=round(40 + 50 * level))
		```
	"""

	if steps <= 0:
		return []

	if sources <= 0:
		raise ValueError(f"pink_noise() needs at least one random source to sum - got sources={sources}")

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


def _lsystem_expand_reporting (
	axiom: str,
	rules: typing.Dict[str, typing.Union[str, typing.List[typing.Tuple[str, float]]]],
	generations: int,
	rng: typing.Optional[random.Random] = None,
	max_length: typing.Optional[int] = None,
) -> typing.Tuple[str, int]:

	"""Expand an L-system string by applying production rules.

	An L-system rewrites every symbol in the current string simultaneously,
	each generation replacing symbols according to ``rules``.  After enough
	generations the string exhibits self-similarity: its large-scale structure
	mirrors its small-scale structure - the same property found in natural
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
			Stochastic: ``{"A": [("AB", 3), ("BA", 1)]}`` - weights are
			relative and do not need to sum to 1.
		generations: Number of rewriting iterations.
		rng: Random number generator.  Required when any rule is stochastic;
			ignored for fully deterministic rule sets.
		max_length: Stop early rather than produce a string longer than this.
			The result is then the last *whole* generation that fits, which is
			still a well-formed L-system string - a truncated one would not be.
			None (the default) expands exactly ``generations`` times.

	Returns:
		The expanded string, and how many generations were actually applied -
		fewer than asked when ``max_length`` stopped it.  A caller that wants
		to say so needs to be told; deriving it from the length would mean
		knowing the rules' growth rate, which stochastic rules do not have.

	Raises:
		ValueError: If stochastic rules are present but ``rng`` is ``None``.

	Example:
		```python
		# Fibonacci-word rhythm - evenly spaced hits that never quite repeat
		expanded = subsequence.sequence_utils.lsystem_expand(
		    axiom="A", rules={"A": "AB", "B": "A"}, generations=6
		)
		# expanded is "ABAABABAABAABABAABABA" (length 21, the gen-6 Fibonacci word)

		# Stochastic - different output each bar
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
	done = 0

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

		expanded = "".join(parts)

		# Stop before the overshoot rather than after it: with a doubling rule
		# the generation that exceeds the budget is roughly twice it, so
		# keeping the previous whole generation is both smaller and better
		# formed than any truncation of this one.
		if max_length is not None and len(expanded) > max_length:
			return current, done

		current = expanded
		done += 1

	return current, done


def lsystem_expand (
	axiom: str,
	rules: typing.Dict[str, typing.Union[str, typing.List[typing.Tuple[str, float]]]],
	generations: int,
	rng: typing.Optional[random.Random] = None,
	max_length: typing.Optional[int] = None,
) -> str:

	"""Expand an L-system string by applying production rules.

	See :func:`_lsystem_expand_reporting`, which this wraps - identical, but
	returning only the string, which is what a caller usually wants.
	"""

	return _lsystem_expand_reporting(axiom, rules, generations, rng, max_length)[0]


# How many distinct cellular-automaton evolutions each cache keeps.  A piece
# uses a handful — one per CA verb, per size and rule — so this is generous for
# anything written on purpose.  The case it exists for is a fresh seed every
# bar, where each entry is looked up exactly once and never wanted again: the
# caches grew one entry a bar for as long as the process ran, 1,601 entries and
# 179,456 grid cells over a 1,200-bar evening (#3071).
_CA_CACHE_ENTRIES = 64


_CachedState = typing.TypeVar("_CachedState")


class _EvolutionCache (typing.Generic[_CachedState]):

	"""The latest ``(generation, state)`` per configuration, oldest evicted first.

	A plain dict here was a leak rather than a cache whenever the key varied
	per bar.  Reads move an entry to the newest end, so what a piece keeps
	using stays and what it used once goes.
	"""

	def __init__ (self, limit: int = _CA_CACHE_ENTRIES) -> None:

		self._entries: "collections.OrderedDict[typing.Any, typing.Tuple[int, _CachedState]]" = collections.OrderedDict()
		self._limit = limit

	def get (self, key: typing.Any) -> typing.Optional[typing.Tuple[int, _CachedState]]:

		entry = self._entries.get(key)

		if entry is not None:
			self._entries.move_to_end(key)

		return entry

	def put (self, key: typing.Any, value: typing.Tuple[int, _CachedState]) -> None:

		self._entries[key] = value
		self._entries.move_to_end(key)

		while len(self._entries) > self._limit:
			self._entries.popitem(last = False)

	def __len__ (self) -> int:

		return len(self._entries)

	def clear (self) -> None:

		self._entries.clear()


_ca_1d_cache: _EvolutionCache[typing.List[int]] = _EvolutionCache()


def _ca_1d_initial_state (steps: int, seed: int) -> typing.List[int]:

	"""Build the generation-0 row for an elementary CA (``seed=1`` → centre cell)."""

	state = [0] * steps

	if seed == 1:
		state[steps // 2] = 1
	else:
		for i in range(min(steps, seed.bit_length())):
			if seed & (1 << i):
				state[i] = 1

	return state


def _ca_1d_step (state: typing.List[int], rule: int, steps: int) -> typing.List[int]:

	"""Advance an elementary-CA row by one generation (toroidal neighbourhood)."""

	new_state = [0] * steps

	for i in range(steps):
		left = state[(i - 1) % steps]
		center = state[i]
		right = state[(i + 1) % steps]
		neighborhood = (left << 2) | (center << 1) | right
		new_state[i] = (rule >> neighborhood) & 1

	return new_state


def generate_cellular_automaton_1d (steps: int, rule: int = 30, generation: int = 0, seed: int = 1) -> typing.List[int]:

	"""Generate a binary sequence using an elementary cellular automaton.

	Evolves a 1D CA from an initial state for the specified number of
	generations, returning the final state as a binary rhythm.  Each
	generation the pattern evolves - use ``p.cycle`` as the generation
	to get a rhythm that changes every bar.

	Rule 30 produces "structured chaos" - patterns that look random but
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

	# A negative generation is not "before the beginning" — it poisons the
	# cache below for everybody. The cache holds (generation, state) per
	# (steps, rule, seed), and a negative one stores the INITIAL state under a
	# negative number; the next call with generation=0 then finds -3 <= 0,
	# accepts it, and runs range(-3, 0) — three evolution steps, returned as
	# "generation 0". The cache is process-global, so the damage reaches other
	# patterns sharing a rule and seed, and it depends on the order calls
	# happen to be made in. Refuse it where it is written (#3050).
	if generation < 0:
		raise ValueError(
			f"generation must be 0 or more, got {generation}. "
			f"Generation 0 is the initial state; p.cycle counts up from there."
		)

	# Memoise the evolution: the common idiom drives `generation` from `p.cycle`,
	# advancing one generation per bar, so without a cache each bar re-ran every
	# prior generation from scratch (cost growing without bound over a long set).
	# The cache holds the latest (generation, state) per (steps, rule, seed) and
	# advances incrementally; a request for an earlier generation than cached
	# recomputes from the initial state.  Correct because the CA is Markovian —
	# generation N+1 depends only on generation N.
	cache_key = (steps, rule, seed)
	cached = _ca_1d_cache.get(cache_key)

	if cached is not None and cached[0] <= generation:
		# Not copied here: the write below stores a copy, so the cached list is
		# never the one returned.  See the note in the 2D version (#3071).
		current_gen, state = cached[0], cached[1]
	else:
		current_gen, state = 0, _ca_1d_initial_state(steps, seed)

	for _ in range(current_gen, generation):
		state = _ca_1d_step(state, rule, steps)

	_ca_1d_cache.put(cache_key, (generation, list(state)))

	return state


def _parse_life_rule (rule: str) -> typing.Tuple[typing.Set[int], typing.Set[int]]:

	"""Parse a Life-like rule string in Birth/Survival notation.

	Parameters:
		rule: Rule string in the form ``"B<digits>/S<digits>"``, e.g.
		      ``"B3/S23"`` for Conway's Life or ``"B368/S245"`` for Morley.

	Returns:
		``(birth_set, survival_set)`` - sets of neighbour counts that
		trigger birth or survival respectively.

	Raises:
		ValueError: If the rule string is not valid Birth/Survival notation.
	"""

	rule = rule.strip().upper()
	parts = rule.split("/")

	if len(parts) != 2:
		raise ValueError(f"Invalid Life rule: {rule!r} - expected 'B.../S...' format")

	birth_part, survival_part = parts

	if not birth_part.startswith("B") or not survival_part.startswith("S"):
		raise ValueError(f"Invalid Life rule: {rule!r} - expected 'B.../S...' format")

	try:
		birth_set: typing.Set[int] = {int(c) for c in birth_part[1:]}
		survival_set: typing.Set[int] = {int(c) for c in survival_part[1:]}
	except ValueError:
		raise ValueError(f"Invalid Life rule: {rule!r} - neighbour counts must be digits 0–8")

	for n in birth_set | survival_set:
		if n > 8:
			raise ValueError(f"Invalid Life rule: {rule!r} - neighbour count {n} exceeds maximum of 8")

	return birth_set, survival_set


_ca_2d_cache: _EvolutionCache[typing.List[typing.List[int]]] = _EvolutionCache()


def _ca_2d_initial_grid (rows: int, cols: int, seed: int, density: float) -> typing.List[typing.List[int]]:

	"""Build the generation-0 grid for an int-seeded 2D CA."""

	if seed == 1:
		grid = [[0] * cols for _ in range(rows)]
		grid[rows // 2][cols // 2] = 1
		return grid

	rng = random.Random(seed)
	return [[1 if rng.random() < density else 0 for _ in range(cols)] for _ in range(rows)]


def _ca_2d_step (grid: typing.List[typing.List[int]], rows: int, cols: int, birth_set: typing.Set[int], survival_set: typing.Set[int]) -> typing.List[typing.List[int]]:

	"""Advance a Life-like 2D grid by one generation (toroidal Moore neighbourhood)."""

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

	return new_grid


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

	This evolves one start as it is, dead or alive.  ``p.cellular_2d()``
	redraws a random start that dies out or loops.

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

	# A grid with no rows or no columns has no cells to evolve — return the
	# degenerate empty grid, matching the 1D kernel's steps<=0 no-op.
	if rows <= 0 or cols <= 0:
		return [[] for _ in range(max(0, rows))]

	# A negative generation is not "before the beginning" — it poisons the
	# cache below for everybody. The cache holds (generation, state) per
	# (steps, rule, seed), and a negative one stores the INITIAL state under a
	# negative number; the next call with generation=0 then finds -3 <= 0,
	# accepts it, and runs range(-3, 0) — three evolution steps, returned as
	# "generation 0". The cache is process-global, so the damage reaches other
	# patterns sharing a rule and seed, and it depends on the order calls
	# happen to be made in. Refuse it where it is written (#3050).
	if generation < 0:
		raise ValueError(
			f"generation must be 0 or more, got {generation}. "
			f"Generation 0 is the initial state; p.cycle counts up from there."
		)

	birth_set, survival_set = _parse_life_rule(rule)

	# Memoise the evolution incrementally, like the 1D version, so a
	# `generation`-per-bar idiom doesn't re-run every prior generation each call.
	#
	# An explicit starting grid is keyed by its CONTENTS.  It used to be left
	# out of the cache for want of a hashable key, and so replayed every
	# generation on every rebuild: a 4x16 grid cost 96 ms at generation 4,000,
	# and across a 400-bar set an 8x32 one spent 7.6 seconds on the event loop
	# against 39 ms for the same thing cached — all of it between pulses, where
	# a pulse at 120 BPM is 20.8 ms (#3071).
	if isinstance(seed, list):
		grid = [[int(bool(seed[r][c])) for c in range(cols)] for r in range(rows)]
		cache_key: typing.Tuple[typing.Any, ...] = (
			rows, cols, rule, tuple(tuple(row) for row in grid), density,
		)
	else:
		grid = []
		cache_key = (rows, cols, rule, seed, density)

	cached = _ca_2d_cache.get(cache_key)

	if cached is not None and cached[0] <= generation:
		# Not copied here.  What is stored below is already a copy, so the
		# entry the cache holds is never the object handed back, and a caller
		# is free to mutate what it is given.  Copying on the way in as well
		# was a second copy of every grid on every cache hit, guarding nothing
		# the write does not — found by a break that failed no test (#3071).
		current_gen, grid = cached[0], cached[1]
	elif isinstance(seed, list):
		current_gen = 0		# grid already holds the starting state
	else:
		current_gen, grid = 0, _ca_2d_initial_grid(rows, cols, seed, density)

	for _ in range(current_gen, generation):
		grid = _ca_2d_step(grid, rows, cols, birth_set, survival_set)

	_ca_2d_cache.put(cache_key, (generation, [row[:] for row in grid]))

	return grid


# The latest (grid, the grid before it, how many fresh grids have been drawn)
# per configuration, for _ca_2d_redrawing().
_ca_2d_redraw_cache: _EvolutionCache[typing.Tuple[typing.List[typing.List[int]], typing.Optional[typing.List[typing.List[int]]], int]] = _EvolutionCache()


def _ca_2d_redraw_seed (seed: int, draws: int) -> int:

	"""The seed of the *draws*-th fresh grid after *seed*'s own: the same on every run, and never 1."""

	return random.Random(f"{seed}:{draws}").randint(2, 2_147_483_646)


def _ca_2d_redrawing (
	rows: int,
	cols: int,
	rule: str,
	generation: int,
	seed: int,
	density: float,
) -> typing.List[typing.List[int]]:

	"""A random-start 2D automaton, redrawn whenever it dies out or settles into a one- or two-bar loop.

	Generation *generation* of the automaton begun from *seed*, except that a
	generation which comes out empty, or the same as the one before it or the
	one before that, is replaced by a fresh grid drawn at *density*.  Those
	grids come from *seed* in a fixed order, so a seeded piece plays the same
	on every run.

	Measured before this existed, a random 4x16 grid drawn once and left to
	evolve under the default rule died out 52 times in 100, and every one of
	them died or looped, at a median of bar 42 (#3072, #3498).
	"""

	if rows <= 0 or cols <= 0:
		return [[] for _ in range(max(0, rows))]

	if generation < 0:
		raise ValueError(
			f"generation must be 0 or more, got {generation}. "
			f"Generation 0 is the initial state; p.cycle counts up from there."
		)

	birth_set, survival_set = _parse_life_rule(rule)
	cache_key = (rows, cols, rule, seed, density)
	cached = _ca_2d_redraw_cache.get(cache_key)

	before: typing.Optional[typing.List[typing.List[int]]]

	if cached is not None and cached[0] <= generation:
		current_gen, (grid, before, draws) = cached
	else:
		current_gen, grid, before, draws = 0, _ca_2d_initial_grid(rows, cols, seed, density), None, 0

	for _ in range(current_gen, generation):
		after = _ca_2d_step(grid, rows, cols, birth_set, survival_set)

		if not any(any(row) for row in after) or after == grid or after == before:
			draws += 1
			grid, before = _ca_2d_initial_grid(rows, cols, _ca_2d_redraw_seed(seed, draws), density), None
		else:
			grid, before = after, grid

	# Copies, so the entry the cache holds is never the object handed back.
	_ca_2d_redraw_cache.put(cache_key, (generation, (
		[row[:] for row in grid],
		None if before is None else [row[:] for row in before],
		draws,
	)))

	return grid


def thue_morse (n: int, offset: int = 0) -> typing.List[int]:

	"""
	Generate the Thue-Morse sequence.

	The Thue-Morse sequence is an infinite aperiodic binary sequence defined
	by ``t(i) = popcount(i) mod 2`` - the parity of the number of 1-bits in
	``i``.  It is perfectly balanced (equal density of 0s and 1s over any
	power-of-two window) and overlap-free: no subsequence occurs three times
	consecutively.  It is self-similar but never strictly periodic, making it
	useful for rhythmic patterns that feel structured yet avoid monotony.

	Parameters:
		n: Number of values to generate.
		offset: How far into the sequence to start.  Default 0, its start.

	Returns:
		Binary list of length ``n`` (0s and 1s).

	Raises:
		ValueError: If ``offset`` is negative.

	Example:
		```python
		# 16-step Thue-Morse rhythm - first 8 values: 0 1 1 0 1 0 0 1
		seq = subsequence.sequence_utils.thue_morse(16)

		# The next 16, which are the first 16 with every value flipped
		seq = subsequence.sequence_utils.thue_morse(16, offset=16)
		```
	"""

	if offset < 0:
		raise ValueError(f"thue_morse offset must be 0 or more, not {offset}")

	if n <= 0:
		return []

	return [bin(i).count("1") % 2 for i in range(offset, offset + n)]


_MORSE_CODE = {
	"a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.",
	"g": "--.", "h": "....", "i": "..", "j": ".---", "k": "-.-", "l": ".-..",
	"m": "--", "n": "-.", "o": "---", "p": ".--.", "q": "--.-", "r": ".-.",
	"s": "...", "t": "-", "u": "..-", "v": "...-", "w": ".--", "x": "-..-",
	"y": "-.--", "z": "--..",
	"0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
	"5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
	".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
	"/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
	";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
	'"': ".-..-.", "$": "...-..-", "@": ".--.-.",
}


def morse_code (
	text: str,
	dot: float = 0.25,
	dash: float = 0.75,
	symbol_gap: float = 0.25,
	letter_gap: float = 0.75,
	word_gap: float = 1.75,
) -> typing.List[float]:

	"""
	Translate text into an International Morse Code rhythm.

	Encodes ``text`` as Morse and lays it out as a per-step duration list - the
	same shape as :func:`generate_legato_durations`, where ``0.0`` marks a rest.
	Each dot becomes a note of length ``dot`` and each dash a note of length
	``dash``; the gaps between elements, characters and words are spans of rests.

	The ``dot`` is the base time unit: every element and gap occupies
	``round(duration / dot)`` cells, so the genuine 1:3 dot/dash ratio and the
	1/3/7-unit gaps fall straight out of the defaults.  Place the result on a
	grid whose step equals ``dot`` for authentic timing - a dash then sustains
	across its three cells.

	Pair it with :func:`sequence_to_indices` to get the note positions, then read
	the matching durations from the list.  (Not to be confused with
	:func:`thue_morse`, the unrelated Thue-Morse mathematical sequence.)

	The full International Morse alphabet is supported: A-Z, 0-9 and the standard
	punctuation.  Input is normalised first - folded to one case (Morse is
	caseless), runs of whitespace collapsed to a single word gap and trimmed from
	the ends, and any unencodable character dropped - so arbitrary text is safe.

	Parameters:
		text: The message to encode.
		dot: Note length of a dot, and the base time unit (default ``0.25``).
		dash: Note length of a dash (default ``0.75`` - three units).
		symbol_gap: Rest between elements within a character (default ``0.25``).
		letter_gap: Rest between characters (default ``0.75`` - three units).
		word_gap: Rest between words (default ``1.75`` - seven units).

	Returns:
		A per-step duration list with ``0.0`` for rests, or ``[]`` when the text
		has no encodable characters.

	Raises:
		ValueError: If ``dot`` is not positive - it is the base time unit.

	Example:
		```python
		# "sos" -> the canonical  ...---...  rhythm.
		rhythm = subsequence.sequence_utils.morse_code("sos")
		steps = subsequence.sequence_utils.sequence_to_indices(rhythm)
		durations = [rhythm[s] for s in steps]
		p.sequence(steps=steps, pitches=40, durations=durations, velocities=90)
		```
	"""

	if dot <= 0:
		raise ValueError("morse_code: dot must be positive (it is the base time unit)")

	normalised = " ".join(text.lower().split())
	if not normalised:
		return []

	words: typing.List[typing.List[str]] = []
	for word in normalised.split(" "):
		codes = [_MORSE_CODE[ch] for ch in word if ch in _MORSE_CODE]
		if codes:
			words.append(codes)

	if not words:
		return []

	dash_cells = max(1, round(dash / dot))
	symbol_cells = max(0, round(symbol_gap / dot))
	letter_cells = max(0, round(letter_gap / dot))
	word_cells = max(0, round(word_gap / dot))

	result: typing.List[float] = []

	for w, codes in enumerate(words):
		if w > 0:
			result.extend([0.0] * word_cells)
		for c, code in enumerate(codes):
			if c > 0:
				result.extend([0.0] * letter_cells)
			for e, element in enumerate(code):
				if e > 0:
					result.extend([0.0] * symbol_cells)
				if element == "-":
					result.append(dash)
					# These 0.0 cells are occupied by the dash's sustain, not rests —
					# the duration-at-onset convention, as in generate_legato_durations.
					result.extend([0.0] * (dash_cells - 1))
				else:
					result.append(dot)

	return result


def de_bruijn (k: int, n: int) -> typing.List[int]:

	"""
	Generate a de Bruijn sequence B(k, n).

	A de Bruijn sequence over an alphabet of size ``k`` with window ``n`` is a
	cyclic sequence in which every possible subsequence of length ``n`` appears
	exactly once.  The output length is ``k ** n``.

	Uses Martin's algorithm (Lyndon word decomposition), which produces a
	lexicographically minimal sequence with no external dependencies.

	Parameters:
		k: Alphabet size (number of distinct symbols, e.g. 2 for binary or
		   ``len(pitches)`` for a pitch list).
		n: Window size.  Every ``n``-gram over the ``k`` symbols appears
		   exactly once in the cyclic output.

	Returns:
		List of integers in ``[0, k-1]`` of length ``k ** n``.

	Example:
		```python
		# Map each integer to a pitch index
		indices = subsequence.sequence_utils.de_bruijn(3, 2)  # length 9
		pitches = [60, 62, 64]
		melody = [pitches[i] for i in indices]
		```
	"""

	if k <= 0 or n <= 0:
		return []

	sequence: typing.List[int] = []
	a = [0] * (n + 1)

	def _db (t: int, p: int) -> None:
		if t > n:
			if n % p == 0:
				sequence.extend(a[1:p + 1])
		else:
			a[t] = a[t - p]
			_db(t + 1, p)
			for j in range(a[t - p] + 1, k):
				a[t] = j
				_db(t + 1, t)

	_db(1, 1)
	return sequence


def recaman (count: int, start: int = 0, skip: int = 0) -> typing.List[int]:

	"""Generate Recamán's sequence - a line that never settles and never repeats.

	The rule is simply *step back if you can, otherwise step forward*: at step *n*
	move back by *n* if that lands on a positive number you have not already visited,
	and forward by *n* if it does not.  The steps therefore grow - the gap between
	consecutive values is always exactly *n* - which makes the line lurch further and
	further as it goes.

	Musically the interest is that the back-and-forth splits into **two voices**.  Take
	terms 8 to 17 from the default start: ``12, 21, 11, 22, 10, 23, 9, 24, 8, 25`` - the
	alternate values fall away (12, 11, 10, 9, 8) while the ones between them climb
	(21, 22, 23, 24, 25).  One line of notes, heard as two - the wedge that Baroque solo
	writing uses.  It is at its most characterful over roughly 16 to 32 values; much
	beyond that it spreads out and starts to sound like a random walk.

	The values grow without limit, so they are indices into a pitch space, not pitches.
	Pair with :func:`fold` to bound them, and see :func:`fibonacci` for the counterpart
	that does repeat.

	Parameters:
		count: How many values to return.
		start: The first value.  Anything from 2 upward gives genuinely different
			material, and the higher it is the longer the opening descent (40 opens
			with eight falling steps).  Note ``0`` and ``1`` differ only by
			transposition - they are the same shape.
		skip: Discard this many leading values, to take a window further along the
			sequence.  Later windows sit higher up, so normalise against the window's
			own lowest value rather than assuming it starts near zero.

	Returns:
		A list of ``count`` whole numbers, or ``[]`` when ``count`` is not positive.

	Raises:
		ValueError: If ``skip`` is negative.

	Example:
		```python
		# Sixteen values, then folded into a two-octave space.
		values = subsequence.sequence_utils.recaman(16, start=2)
		bounded = subsequence.sequence_utils.fold(values, 0, 24, mode="reflect")
		```
	"""

	if skip < 0:
		raise ValueError(f"recaman() skip is how many values to discard from the front - it cannot be negative, got {skip}")

	if count <= 0:
		return []

	total = count + skip
	seen = {start}
	sequence = [start]
	current = start

	for n in range(1, total):
		back = current - n
		# The "not already visited" test guards only the backward step; a forward step
		# is taken unconditionally, which is why some values recur (42 arrives twice).
		current = back if (back > 0 and back not in seen) else current + n
		sequence.append(current)
		seen.add(current)

	return sequence[skip:]


def fibonacci (
	count: typing.Optional[int] = None,
	a: int = 1,
	b: int = 1,
	modulus: typing.Optional[int] = None,
) -> typing.List[int]:

	"""Generate Fibonacci numbers, optionally folded into a repeating pitch cycle.

	Each number is the sum of the previous two.  Left unmodulated the values grow
	exponentially and climb out of hearing almost at once - only eleven of the first
	twenty fit inside MIDI's range - so as raw pitch this is a single rising gesture.

	The musical form is ``modulus``.  Taken modulo *m* the sequence repeats, and the
	length it repeats after (its Pisano period) is fixed by *m* alone - so the size of
	the pitch space you fold into *chooses the phrase length for you*:

		- 3 (a triad) - 8 steps
		- 5 (pentatonic) - 20 steps
		- 7 (a diatonic scale) - 16 steps
		- 8 (octatonic) - 12 steps
		- 12 (chromatic) - 24 steps

	This is the counterpart to :func:`recaman`, which never repeats, and is unrelated
	to :func:`golden_rhythm`, which places events in time via the golden ratio.

	Parameters:
		count: How many numbers to generate.  Omit to return exactly one full cycle,
			which requires a ``modulus`` (an unmodulated sequence never repeats).
		a: The first number.  Defaults to 1.
		b: The second number.  Defaults to 1.  ``(2, 1)`` gives the Lucas numbers - a
			genuinely different cycle through the same pool.  Many other pairs are the
			same cycle entered at a different point: ``(1, 3)`` is Lucas one step along.
		modulus: Fold the values into ``[0, modulus)``, making the sequence repeat.

	Returns:
		A list of whole numbers - the full sequence, or ``[]`` when ``count`` is zero
		or negative.

	Raises:
		ValueError: If ``modulus`` is below 1, or if both ``count`` and ``modulus``
			are omitted (nothing then bounds the sequence).

	Example:
		```python
		# One complete cycle over a seven-note scale - 16 steps, chosen by the maths.
		degrees = subsequence.sequence_utils.fibonacci(modulus=7)
		```
	"""

	if modulus is not None and modulus < 1:
		raise ValueError(f"fibonacci() modulus is the size of the space to fold into - it must be at least 1, got {modulus}")

	if count is None and modulus is None:
		raise ValueError("fibonacci() needs a count or a modulus - without a modulus the sequence never repeats, so there is no natural length")

	if count is not None and count <= 0:
		return []

	sequence: typing.List[int] = []

	if modulus is None:
		assert count is not None	# guaranteed: the both-omitted case raised above
		x, y = a, b
		for _ in range(count):
			sequence.append(x)
			x, y = y, x + y
		return sequence

	# The map (x, y) -> (y, x + y) mod m is a bijection on a finite set of pairs, so
	# every orbit is a pure loop.  Stopping when the *starting pair* comes back (rather
	# than the textbook (0, 1)) means custom a/b report their own true cycle, and
	# modulus=1 terminates instead of searching forever for a pair it never reaches.
	start = (a % modulus, b % modulus)
	x, y = start

	while True:
		sequence.append(x)
		x, y = y, (x + y) % modulus

		if count is not None:
			if len(sequence) >= count:
				break
		elif (x, y) == start:
			break

	return sequence


def golden_rhythm (count: int, length: float = 4.0) -> typing.List[float]:

	"""
	Generate beat positions spaced by the golden ratio.

	Uses the golden angle method: ``position_i = frac(i * φ) * length``, where
	``φ = (1 + √5) / 2 ≈ 1.618``.  The result is sorted into ascending order.
	This distributes events with the maximum possible spread - analogous to
	how sunflower seeds are arranged - producing a quasi-random but
	aesthetically pleasing timing distribution that is distinct from both
	even grids (Euclidean) and pure randomness.

	This places events in *time* only; it is unrelated to the Fibonacci integer
	sequence, which :func:`fibonacci` generates as pitch material.

	Parameters:
		count: Number of beat positions to generate.
		length: Total span in beats to fill.  Defaults to 4.0 (one bar of 4/4).

	Returns:
		Sorted list of ``count`` float beat positions in ``[0.0, length)``.

	Example:
		```python
		beats = subsequence.sequence_utils.golden_rhythm(8, length=4.0)
		for beat in beats:
		    p.note(pitch=60, beat=beat, velocity=80, duration=0.2)
		```
	"""

	if count <= 0:
		return []

	phi = (1.0 + math.sqrt(5.0)) / 2.0

	# Take the *fractional* part of i·φ to get a low-discrepancy point in [0, 1),
	# then scale to the span.  Applying ``% length`` directly to ``i·φ`` (φ ≈ 1.618,
	# typically < length) does not equidistribute — it clusters two notes near the
	# start — so the fractional part is what produces the documented sunflower spread.
	positions = sorted(((i * phi) % 1.0) * length for i in range(count))
	return positions


# The longest single Euler step lorenz_attractor takes (M17 of the 2026-09-19 review).
_LORENZ_STEP = 0.01

# How much of the trajectory its range is measured over, in the system's own
# time units from its start (#3472).  Each axis is scaled against that one
# range, whichever stretch is played, so a quiet stretch of the attractor stays
# quiet.  Stretched to fill each call instead, as it was, every bar swept the
# whole pool, and a bar-long stretch from x0 was the same bar whatever x0 was.
# The start's transient is measured on purpose: a system that settles to a point
# (at a low rho) leaves only a dying spiral after any burn-in, and measuring
# that alone would stretch it across the pool.  Sixty units at the
# classic parameters reach within a few per cent of the attractor's full width,
# and the rare excursion beyond it is clamped.
_LORENZ_RANGE_TIME = 60.0

# The finest step the range is measured at.  In the builder dt is bounded at
# 0.001 and the range is measured at the trajectory's own step; only a direct
# call can go finer, and sixty units at a step of 1e-6 would take minutes.
_LORENZ_RANGE_STEP = 0.001

# The latest (point, state) per trajectory, so each bar carries on from where
# the last one stopped instead of integrating from the start again.
_lorenz_cache: _EvolutionCache[typing.Tuple[float, float, float]] = _EvolutionCache()


def _lorenz_step_size (dt: float) -> typing.Tuple[int, float]:

	"""How many Euler steps each point takes, and how long each one is.

	Euler is stable only for short steps: from about 0.025 the classic system
	ran off to infinity and every rebuild raised, silencing the part.  So a
	longer dt is taken as several steps of at most _LORENZ_STEP - dt stays the
	time between points, and anything up to that integrates exactly as before.
	"""

	substeps = max(1, math.ceil(dt / _LORENZ_STEP))

	return substeps, dt / substeps


def _lorenz_ran_off (sigma: float, rho: float, beta: float) -> ValueError:

	return ValueError(
		f"the Lorenz system ran off to infinity with sigma={sigma:g}, rho={rho:g}, beta={beta:g} - "
		"values nearer the classic 10, 28 and 8/3 stay on the attractor"
	)


def _lorenz_states (
	steps: int,
	start: int,
	dt: float,
	sigma: float,
	rho: float,
	beta: float,
	x0: float,
	y0: float,
	z0: float,
) -> typing.List[typing.Tuple[float, float, float]]:

	"""Points ``start`` to ``start + steps - 1`` of the trajectory from (x0, y0, z0), unscaled.

	Point i is the state after i + 1 steps of ``dt``.  The cache holds where the
	last call stopped, so a call starting there or later carries on from it,
	and an earlier start integrates from the beginning again.  Correct because
	the system is deterministic: each point depends only on the one before.
	"""

	substeps, h = _lorenz_step_size(dt)
	key = (dt, sigma, rho, beta, x0, y0, z0)
	cached = _lorenz_cache.get(key)

	if cached is not None and cached[0] <= start:
		done, (x, y, z) = cached
	else:
		done, (x, y, z) = 0, (x0, y0, z0)

	states: typing.List[typing.Tuple[float, float, float]] = []

	while done < start + steps:

		for _ in range(substeps):
			dx = sigma * (y - x) * h
			dy = (x * (rho - z) - y) * h
			dz = (x * y - beta * z) * h
			x += dx
			y += dy
			z += dz

		if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
			raise _lorenz_ran_off(sigma, rho, beta)

		if done >= start:
			states.append((x, y, z))

		done += 1

	_lorenz_cache.put(key, (done, (x, y, z)))

	return states


@functools.lru_cache(maxsize = _CA_CACHE_ENTRIES)
def _lorenz_range (
	dt: float,
	sigma: float,
	rho: float,
	beta: float,
	x0: float,
	y0: float,
	z0: float,
) -> typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float], typing.Tuple[float, float]]:

	"""Each axis's (lowest, highest) over the trajectory's first _LORENZ_RANGE_TIME time units.

	Measured at the trajectory's own step, so for the first sixty units every
	point lies inside it exactly; it runs off to infinity here first if it runs
	off at all, which is why the kernel asks for it before anything else.
	"""

	_, h = _lorenz_step_size(dt)
	h = max(h, _LORENZ_RANGE_STEP)
	x, y, z = x0, y0, z0
	lo_x = lo_y = lo_z = math.inf
	hi_x = hi_y = hi_z = -math.inf

	for _ in range(math.ceil(_LORENZ_RANGE_TIME / h)):
		dx = sigma * (y - x) * h
		dy = (x * (rho - z) - y) * h
		dz = (x * y - beta * z) * h
		x += dx
		y += dy
		z += dz
		if x < lo_x:
			lo_x = x
		if x > hi_x:
			hi_x = x
		if y < lo_y:
			lo_y = y
		if y > hi_y:
			hi_y = y
		if z < lo_z:
			lo_z = z
		if z > hi_z:
			hi_z = z

	# Checked once, at the end: a value that ran off stays infinite or NaN.
	if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
		raise _lorenz_ran_off(sigma, rho, beta)

	return (lo_x, hi_x), (lo_y, hi_y), (lo_z, hi_z)


def _lorenz_scaled (value: float, lo: float, hi: float) -> float:

	"""*value* as a share of [lo, hi], clamped to it - or the middle, when the range has no width."""

	if hi - lo <= 1e-12 * max(1.0, abs(lo), abs(hi)):
		return 0.5

	return min(max((value - lo) / (hi - lo), 0.0), 1.0)


def lorenz_attractor (
	steps: int,
	dt: float = 0.1,
	sigma: float = 10.0,
	rho: float = 28.0,
	beta: float = 8.0 / 3.0,
	x0: float = 0.1,
	y0: float = 0.0,
	z0: float = 0.0,
	start: int = 0,
) -> typing.List[typing.Tuple[float, float, float]]:

	"""
	Integrate the Lorenz attractor and return normalised (x, y, z) tuples.

	The Lorenz system is a set of three coupled differential equations
	originally derived to model atmospheric convection.  Its trajectories
	orbit a butterfly-shaped strange attractor: deterministic yet sensitive to
	initial conditions, never exactly repeating.  The three axes provide
	independent but correlated modulation sources - ideal for simultaneously
	shaping pitch, velocity, and duration from a single generative process.

	Integration uses the Euler method, in steps of at most 0.01: a longer
	``dt`` is the time between points, taken as several short steps so the
	trajectory never runs off to infinity.

	One call is one stretch of one trajectory: ``start`` says how far along it
	begins, so ``start=p.cycle * 16`` carries a 16-point bar on from the last
	and the line keeps moving.  Each axis is scaled to ``[0.0, 1.0]``
	against the range the trajectory covers over its first sixty time units -
	the same for every stretch - so a quiet stretch stays quiet rather than
	being stretched to fill the range, and the rare point beyond it is clamped.

	Parameters:
		steps: Number of points to generate.
		dt: Time along the trajectory between one point and the next.
		    Smaller values move more smoothly, and more slowly.  Default 0.1.
		sigma: Lorenz σ parameter.  Default 10.0.
		rho: Lorenz ρ parameter.  Default 28.0 (classic chaotic regime).
		    Low values settle to a point.
		beta: Lorenz β parameter.  Default 8/3.
		x0: Initial x position.  Small changes diverge over time.
		y0: Initial y position.
		z0: Initial z position.
		start: How many points into the trajectory to begin.  Default 0.

	Returns:
		List of ``(x, y, z)`` tuples, each component in ``[0.0, 1.0]``.

	Raises:
		ValueError: If ``start`` is negative, or the system runs off to
		    infinity (with sigma, rho or beta far from the classic values).

	Example:
		```python
		points = subsequence.sequence_utils.lorenz_attractor(16, start=p.cycle * 16)
		pitches = [60, 62, 64, 65, 67, 69, 71, 72]
		for i, (x, y, z) in enumerate(points):
		    pitch = pitches[min(int(x * len(pitches)), len(pitches) - 1)]
		    vel   = int(40 + y * 87)
		    p.note(pitch=pitch, beat=i * 0.25, velocity=vel, duration=0.05 + z * 0.2)
		```
	"""

	if start < 0:
		raise ValueError(f"lorenz_attractor start must be 0 or more, not {start}")

	if steps <= 0:
		return []

	(lo_x, hi_x), (lo_y, hi_y), (lo_z, hi_z) = _lorenz_range(dt, sigma, rho, beta, x0, y0, z0)

	return [
		(_lorenz_scaled(x, lo_x, hi_x), _lorenz_scaled(y, lo_y, hi_y), _lorenz_scaled(z, lo_z, hi_z))
		for x, y, z in _lorenz_states(steps, start, dt, sigma, rho, beta, x0, y0, z0)
	]


# When a Gray-Scott field holds no pattern (#3464).  A field whose peak is under
# a millionth has died out, and one that varies by less than a hundredth of its
# own peak has evened out.  Normalising either stretched what was left - 1e-40
# of a chemical, or a ripple of 1e-15 - into a bar of hits.  Measured over feed
# 0 to 0.1 by kill 0.03 to 0.08, on rings of 8 to 64 cells, from 100 to 20000
# steps: every field these two lines silence is dead or even by 20000 steps, and
# none of them was on its way to a pattern.  Evenness is relative because a
# fading ripple is not rounding noise: a millionth there too left eleven of them
# playing at 16 cells and 1000 steps, peaks of 0.14 to 0.37 varying by 1e-6 to
# 3e-4.
_DIED_OUT = 1e-6
_EVENED_OUT = 1e-2


def reaction_diffusion_1d (
	width: int,
	steps: int = 1000,
	feed_rate: float = 0.08,
	kill_rate: float = 0.061,
	du: float = 0.16,
	dv: float = 0.08,
) -> typing.List[float]:

	"""
	Simulate a 1D Gray-Scott reaction-diffusion system.

	The Gray-Scott model describes two interacting chemicals U and V
	on a 1D ring.  V is introduced as a small seed in the centre; the
	simulation evolves until a stable spatial pattern forms.  The resulting
	V-concentration profile is returned as a normalised float sequence.  On a
	ring the size of a bar the patterns are spots: runs of cells, each
	weakest at its edges.

	This is fundamentally different from cellular automata: the state is
	continuous, the update rule is a PDE (not a binary function), and the
	patterns are governed by diffusion rates rather than neighbour counts.
	The spatial structure maps naturally to a rhythm grid.

	Only a narrow band of feed and kill rates forms a pattern.  Too much kill
	for the feed and V dies out; too little and it evens out around the whole
	ring.  Either way there is no pattern, and every value returned is 0.0.

	Parameters:
		width: Number of cells (maps to the pattern's step grid).
		steps: Number of simulation iterations.  More steps = more developed
		       pattern.  Default 1000.
		feed_rate: Rate at which U is replenished.  Default 0.08.
		kill_rate: Rate at which V is removed.  Default 0.061.
		du: Diffusion rate for U.  Default 0.16.
		dv: Diffusion rate for V.  Default 0.08.

	Returns:
		List of ``width`` floats in ``[0.0, 1.0]`` representing final V
		concentration, or all 0.0 when it holds no pattern.

	Raises:
		ValueError: If the rates are so far from that band that the
		    simulation blows up.

	Example:
		```python
		# Use as a rhythm grid - threshold to place notes
		conc = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=2000)
		hits = [i for i, v in enumerate(conc) if v > 0.5]
		p.hit_steps("kick", hits, velocity=90)
		```
	"""

	return _reaction_diffusion_reporting(width, steps, feed_rate, kill_rate, du, dv)[0]


def _reaction_diffusion_reporting (
	width: int,
	steps: int,
	feed_rate: float,
	kill_rate: float,
	du: float = 0.16,
	dv: float = 0.08,
) -> typing.Tuple[typing.List[float], typing.Optional[str]]:

	"""Simulate the ring for :func:`reaction_diffusion_1d`, and say why when it holds no pattern.

	Returns the profile and ``None``, or all zeros and what happened to the
	field: ``"died out"`` or ``"evened out"``.  The builder needs the reason
	to say which way the rates were off.
	"""

	if width <= 0:
		return [], None

	u = [1.0] * width
	v = [0.0] * width

	# Seed the centre half (width//4 to 3*width//4) with a small V concentration.
	seed_start = width // 4
	seed_end = 3 * width // 4
	for i in range(seed_start, seed_end):
		v[i] = 0.25

	for _ in range(steps):

		new_u = [0.0] * width
		new_v = [0.0] * width

		for i in range(width):
			lap_u = u[(i - 1) % width] - 2.0 * u[i] + u[(i + 1) % width]
			lap_v = v[(i - 1) % width] - 2.0 * v[i] + v[(i + 1) % width]
			uvv = u[i] * v[i] * v[i]
			new_u[i] = u[i] + du * lap_u - uvv + feed_rate * (1.0 - u[i])
			new_v[i] = v[i] + dv * lap_v + uvv - (feed_rate + kill_rate) * v[i]

		u = new_u
		v = new_v

	# Checked first: min() and max() skip a NaN or return it depending on
	# where it sits, so a blown-up field would otherwise normalise into NaN.
	if not all(math.isfinite(x) for x in v):
		raise ValueError(
			f"the Gray-Scott simulation blew up with feed_rate={feed_rate:g}, kill_rate={kill_rate:g}, "
			f"du={du:g}, dv={dv:g} - values nearer the defaults stay stable"
		)

	lo = min(v)
	hi = max(v)

	if hi < _DIED_OUT:
		return [0.0] * width, "died out"

	if hi - lo < _EVENED_OUT * hi:
		return [0.0] * width, "evened out"

	span = hi - lo
	return [(x - lo) / span for x in v], None


# A step is a step; a leap is the exception that keeps a line from sounding
# like a scale exercise. Eight to one, and not four: the choice is made among
# whatever is REACHABLE, and the note just left is usually the ±1 that is out
# of bounds — so a nominal 4:1 delivered 37% leaps, which is not "occasional".
# At 8:1 it lands near a fifth of the steps, which is.
_WALK_STEP_WEIGHTS: typing.Dict[int, float] = {1: 8.0, 2: 1.0}


def self_avoiding_walk (
	n: int,
	low: int,
	high: int,
	rng: random.Random,
	start: typing.Optional[int] = None,
	heard: typing.Optional[typing.Sequence[int]] = None,
) -> typing.List[int]:

	"""
	Generate a short-memory walk over an integer range.

	Unlike :func:`random_walk`, which can revisit any position at any time,
	this walk remembers roughly the last half-range of values and steps
	somewhere it has not been lately.  Steps are mostly ±1, occasionally ±2,
	so the line moves by step with the odd small leap in it.

	**Short memory, not total recall.**  Avoiding *every* value ever visited
	leaves nothing to choose on a one-dimensional range: after the first step
	one neighbour is always already visited, so every step after it is forced
	and the walk is a deterministic bounce between the ends.  Measured over
	500 seeds, the old version produced exactly **two** distinct melodies for
	any given range and length - the only randomness in it was the direction
	of the first step.  Remembering a window instead keeps what the constraint
	was for (no repeats nearby, step-wise motion) and leaves a real choice at
	every step.

	Measured over 500 seeds, 16 notes across MIDI 60–72: **218** distinct
	melodies, no value returning sooner than three notes later, and about a
	quarter of the steps being leaps of 2.  A range of two or three values
	has little freedom left whatever the rule, and still walks rather than
	repeating.

	Parameters:
		n: Number of values to generate.
		low: Minimum value (inclusive).
		high: Maximum value (inclusive).
		rng: Random number generator instance.
		start: Starting value.  Defaults to the midpoint of ``[low, high]``.
		heard: Values heard just before this walk, oldest first, which it keeps
		       clear of as if it had played them.  Pass the end of one walk, with
		       its last value as *start*, and the next goes on as the same line.

	Returns:
		List of ``n`` integers in ``[low, high]``.

	Example:
		```python
		# Short-memory bassline across a 2-octave range (MIDI 40–64)
		notes = subsequence.sequence_utils.self_avoiding_walk(16, low=40, high=64, rng=p.rng)
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

	# About half the range, so there is always somewhere left to go.
	span = high - low + 1
	remembered = max(2, span // 2)

	recent: typing.Deque[int] = collections.deque((value for value in heard or () if low <= value <= high), maxlen = remembered)

	if not recent or recent[-1] != current:
		recent.append(current)

	result: typing.List[int] = [current]

	def reachable (avoid_recent: bool) -> typing.Tuple[typing.List[int], typing.List[float]]:

		"""In-range neighbours a step or a leap away, with their weights."""

		places: typing.List[int] = []
		weights: typing.List[float] = []

		for delta in (-2, -1, 1, 2):
			where = current + delta

			if not low <= where <= high:
				continue

			if avoid_recent and where in recent:
				continue

			places.append(where)
			weights.append(_WALK_STEP_WEIGHTS[abs(delta)])

		return places, weights

	for _ in range(n - 1):

		places, weights = reachable(avoid_recent = True)

		if not places:

			# Everything within reach was heard lately — which happens at the
			# ends of a short range, where there is simply less room.  Go to
			# whichever was heard LONGEST ago rather than forgetting the
			# window outright: clearing it let a value come back two steps
			# later right at the edges, which is the repetition this is for.
			places, weights = reachable(avoid_recent = False)

			if places:
				heard = list(recent)

				def last_heard (where: int) -> int:
					return heard.index(where) if where in heard else -1

				oldest = min(last_heard(where) for where in places)

				kept = [
					(where, weight)
					for where, weight in zip(places, weights)
					if last_heard(where) == oldest
				]

				places = [where for where, _ in kept]
				weights = [weight for _, weight in kept]

		if not places:
			# The range is a single value; there is nowhere to go.
			result.append(current)
			continue

		current = rng.choices(places, weights = weights)[0]
		recent.append(current)
		result.append(current)

	return result


def _branch_retrograde (seq: typing.List[int], root: int, interval: int) -> typing.List[int]:

	"""Reverse the pitch order (rhythm untouched - callers own timing)."""

	return list(reversed(seq))


def _branch_invert (seq: typing.List[int], root: int, interval: int) -> typing.List[int]:

	"""Mirror each pitch around the root (the sequence's first note)."""

	return [root + (root - p) for p in seq]


def _branch_transpose (seq: typing.List[int], root: int, interval: int) -> typing.List[int]:

	"""Shift all pitches by the interval between the first two notes."""

	return [p + interval for p in seq]


def _branch_rotate (seq: typing.List[int], root: int, interval: int) -> typing.List[int]:

	"""Rotate the pitch order by one position (first note moves to the end)."""

	if not seq:
		return seq

	return seq[1:] + seq[:1]


def _branch_compress (seq: typing.List[int], root: int, interval: int) -> typing.List[int]:

	"""Halve every interval from the root, rounded to the nearest semitone."""

	return [root + round((p - root) * 0.5) for p in seq]


def _branch_expand (seq: typing.List[int], root: int, interval: int) -> typing.List[int]:

	"""Double every interval from the root."""

	return [root + round((p - root) * 2.0) for p in seq]


# Indexed by the tree RNG — the ORDER of this list is part of branch()'s
# deterministic output contract; append new transforms, never reorder.
_BRANCH_TRANSFORMS = [
	_branch_retrograde,
	_branch_invert,
	_branch_transpose,
	_branch_rotate,
	_branch_compress,
	_branch_expand,
]


def branch_sequence (
	pitches: typing.List[int],
	depth: int = 2,
	path: int = 0,
	mutation: float = 0.0,
	rng: typing.Optional[random.Random] = None,
) -> typing.List[int]:

	"""
	Navigate a fractal tree of pitch-sequence transforms and return one variation.

	The ``pitches`` sequence is the trunk.  At each of ``depth`` levels two
	transforms are assigned deterministically (derived from the pitch content
	itself, so the tree is identical for the same trunk regardless of any
	seed), and ``path`` selects left or right per level - ``2 ** depth``
	variations before the index wraps.  The transforms are order and interval
	operations (retrograde, inversion, transposition, rotation, interval
	compression/expansion): deliberately rhythm-free, so the caller owns
	timing.  Feed the result to ``Motif.notes()`` for a storable variation,
	or let ``p.branch()`` place it directly.

	Parameters:
		pitches: The trunk - absolute MIDI pitches.  All variations derive
			from this.
		depth: Branching levels (``2 ** depth`` variations).
		path: Which variation (0-based; wraps modulo ``2 ** depth``).
		mutation: Probability per step of substituting a random trunk pitch
			on top of the deterministic branching.
		rng: Random source for ``mutation`` draws only (the tree itself is
			deterministic).  Unseeded when omitted.

	Returns:
		A pitch list the same length as the trunk.
	"""

	if not pitches:
		raise ValueError("pitches list cannot be empty")

	# Tree RNG derived from the pitch content (never the caller's rng) so the
	# tree structure is always the same for the same trunk.  hash() here is
	# deterministic across runs: PYTHONHASHSEED randomises only str/bytes
	# hashes, never ints or tuples of ints.
	branch_rng = random.Random(hash(tuple(pitches)))

	path_index = path % (2 ** depth)
	sequence = list(pitches)
	root = pitches[0]
	interval = (pitches[1] - pitches[0]) if len(pitches) >= 2 else 0

	for level in range(depth):
		left = _BRANCH_TRANSFORMS[branch_rng.randint(0, len(_BRANCH_TRANSFORMS) - 1)]
		right = _BRANCH_TRANSFORMS[branch_rng.randint(0, len(_BRANCH_TRANSFORMS) - 1)]
		direction = (path_index >> level) & 1
		sequence = left(sequence, root, interval) if direction == 0 else right(sequence, root, interval)

	if mutation > 0.0:

		if rng is None:
			rng = random.Random()

		for i in range(len(sequence)):
			if rng.random() < mutation:
				sequence[i] = rng.choice(pitches)

	# Transposing the trunk runs it off the keyboard — `branch_sequence([78,
	# 40, 69], 2, 1)` reached 154 — and a pitch MIDI cannot carry is dropped at
	# every send.  Folded by octaves, so the variation keeps its shape and
	# still sounds (#3004).
	return [fold_to_midi_range(pitch) for pitch in sequence]


def build_metric_weights (time_signature: typing.Tuple[int, int] = (4, 4), grid: int = 16) -> typing.List[float]:

	"""
	Per-step metric weights for one bar - how "strong" each grid position is.

	In a simple metre, each written unit is a beat.  The downbeat is 1.0, the
	half-bar (even beat counts only) is 0.75, other beats are 0.5, halfway
	between beats is 0.25, and everything finer is 0.125.  That is every ``/4``
	metre, and ``(2, 2)``, which accents its halves.

	With a unit of an eighth or finer, the units group into felt beats.
	Compound metres (``(6, 8)``, ``(9, 8)``, ``(12, 8)``) group in threes, and
	irregular ones in twos with a three at the end, so ``(7, 8)`` is 2+2+3.
	The downbeat is 1.0, each group's start 0.5 (0.75 on the half-bar, as in
	``(12, 8)``), the other units 0.25, and anything finer 0.125.

	Pass a custom weight list instead, wherever a metric table is accepted, for
	a grouping these defaults do not guess (``(7, 8)`` felt as 3+2+2).

	Parameters:
		time_signature: ``(beats, unit)``, such as ``(4, 4)`` or ``(7, 8)``.
		grid: Number of equal steps across the bar.

	Returns:
		``grid`` floats in step order.

	Example:
		```python
		build_metric_weights((4, 4), grid=8)
		# → [1.0, 0.25, 0.5, 0.25, 0.75, 0.25, 0.5, 0.25]
		```
	"""

	if grid < 1:
		raise ValueError(f"grid must be at least 1 - got {grid}")

	beats, _ = subsequence.metre.check(time_signature)
	grouped = subsequence.metre.accent_groups(time_signature) is not None
	starts = subsequence.metre.group_starts(time_signature)
	weights = []

	for i in range(grid):

		numerator = i * beats	# unit position = numerator / grid

		if i == 0:
			weights.append(1.0)
		elif numerator % grid == 0:
			unit = numerator // grid
			if unit not in starts:
				weights.append(0.25)
			elif 2 * unit == beats:
				weights.append(0.75)
			else:
				weights.append(0.5)
		elif not grouped and (2 * numerator) % grid == 0:
			weights.append(0.25)
		else:
			weights.append(0.125)

	return weights


def vl_distance (
	source: typing.Sequence[int],
	target: typing.Sequence[int],
	pitch_classes: bool = True,
) -> int:

	"""Voice-leading distance between two chords (Tymoczko's taxicab metric).

	The smallest total semitone movement that turns *source* into *target*,
	minimised over every way of assigning source notes to target notes.  When
	the chords have different sizes, notes of the smaller chord may be doubled
	(every note of both chords takes part - nothing is dropped).

	Parameters:
		source: Pitches of the first chord.
		target: Pitches of the second chord.
		pitch_classes: When True (default), pitches are reduced mod 12 and each
			voice moves by the shortest path around the pitch-class circle (a
			tritone is 6).  When False, pitches are absolute MIDI notes and
			each voice moves by its literal semitone interval - use this to
			score concrete voicings rather than abstract chords.

	Returns:
		Total semitone movement (an int).

	Example:
		```python
		vl_distance([0, 4, 7], [9, 0, 4])   # C → Am: G moves to A, distance 2
		vl_distance([0, 4, 7], [5, 9, 0])   # C → F: distance 3
		```
	"""

	if not source or not target:
		raise ValueError("vl_distance needs at least one pitch in each chord")

	if pitch_classes:
		left = [pitch % 12 for pitch in source]
		right = [pitch % 12 for pitch in target]
	else:
		left = list(source)
		right = list(target)

	def step (a: int, b: int) -> int:
		if pitch_classes:
			diff = abs(a - b) % 12
			return min(diff, 12 - diff)
		return abs(a - b)

	# Orient so `small` is doubled into `large`: every large note is assigned
	# one small note, and every small note must be used at least once.
	small, large = (left, right) if len(left) <= len(right) else (right, left)

	best: typing.Optional[int] = None

	for assignment in itertools.product(range(len(small)), repeat = len(large)):

		if len(set(assignment)) < len(small):
			continue	# a small-chord note was dropped — not a voice leading

		total = sum(step(small[index], large[position]) for position, index in enumerate(assignment))

		if best is None or total < best:
			best = total

	assert best is not None	# guaranteed: the identity-style assignment always survives
	return best


def _constraint_label (node: typing.Any) -> str:

	"""A readable label for a graph node in constraint error messages."""

	name = getattr(node, "name", None)

	if callable(name):
		return str(name())

	return repr(node)


def constrained_walk (
	graph: "subsequence.weighted_graph.WeightedGraph[T]",
	start: T,
	length: int,
	rng: random.Random,
	pins: typing.Optional[typing.Dict[int, T]] = None,
	end: typing.Optional[T] = None,
	avoid: typing.Optional[typing.Collection[T]] = None,
	weight_modifier: typing.Optional[typing.Callable[[T, T, int], float]] = None,
	before_choice: typing.Optional[typing.Callable[[T], None]] = None,
	after_choice: typing.Optional[typing.Callable[[T], None]] = None,
) -> typing.List[T]:

	"""Walk a weighted graph under constraints - the shared hybrid kernel.

	A backward **feasibility** pass (boolean reachability of every pin, so
	unsatisfiability is known before a note is emitted) followed by a forward
	walk through the graph's **real, possibly history-dependent** weights
	masked to surviving candidates.  This guarantees *satisfaction*, not an
	exact conditional distribution - history-dependent weighting (NIR,
	key pull, diversity) keeps its character rather than being flattened.

	Positions are **1-based** (the musician count); position 1 is *start*,
	which is fixed - pins may name it only redundantly.  ``avoid`` applies
	to the chosen positions (2..length); the start is exempt.

	With no constraints, the walk consumes the RNG exactly as repeated
	``graph.choose_next()`` calls would (one draw per step, same candidate
	order), so an unconstrained walk reproduces the unconstrained engine.

	Parameters:
		graph: The transition graph.
		start: The node at position 1.
		length: Total walk length, including *start*.
		rng: Random stream for the weighted draws.
		pins: ``{position: node}`` - the node that MUST sound at a 1-based
			position.
		end: The node at the final position - sugar for ``pins[length]``.
		avoid: Nodes excluded from every chosen position.  Naming a node
			the graph does not contain is allowed (trivially satisfied).
		weight_modifier: ``fn(source, target, weight) -> float`` - the
			engine's soft weighting, applied inside the feasible mask.  If
			it suppresses every feasible candidate at some step (all
			modifiers <= 0), the step falls back to the unmodified weights
			(stall detection) - satisfaction beats character.
		before_choice: Called with the source node before each draw - the
			seam for history bookkeeping (append the source to history, as
			the live engine's ``step()`` does, so *weight_modifier* sees
			the same context it would live).
		after_choice: Called with each chosen node after its draw.

	Returns:
		The walked nodes, ``[start, ...]``, exactly *length* long.

	Raises:
		ValueError: If the constraints are contradictory or unsatisfiable -
			before any RNG draw, naming the failing position.
	"""

	if length < 1:
		raise ValueError(f"a walk needs at least one position, got length={length}")

	pins = dict(pins) if pins else {}

	if end is not None:
		if length in pins and pins[length] != end:
			raise ValueError(
				f"end={_constraint_label(end)} conflicts with pins[{length}]="
				f"{_constraint_label(pins[length])} - they name the same position"
			)
		pins[length] = end

	for position in pins:
		if not 1 <= position <= length:
			raise ValueError(f"pin position {position} is outside the walk (1–{length})")

	avoid_set = set(avoid) if avoid else set()

	for position, node in pins.items():
		if node in avoid_set:
			raise ValueError(
				f"pins[{position}]={_constraint_label(node)} is also in avoid - "
				"a chord cannot be both required and forbidden"
			)

	if 1 in pins and pins[1] != start:
		raise ValueError(
			f"pins[1]={_constraint_label(pins[1])} conflicts with the walk's start "
			f"({_constraint_label(start)}) - position 1 is where the walk begins"
		)

	all_nodes = graph.nodes()

	for position, node in pins.items():
		if node not in all_nodes and node != start:
			raise ValueError(
				f"pins[{position}]={_constraint_label(node)} is not in this graph's "
				"vocabulary - it can never sound"
			)

	if length == 1:
		return [start]

	# Backward feasibility: ok[i] = nodes allowed at position i from which a
	# valid completion exists.  Position 1 is the fixed start.
	def allowed (position: int) -> typing.List[T]:
		if position in pins:
			return [pins[position]]
		return [node for node in all_nodes if node not in avoid_set]

	ok: typing.Dict[int, typing.Set[T]] = {length: set(allowed(length))}

	if not ok[length]:
		raise ValueError(f"no chord can satisfy the constraints at position {length}")

	for position in range(length - 1, 1, -1):
		ok[position] = {
			node for node in allowed(position)
			if any(target in ok[position + 1] for target, _ in graph.get_transitions(node))
		}
		if not ok[position]:
			raise ValueError(
				f"no chord can satisfy the constraints at position {position} - "
				"there is no way through to the pins after it"
			)

	if not any(target in ok[2] for target, _ in graph.get_transitions(start)):
		raise ValueError(
			f"no path from {_constraint_label(start)} satisfies the constraints "
			f"(pins at {sorted(pins)}, {len(avoid_set)} avoided) within {length} positions"
		)

	# Forward walk: real weights, masked to the feasible sets.
	walk: typing.List[T] = [start]

	for position in range(2, length + 1):

		source = walk[-1]

		if before_choice is not None:
			before_choice(source)

		candidates: typing.List[typing.Tuple[T, float]] = []
		total = 0.0

		for target, weight in graph.get_transitions(source):

			if target not in ok[position]:
				continue

			modifier = 1.0 if weight_modifier is None else float(weight_modifier(source, target, weight))

			if modifier <= 0:
				continue

			adjusted = float(weight) * modifier
			candidates.append((target, adjusted))
			total += adjusted

		if total <= 0:
			# Stall: the soft weighting suppressed every feasible candidate.
			# Satisfaction beats character — fall back to the bare weights.
			candidates = [
				(target, float(weight))
				for target, weight in graph.get_transitions(source)
				if target in ok[position]
			]
			total = sum(weight for _, weight in candidates)

		roll = rng.uniform(0, total)
		accum = 0.0
		chosen = candidates[-1][0]

		for target, adjusted in candidates:
			accum += adjusted
			if roll <= accum:
				chosen = target
				break

		if after_choice is not None:
			after_choice(chosen)

		walk.append(chosen)

	return walk


def cseg (pitches: typing.Sequence[float]) -> typing.List[int]:

	"""Contour segment: each pitch's rank within the line (Morris's CSEG).

	The melodic shape abstracted from exact pitch: ``[60, 67, 64]`` and
	``[50, 59, 55]`` both rank ``[0, 2, 1]``.  Equal pitches share a rank.

	Example:
		```python
		cseg([60, 67, 64])   # → [0, 2, 1]
		cseg([5, 5, 3])      # → [1, 1, 0]
		```
	"""

	if not pitches:
		return []

	distinct = sorted(set(pitches))

	return [distinct.index(pitch) for pitch in pitches]


def csim (a: typing.Sequence[float], b: typing.Sequence[float]) -> float:

	"""Contour similarity between two equal-length lines (Marvin/Laprade CSIM).

	The fraction of pairwise order relations (above/below/equal) the two
	contours share - 1.0 for identical shapes, regardless of exact pitch.

	Raises ``ValueError`` for mismatched lengths (similarity between
	different-length contours is not defined here).
	"""

	if len(a) != len(b):
		raise ValueError(f"csim() compares equal-length lines - got {len(a)} and {len(b)}")

	count = len(a)

	if count < 2:
		return 1.0

	def relation (x: float, y: float) -> int:
		return (x > y) - (x < y)

	agreements = 0
	pairs = 0

	for i in range(count):
		for j in range(i + 1, count):
			pairs += 1
			if relation(a[i], a[j]) == relation(b[i], b[j]):
				agreements += 1

	return agreements / pairs


# ---------------------------------------------------------------------------
# Xenakis sieves — one integer-set kernel serving scales, pitch pools, rhythm
# grids, and bar selection alike (the experimental composer's primitive).
# ---------------------------------------------------------------------------


def sieve (
	classes: typing.Sequence[typing.Tuple[int, int]],
	hi: int,
	lo: int = 0,
) -> typing.List[int]:

	"""Xenakis sieve: the sorted integers in ``[lo, hi)`` in any of the classes.

	A sieve (Xenakis's *crible*) is a logical formula over **residual
	classes** that denotes a subset of the integers.  This primary form takes
	a list of ``(modulus, residue)`` pairs and returns their **union** over a
	bounded range - every ``x`` in ``[lo, hi)`` with ``x % modulus == residue``
	for at least one class.  The integers index *any* ordered parameter, so
	one kernel builds custom scales (over 0–11 semitones), non-octave pitch
	pools, rhythm grids, and bar-selection masks.

	For intersection and complement, compose :func:`residual_class` objects
	with ``&``, ``|``, ``~`` and evaluate the result (see :class:`Sieve`).

	Parameters:
		classes: ``(modulus, residue)`` pairs.  ``modulus`` must be ≥ 1; the
			residue is taken modulo the modulus.
		hi: Exclusive upper bound.
		lo: Inclusive lower bound (default 0).

	Returns:
		The sorted, de-duplicated integers in range that satisfy any class.

	Raises:
		ValueError: If a modulus is below 1.

	Example:
		```python
		sieve([(12, 0), (12, 2), (12, 4), (12, 5), (12, 7), (12, 9), (12, 11)], hi=12)
		# → [0, 2, 4, 5, 7, 9, 11]  - the major scale as a sieve
		sieve([(2, 0)], hi=12)          # → [0, 2, 4, 6, 8, 10]  - whole-tone
		sieve([(5, 0), (7, 1)], lo=60, hi=96)   # a non-octave pitch pool
		```
	"""

	for modulus, _residue in classes:
		if modulus < 1:
			raise ValueError(f"sieve modulus must be at least 1 - got {modulus}")

	hits = {
		x
		for x in range(lo, hi)
		for modulus, residue in classes
		if x % modulus == residue % modulus
	}

	return sorted(hits)


class Sieve:

	"""A composable Xenakis sieve - residual classes under ``&`` ``|`` ``~``.

	The full algebra layer over :func:`sieve`: build a :class:`Sieve` with
	:func:`residual_class` and combine with union (``|``), intersection
	(``&``), and complement (``~``), then :meth:`evaluate` over a range.
	Membership is decided per integer, so complement is well-defined
	without a range until evaluation.

	Example:
		```python
		# Multiples of 2 or 3, excluding steps one past a multiple of 4.
		evens = subsequence.sequence_utils.residual_class(2, 0)
		thirds = subsequence.sequence_utils.residual_class(3, 0)
		off_fours = subsequence.sequence_utils.residual_class(4, 1)
		((evens | thirds) & ~off_fours).evaluate(hi=24)
		```
	"""

	def __init__ (self, predicate: typing.Callable[[int], bool]) -> None:

		"""Wrap a membership predicate (use :func:`residual_class` to make one)."""

		self._predicate = predicate

	def __contains__ (self, value: int) -> bool:

		"""Membership test for a single integer."""

		return self._predicate(value)

	def __or__ (self, other: "Sieve") -> "Sieve":

		"""Union - in either sieve."""

		return Sieve(lambda x: self._predicate(x) or other._predicate(x))

	def __and__ (self, other: "Sieve") -> "Sieve":

		"""Intersection - in both sieves."""

		return Sieve(lambda x: self._predicate(x) and other._predicate(x))

	def __invert__ (self) -> "Sieve":

		"""Complement - every integer NOT in this sieve."""

		return Sieve(lambda x: not self._predicate(x))

	def evaluate (self, hi: int, lo: int = 0) -> typing.List[int]:

		"""The sorted integers in ``[lo, hi)`` that belong to this sieve."""

		return [x for x in range(lo, hi) if self._predicate(x)]


def residual_class (modulus: int, residue: int) -> Sieve:

	"""A single residual class ``{x : x % modulus == residue}`` as a :class:`Sieve`.

	The atom of sieve algebra (Xenakis's notation ``modulus @ residue``).
	Combine with ``&`` ``|`` ``~`` and call :meth:`Sieve.evaluate`.
	"""

	if modulus < 1:
		raise ValueError(f"residual-class modulus must be at least 1 - got {modulus}")

	reduced = residue % modulus

	return Sieve(lambda x: x % modulus == reduced)


# ---------------------------------------------------------------------------
# Toussaint rhythm measures — evenness, off-beatness, syncopation (analysis
# primitives from "The Geometry of Musical Rhythm").
# ---------------------------------------------------------------------------


def rhythmic_evenness (onsets: typing.Sequence[int], grid: int, normalize: bool = True) -> float:

	"""How evenly onsets are spread around the cycle (Toussaint's evenness).

	Places the *grid* pulses as equally spaced points on a unit circle and
	sums the chord lengths between every pair of onsets (``2·sin(π·d/grid)``
	for a pulse distance ``d``).  A maximally even rhythm (a regular polygon -
	the Euclidean rhythms) maximises this sum; clustered onsets minimise it.

	Parameters:
		onsets: 0-based onset indices (duplicates and out-of-range values are
			reduced modulo *grid* and de-duplicated).
		grid: Pulses in the cycle.
		normalize: Divide by the maximally-even sum for *k* onsets, giving
			``(0, 1]`` (1.0 = perfectly even).  ``False`` returns the raw sum.

	Returns:
		The evenness, in ``(0, 1]`` when normalised (1.0 for fewer than two
		onsets).

	Example:
		```python
		rhythmic_evenness([0, 3, 6], 8)     # tresillo - near 1.0
		rhythmic_evenness([0, 1, 2], 8)     # clustered - much lower
		```
	"""

	if grid < 1:
		raise ValueError(f"grid must be at least 1 - got {grid}")

	reduced = sorted({o % grid for o in onsets})
	k = len(reduced)

	if k < 2:
		return 1.0

	raw = sum(
		2.0 * math.sin(math.pi * abs(reduced[a] - reduced[b]) / grid)
		for a in range(k)
		for b in range(a + 1, k)
	)

	if not normalize:
		return raw

	# The maximally-even arrangement of k points on the grid is the regular
	# k-gon: pairwise distances 2·sin(π·i/k) for each of the k rotations.
	maximum = sum(2.0 * math.sin(math.pi * i / k) * (k - i) for i in range(1, k))

	return raw / maximum if maximum > 0 else 1.0


def offbeatness (onsets: typing.Sequence[int], grid: int) -> int:

	"""How many onsets fall on intrinsically off-beat pulses (Toussaint).

	The on-beat pulses are the vertices of every regular sub-polygon of the
	cycle (the divisor metres); the off-beat pulses are exactly those coprime
	to *grid*.  Off-beatness counts onsets landing on coprime positions - a
	metre-independent syncopation flavour (high for rhythms that fight every
	even subdivision).

	Parameters:
		onsets: 0-based onset indices (reduced modulo *grid*, de-duplicated).
		grid: Pulses in the cycle.

	Returns:
		The count of distinct onsets on off-beat (coprime) pulses.

	Example:
		```python
		offbeatness([0, 4, 8, 12], 16)   # 0 - all on the strong polygon
		offbeatness([0, 3, 6, 10, 13], 16)   # 2 - bossa, off-beats on pulses 3 and 13
		```
	"""

	if grid < 1:
		raise ValueError(f"grid must be at least 1 - got {grid}")

	reduced = {o % grid for o in onsets}

	# The downbeat (pulse 0) is always on-beat; the explicit guard also handles
	# grid==1, where gcd(0, 1) == 1 would otherwise misclassify it.
	return sum(1 for p in reduced if p != 0 and math.gcd(p, grid) == 1)


def syncopation (
	onsets: typing.Sequence[int],
	grid: int,
	time_signature: typing.Tuple[int, int] = (4, 4),
	weights: typing.Optional[typing.Sequence[float]] = None,
) -> float:

	"""How much a rhythm pulls away from its metric strong points.

	A weighted off-beat measure: each onset contributes ``max_weight −
	weight_at_its_pulse`` from the metric-weight table (so onsets on the
	downbeat add nothing, onsets on the weakest pulses add the most),
	normalised by the onset count.  Uses :func:`build_metric_weights` by
	default; pass a custom per-pulse *weights* list for additive or
	non-isochronous metres.

	Parameters:
		onsets: 0-based onset indices (reduced modulo *grid*, de-duplicated).
		grid: Pulses in the cycle.
		time_signature: Shapes the default weight table.
		weights: Optional explicit per-pulse weights (length *grid*).

	Returns:
		Mean weight deficit per onset, in ``[0, max_weight − min_weight]``
		(0.0 only when every onset sits on the downbeat, or there are none;
		the downbeat alone carries the maximum weight, so even on-beat
		rhythms score a little above 0).

	Example:
		```python
		syncopation([0], 16)             # 0.0 - the downbeat only
		syncopation([0, 4, 8, 12], 16)   # low - on the beats, but beat 1 is strongest
		syncopation([3, 7, 11, 15], 16)  # high - every onset on a weak pulse
		```
	"""

	if grid < 1:
		raise ValueError(f"grid must be at least 1 - got {grid}")

	table = list(weights) if weights is not None else build_metric_weights(time_signature, grid)

	if len(table) != grid:
		raise ValueError(f"weights must have one value per grid step ({grid}) - got {len(table)}")

	reduced = sorted({o % grid for o in onsets})

	if not reduced:
		return 0.0

	strongest = max(table)

	return sum(strongest - table[p] for p in reduced) / len(reduced)
