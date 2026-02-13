import typing


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
