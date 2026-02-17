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
			p = probability[i] if i < len(probability) else 1.0
		else:
			p = probability

		result.append(value if rng.random() < p else 0)

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
