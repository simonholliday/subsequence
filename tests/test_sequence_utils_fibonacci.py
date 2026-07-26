import pytest

import subsequence.sequence_utils


FIB = subsequence.sequence_utils.fibonacci


def test_raw_sequence_is_fibonacci () -> None:

	"""Unmodulated, each number is the sum of the previous two."""

	assert FIB(12) == [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]


def test_raw_sequence_respects_start_pair () -> None:

	"""(2, 1) gives the Lucas numbers."""

	assert FIB(8, a=2, b=1) == [2, 1, 3, 4, 7, 11, 18, 29]


def test_modulus_bounds_the_values () -> None:

	"""Every value lands inside [0, modulus)."""

	for modulus in (2, 3, 5, 7, 8, 12, 16):
		assert all(0 <= v < modulus for v in FIB(50, modulus=modulus))


def test_pisano_period_sets_the_cycle_length () -> None:

	"""The modulus alone decides the phrase length — this is the musical point."""

	assert len(FIB(modulus=3)) == 8	 # triad
	assert len(FIB(modulus=5)) == 20	# pentatonic
	assert len(FIB(modulus=7)) == 16	# diatonic
	assert len(FIB(modulus=8)) == 12	# octatonic
	assert len(FIB(modulus=12)) == 24   # chromatic


def test_default_count_is_exactly_one_cycle () -> None:

	"""Omitting count returns one full cycle — the next value would restart it."""

	cycle = FIB(modulus=7)
	twice = FIB(len(cycle) * 2, modulus=7)

	assert twice == cycle + cycle


def test_modulus_one_terminates () -> None:

	"""A single-pitch pool gives modulus 1, which must not hang.

	The textbook Pisano method watches for the pair (0, 1), which never occurs
	mod 1; tracking the starting pair instead terminates for every modulus.
	"""

	assert FIB(modulus=1) == [0]


def test_custom_start_gives_its_own_true_cycle () -> None:

	"""A custom pair reports its own orbit, which can be shorter than the Pisano period."""

	orbit = FIB(a=2, b=4, modulus=8)

	assert len(orbit) < len(FIB(modulus=8))
	# It is a real cycle: continuing past it simply repeats.
	assert FIB(len(orbit) * 2, a=2, b=4, modulus=8) == orbit + orbit


def test_start_pairs_can_share_a_cycle () -> None:

	"""(1, 3) is the Lucas cycle entered one step along — the documented phase trap."""

	lucas = FIB(24, a=2, b=1, modulus=12)
	shifted = FIB(24, a=1, b=3, modulus=12)

	assert shifted[:8] == lucas[1:9]


def test_zero_and_negative_count_are_empty () -> None:

	"""No notes requested, no notes generated."""

	assert FIB(0, modulus=7) == []
	assert FIB(-4, modulus=7) == []


def test_deterministic () -> None:

	"""No randomness anywhere — two identical calls agree."""

	assert FIB(30, modulus=7) == FIB(30, modulus=7)


def test_modulus_below_one_raises () -> None:

	"""A modulus is a space to fold into, so it must be at least 1."""

	with pytest.raises(ValueError) as exc:
		FIB(8, modulus=0)
	assert "at least 1" in str(exc.value)


def test_unbounded_call_raises () -> None:

	"""Without a modulus the sequence never repeats, so a count is required."""

	with pytest.raises(ValueError) as exc:
		FIB()
	assert "count or a modulus" in str(exc.value)
