import random

import subsequence.sequence_utils


F = subsequence.sequence_utils.flip
C = subsequence.sequence_utils.clamp
TH = subsequence.sequence_utils.threshold
TOL = 1e-9


# --- flip ---

def test_flip_default_is_complement () -> None:

	"""The default range gives the [0, 1] complement 1 - x."""

	assert abs(F(0.0) - 1.0) < TOL
	assert abs(F(1.0) - 0.0) < TOL
	assert abs(F(0.25) - 0.75) < TOL


def test_flip_is_involution () -> None:

	"""Flipping twice returns the original value."""

	rng = random.Random(0)

	for _ in range(500):
		x = rng.random()
		assert abs(F(F(x)) - x) < TOL


def test_flip_range_aware () -> None:

	"""A non-unit range mirrors within that range."""

	assert F(100, 0, 127) == 27
	assert F(0, 0, 127) == 127
	assert F(127, 0, 127) == 0


def test_flip_logical_not_on_binary () -> None:

	"""On a 0/1 list flip is the logical complement."""

	out = F([1, 0, 0, 1])
	for o, e in zip(out, [0.0, 1.0, 1.0, 0.0]):
		assert abs(o - e) < TOL


def test_flip_scalar_returns_float () -> None:

	"""A scalar value returns a float."""

	assert isinstance(F(0.3), float)


def test_flip_list_returns_list () -> None:

	"""A list value returns a same-length list."""

	out = F([0.1, 0.2, 0.9])
	assert isinstance(out, list)
	assert len(out) == 3


def test_flip_empty_list () -> None:

	"""An empty list yields an empty list."""

	assert F([]) == []


def test_flip_does_not_clamp () -> None:

	"""Out-of-range input is reflected, not clamped."""

	assert abs(F(1.2) - (-0.2)) < TOL


# --- clamp ---

def test_clamp_within_passes () -> None:

	"""A value already in range is unchanged."""

	assert C(0.5) == 0.5


def test_clamp_bounds () -> None:

	"""Out-of-range values snap to the nearest bound."""

	assert C(1.2) == 1.0
	assert C(-0.3) == 0.0


def test_clamp_custom_range () -> None:

	"""A custom range bounds to that range."""

	assert C(200, 0, 127) == 127
	assert C(-5, 0, 127) == 0


def test_clamp_list () -> None:

	"""A list is bounded element-wise."""

	out = C([-1.0, 0.5, 2.0])
	for o, e in zip(out, [0.0, 0.5, 1.0]):
		assert abs(o - e) < TOL


def test_clamp_scalar_returns_float () -> None:

	"""A scalar value returns a float."""

	assert isinstance(C(0.4), float)


def test_clamp_list_returns_list () -> None:

	"""A list value returns a list."""

	assert isinstance(C([0.1, 0.2]), list)


def test_clamp_empty_list () -> None:

	"""An empty list yields an empty list."""

	assert C([]) == []


def test_flip_then_clamp_composes () -> None:

	"""flip composes with clamp to tame out-of-range input."""

	assert C(F(1.2)) == 0.0


# --- threshold ---

def test_threshold_is_strict () -> None:

	"""Exactly the cutoff does NOT fire; strictly above does."""

	assert TH([0.5, 0.50001, 0.49999]) == [0, 1, 0]


def test_threshold_default_cutoff () -> None:

	"""The default cutoff is 0.5."""

	assert TH([0.9, 0.1, 0.6, 0.4]) == [1, 0, 1, 0]


def test_threshold_custom_cutoff () -> None:

	"""A custom cutoff gates against that level."""

	assert TH([0.3, 0.7], 0.6) == [0, 1]


def test_threshold_returns_ints () -> None:

	"""Every output element is an int 0 or 1."""

	for v in TH([0.9, 0.1, 0.6]):
		assert isinstance(v, int)
		assert v in (0, 1)


def test_threshold_empty () -> None:

	"""An empty sequence yields an empty list."""

	assert TH([]) == []


def test_threshold_pairs_with_indices () -> None:

	"""threshold + sequence_to_indices gives the firing steps."""

	gate = TH([0.9, 0.1, 0.6, 0.4])
	assert subsequence.sequence_utils.sequence_to_indices(gate) == [0, 2]
