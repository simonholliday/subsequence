import subsequence.sequence_utils


def test_sequence_to_indices_basic () -> None:

	"""Extract indices from a binary sequence with hits at known positions."""

	sequence = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]

	assert subsequence.sequence_utils.sequence_to_indices(sequence) == [0, 4, 8, 12]


def test_sequence_to_indices_empty () -> None:

	"""An all-zero sequence should return an empty list."""

	assert subsequence.sequence_utils.sequence_to_indices([0, 0, 0, 0]) == []


def test_sequence_to_indices_all_hits () -> None:

	"""An all-ones sequence should return every index."""

	assert subsequence.sequence_utils.sequence_to_indices([1, 1, 1]) == [0, 1, 2]


def test_roll_no_wraparound () -> None:

	"""Rolling indices that stay within bounds should shift correctly."""

	assert subsequence.sequence_utils.roll([0, 8], 4, 16) == [4, 12]


def test_roll_with_wraparound () -> None:

	"""Indices that exceed length should wrap to the beginning."""

	assert subsequence.sequence_utils.roll([12, 14], 4, 16) == [0, 2]


def test_roll_negative_shift () -> None:

	"""A negative shift should move indices backward with wraparound."""

	assert subsequence.sequence_utils.roll([4, 12], -4, 16) == [0, 8]


def test_roll_empty_list () -> None:

	"""Rolling an empty list should return an empty list."""

	assert subsequence.sequence_utils.roll([], 4, 16) == []


def test_roll_zero_shift () -> None:

	"""A zero shift should return the original indices."""

	assert subsequence.sequence_utils.roll([0, 4, 8, 12], 0, 16) == [0, 4, 8, 12]


def test_roll_full_cycle () -> None:

	"""Rolling by the full length should return the original indices."""

	assert subsequence.sequence_utils.roll([0, 4, 8, 12], 16, 16) == [0, 4, 8, 12]
