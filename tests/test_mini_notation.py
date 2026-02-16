
import pytest
import subsequence.mini_notation


def test_basic_tokenization ():
	
	"""Test breaking string into tokens."""
	
	tokens = subsequence.mini_notation._tokenize("a b c")
	assert tokens == ["a", "b", "c"]
	
	tokens = subsequence.mini_notation._tokenize("a [b c]")
	assert tokens == ["a", ["b", "c"]]
	
	tokens = subsequence.mini_notation._tokenize("a [b [c d]]")
	assert tokens == ["a", ["b", ["c", "d"]]]


def test_basic_parsing ():

	"""Test allocating time slots."""
	
	events = subsequence.mini_notation.parse("a b c d", total_duration=4.0)
	
	assert len(events) == 4
	assert events[0].symbol == "a"
	assert events[0].time == 0.0
	assert events[0].duration == 1.0
	
	assert events[1].symbol == "b"
	assert events[1].time == 1.0
	
	assert events[3].symbol == "d"
	assert events[3].time == 3.0


def test_subdivision ():

	"""Test nested subdivisions."""
	
	# "a [b c] d" -> a(1), [b(0.5), c(0.5)], d(1)
	events = subsequence.mini_notation.parse("a [b c] d", total_duration=3.0)
	
	assert len(events) == 4
	
	# 'a' gets 1 beat
	assert events[0].symbol == "a"
	assert events[0].duration == 1.0
	
	# 'b' gets 0.5 beat
	assert events[1].symbol == "b"
	assert events[1].duration == 0.5
	assert events[1].time == 1.0
	
	# 'c' gets 0.5 beat
	assert events[2].symbol == "c"
	assert events[2].duration == 0.5
	assert events[2].time == 1.5
	
	# 'd' gets 1 beat
	assert events[3].symbol == "d"
	assert events[3].time == 2.0


def test_rests ():

	"""Test rests (~) and (.) are skipped."""
	
	events = subsequence.mini_notation.parse("a ~ b .", total_duration=4.0)
	
	assert len(events) == 2
	
	assert events[0].symbol == "a"
	assert events[0].time == 0.0
	
	assert events[1].symbol == "b"
	assert events[1].time == 2.0  # skips '1.0'


def test_sustain ():

	"""Test sustain (_) extends previous note."""
	
	events = subsequence.mini_notation.parse("a _ b _ _", total_duration=5.0)
	
	assert len(events) == 2
	
	# 'a' takes 2 slots (1.0 + 1.0)
	assert events[0].symbol == "a"
	assert events[0].duration == 2.0
	
	# 'b' takes 3 slots (1.0 + 1.0 + 1.0)
	assert events[1].symbol == "b"
	assert events[1].duration == 3.0
	assert events[1].time == 2.0


def test_empty_string ():

	"""Test empty notation returns no events."""

	events = subsequence.mini_notation.parse("", total_duration=4.0)

	assert events == []


def test_consecutive_sustains ():

	"""Test multiple consecutive sustains extend the same note."""

	events = subsequence.mini_notation.parse("a _ _ _", total_duration=4.0)

	assert len(events) == 1
	assert events[0].symbol == "a"
	assert events[0].duration == 4.0


def test_sustain_at_start ():

	"""Test sustain at start with no prior note is ignored."""

	events = subsequence.mini_notation.parse("_ _ a", total_duration=3.0)

	assert len(events) == 1
	assert events[0].symbol == "a"
	assert events[0].time == 2.0


def test_invalid_total_duration ():

	"""Test that zero or negative total_duration raises ValueError."""

	with pytest.raises(ValueError):
		subsequence.mini_notation.parse("a b", total_duration=0)

	with pytest.raises(ValueError):
		subsequence.mini_notation.parse("a b", total_duration=-1.0)


def test_errors ():

	"""Test invalid syntax."""

	with pytest.raises(subsequence.mini_notation.MiniNotationError):
		subsequence.mini_notation._tokenize("a [ b")

	with pytest.raises(subsequence.mini_notation.MiniNotationError):
		subsequence.mini_notation._tokenize("a ] b")
