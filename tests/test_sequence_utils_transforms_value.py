import random

import pytest

import subsequence.sequence_utils


F = subsequence.sequence_utils.flip
C = subsequence.sequence_utils.clamp
TH = subsequence.sequence_utils.threshold
FOLD = subsequence.sequence_utils.fold
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


# --- fold ---


def test_fold_leaves_in_range_values_alone () -> None:

	"""Values already inside the range pass through untouched, in both modes."""

	inside = [0, 1, 5, 11]
	assert FOLD(inside, 0, 12) == inside
	assert FOLD(inside, 0, 12, mode="reflect") == inside


def test_fold_wrap_is_modulo () -> None:

	"""Wrapping reappears at the opposite end — the octave-style modulo."""

	assert FOLD([12, 13, 24, 25], 0, 12) == [0, 1, 0, 1]


def test_fold_reflect_turns_around_at_the_boundary () -> None:

	"""Reflecting reverses direction at the wall instead of jumping."""

	assert FOLD([11, 12, 13, 14], 0, 12, mode="reflect") == [11, 12, 11, 10]


def test_fold_wrap_excludes_high_reflect_includes_it () -> None:

	"""The documented range asymmetry: high is reachable only under reflect."""

	assert FOLD([12], 0, 12) == [0]
	assert FOLD([12], 0, 12, mode="reflect") == [12]


def test_fold_handles_negatives () -> None:

	"""Values below the range fold back up, not down into nonsense."""

	assert FOLD([-1, -12], 0, 12) == [11, 0]
	assert FOLD([-1, -2], 0, 12, mode="reflect") == [1, 2]


def test_fold_respects_a_non_zero_low () -> None:

	"""The range need not start at zero."""

	assert all(60 <= v <= 72 for v in FOLD([0, 59, 100, 200], 60, 72, mode="reflect"))
	assert all(60 <= v < 72 for v in FOLD([0, 59, 100, 200], 60, 72))


def test_fold_is_idempotent () -> None:

	"""Folding an already-folded sequence changes nothing further."""

	raw = [0, 5, 13, 40, -7, 99]

	for mode in ("wrap", "reflect"):
		once = FOLD(raw, 0, 12, mode=mode)
		assert FOLD(once, 0, 12, mode=mode) == once


def test_fold_wrap_period_and_reflect_period () -> None:

	"""Wrap repeats every span; reflect repeats every two spans (there and back)."""

	rng = random.Random(0)

	for _ in range(200):
		v = rng.randint(-100, 100)
		assert FOLD([v], 0, 12) == FOLD([v + 12], 0, 12)
		assert FOLD([v], 0, 12, mode="reflect") == FOLD([v + 24], 0, 12, mode="reflect")


def test_fold_empty () -> None:

	"""An empty sequence yields an empty list."""

	assert FOLD([], 0, 12) == []


def test_fold_preserves_length () -> None:

	"""Folding never adds or drops steps."""

	raw = [0, 13, -4, 77, 12]
	assert len(FOLD(raw, 0, 7)) == len(raw)


def test_fold_needs_a_real_range () -> None:

	"""A zero-width or inverted range is an error, not a divide-by-zero."""

	with pytest.raises(ValueError) as exc:
		FOLD([1], 5, 5)
	assert "must be above" in str(exc.value)

	with pytest.raises(ValueError):
		FOLD([1], 12, 0)


def test_fold_unknown_mode_lists_the_valid_names () -> None:

	"""An unknown mode names what it should have been."""

	with pytest.raises(ValueError) as exc:
		FOLD([1], 0, 12, mode="bounce")
	assert "reflect" in str(exc.value) and "wrap" in str(exc.value)


def test_fold_reflect_stays_inside_where_flip_does_not () -> None:

	"""fold(reflect) is flip applied until it lands: flip alone can leave the range."""

	# 13 is one step past the top, so it bounces back to one below it.
	assert FOLD([13], 0, 12, mode="reflect") == [11]

	# flip mirrors once and does not clamp, so it falls outside the range entirely.
	assert F(13, 0, 12) == -1
