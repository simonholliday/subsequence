import pytest

import subsequence.sequence_utils


RECAMAN = subsequence.sequence_utils.recaman


def test_known_opening () -> None:

	"""The canonical opening of Recaman's sequence."""

	assert RECAMAN(22) == [0, 1, 3, 6, 2, 7, 13, 20, 12, 21, 11, 22, 10, 23, 9, 24, 8, 25, 43, 62, 42, 63]


def test_first_value_is_the_start () -> None:

	"""The sequence begins where it is told to."""

	for start in (0, 1, 5, 17, 40):
		assert RECAMAN(8, start=start)[0] == start


def test_step_size_always_equals_the_step_number () -> None:

	"""The defining property: the gap between consecutive values is exactly n.

	This is the strongest available check — it holds for every start value and
	pins the rule itself rather than a particular output.
	"""

	for start in (0, 2, 9, 40):
		values = RECAMAN(60, start=start)
		gaps = [abs(b - a) for a, b in zip(values, values[1:])]
		assert gaps == list(range(1, len(values)))


def test_values_are_never_negative () -> None:

	"""The backward step is only taken when it stays positive."""

	assert all(v >= 0 for v in RECAMAN(200, start=0))


def test_start_zero_and_one_are_the_same_shape () -> None:

	"""0 and 1 differ only by transposition — the documented gotcha.

	Normalised against their own minimum they are bit-identical, which is why
	stepping start= by one gives no audible variation.
	"""

	a = RECAMAN(200, start=0)
	b = RECAMAN(200, start=1)

	assert [v - min(a) for v in a] == [v - min(b) for v in b]


def test_higher_start_gives_a_longer_opening_descent () -> None:

	"""The musical meaning of start=: how far the melody falls before turning."""

	def descent (start: int) -> int:
		values = RECAMAN(40, start=start)
		n = 1
		while n < len(values) and values[n] < values[n - 1]:
			n += 1
		return n - 1

	assert descent(0) == 0
	assert descent(12) < descent(40) < descent(80)


def test_start_from_two_is_genuinely_new_material () -> None:

	"""From 2 upward the shape really changes, not just its pitch level."""

	base = RECAMAN(40, start=0)
	other = RECAMAN(40, start=5)

	assert [v - min(other) for v in other] != [v - min(base) for v in base]


def test_values_can_repeat () -> None:

	"""The sequence is not a permutation — the forward step can revisit.

	Guarding against a "all values distinct" assumption: 42 arrives twice.
	"""

	values = RECAMAN(32)
	assert len(set(values)) < len(values)


def test_skip_windows_further_along () -> None:

	"""skip= discards leading values, giving a later window of the same sequence."""

	full = RECAMAN(24)
	assert RECAMAN(16, skip=8) == full[8:24]


def test_skip_zero_is_a_no_op () -> None:

	"""The default window is the sequence from the beginning."""

	assert RECAMAN(16, skip=0) == RECAMAN(16)


def test_zero_and_negative_count_are_empty () -> None:

	"""No values requested, none generated."""

	assert RECAMAN(0) == []
	assert RECAMAN(-3) == []


def test_deterministic () -> None:

	"""No randomness — two identical calls agree."""

	assert RECAMAN(50, start=7) == RECAMAN(50, start=7)


def test_negative_skip_raises () -> None:

	"""A negative window offset is a mistake, not a reverse window."""

	with pytest.raises(ValueError) as exc:
		RECAMAN(8, skip=-1)
	assert "cannot be negative" in str(exc.value)


def test_the_wedge_splits_into_two_voices () -> None:

	"""The reason this generator exists: one line heard as two.

	Terms 8-17 split by index parity into a falling voice and a rising one.
	"""

	window = RECAMAN(18)[8:18]

	falling = window[0::2]
	rising = window[1::2]

	assert falling == [12, 11, 10, 9, 8]
	assert rising == [21, 22, 23, 24, 25]
	assert all(b < a for a, b in zip(falling, falling[1:]))
	assert all(b > a for a, b in zip(rising, rising[1:]))
