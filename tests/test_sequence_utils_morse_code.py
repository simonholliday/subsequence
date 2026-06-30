import pytest

import subsequence.sequence_utils


MORSE = subsequence.sequence_utils.morse_code
TO_INDICES = subsequence.sequence_utils.sequence_to_indices


def test_single_dot () -> None:

	"""A lone 'e' (one dot) is a single short note."""

	assert MORSE("e") == [0.25]


def test_single_dash_spans_three_cells () -> None:

	"""A lone 't' (one dash) is one note sustained across three unit cells."""

	assert MORSE("t") == [0.75, 0.0, 0.0]


def test_sos_canonical_pattern () -> None:

	"""'sos' reconstructs the canonical ...---... — three dots, three dashes, three dots."""

	rhythm = MORSE("sos")
	steps = TO_INDICES(rhythm)
	durations = [rhythm[s] for s in steps]

	# Nine notes: dot dot dot / dash dash dash / dot dot dot.
	assert durations == [0.25, 0.25, 0.25, 0.75, 0.75, 0.75, 0.25, 0.25, 0.25]
	# Onset cells: S at 0,2,4 ; O at 8,12,16 ; S at 22,24,26 ; total 27 cells.
	assert steps == [0, 2, 4, 8, 12, 16, 22, 24, 26]
	assert len(rhythm) == 27


def test_letter_gap () -> None:

	"""Two letters are separated by a three-cell rest (letter gap)."""

	assert MORSE("ee") == [0.25, 0.0, 0.0, 0.0, 0.25]


def test_word_gap () -> None:

	"""Two words are separated by a seven-cell rest (word gap)."""

	assert MORSE("e e") == [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25]


def test_case_insensitive () -> None:

	"""Morse is caseless — upper and lower case encode identically."""

	assert MORSE("SOS") == MORSE("sos")


def test_unknown_characters_dropped () -> None:

	"""Unencodable characters are removed, not substituted."""

	assert MORSE("e#e") == MORSE("ee")


def test_whitespace_collapsed_and_trimmed () -> None:

	"""Runs of whitespace collapse to one word gap; leading/trailing trimmed."""

	assert MORSE("e   e") == MORSE("e e")
	assert MORSE("  e  ") == MORSE("e")


def test_empty_and_all_invalid_are_noops () -> None:

	"""No encodable characters yields an empty list (no-op)."""

	assert MORSE("") == []
	assert MORSE("   ") == []
	assert MORSE("###") == []


def test_punctuation_supported () -> None:

	"""Extended punctuation encodes (e.g. '?' = ..--.. = four dots-with-two-dashes)."""

	rhythm = MORSE("?")
	durations = [rhythm[s] for s in TO_INDICES(rhythm)]
	assert durations == [0.25, 0.25, 0.75, 0.75, 0.25, 0.25]


def test_parameterised_durations () -> None:

	"""Custom dot/dash rescale note lengths and the dash span (round(dash/dot) cells)."""

	# dot is the unit; dash spans round(1.5 / 0.5) = 3 cells.
	assert MORSE("e", dot=0.5) == [0.5]
	assert MORSE("t", dot=0.5, dash=1.5) == [1.5, 0.0, 0.0]


def test_custom_gaps () -> None:

	"""Gap parameters set the rest spans in dot-units."""

	# letter_gap of one unit (0.25) -> a single rest cell between the two dots.
	assert MORSE("ee", letter_gap=0.25) == [0.25, 0.0, 0.25]


def test_dot_must_be_positive () -> None:

	"""dot is the base time unit and must be positive."""

	with pytest.raises(ValueError) as exc:
		MORSE("e", dot=0.0)
	assert "dot must be positive" in str(exc.value)
