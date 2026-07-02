
import pytest

import subsequence.pattern
import subsequence.pattern_builder


def test_detached_uniform_gap () -> None:

	"""Test detached transform with uniform note spacing."""

	# 4-beat pattern (96 pulses)
	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at beat 0 and 2 (pulses 0 and 48)
	builder.note(pitch=60, beat=0.0, duration=0.1)
	builder.note(pitch=62, beat=2.0, duration=0.1)

	# 0.05 beats = 1 pulse at 24 PPQN (int truncation: int(0.05 * 24) = 1)
	builder.detached()

	# Pulse 0 -> 48 gap is 48; minus 1 pulse silence = 47
	# Pulse 48 -> 96 (wrap to 0) gap is 48; minus 1 pulse silence = 47
	assert pat.steps[0].notes[0].duration == 47
	assert pat.steps[48].notes[0].duration == 47


def test_detached_varying_gaps () -> None:

	"""Test detached transform with irregular spacing and wrap-around."""

	# 4-beat pattern (96 pulses)
	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at 0, 1.0 (24), 3.0 (72)
	builder.note(pitch=60, beat=0.0, duration=0.1)
	builder.note(pitch=60, beat=1.0, duration=0.1)
	builder.note(pitch=60, beat=3.0, duration=0.1)

	# Use 0.25 beats (6 pulses) as the silence
	builder.detached(beats=0.25)

	# 0 -> 24 (gap 24) - 6 = 18
	assert pat.steps[0].notes[0].duration == 18
	# 24 -> 72 (gap 48) - 6 = 42
	assert pat.steps[24].notes[0].duration == 42
	# 72 -> 0 (wrap: 96-72 = 24) - 6 = 18
	assert pat.steps[72].notes[0].duration == 18


def test_detached_explicit_beats () -> None:

	"""Test detached with an explicit beats value larger than the default."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at 0 and 2.0 (48)
	builder.note(pitch=60, beat=0.0, duration=0.1)
	builder.note(pitch=60, beat=2.0, duration=0.1)

	# 0.5-beat silence = 12 pulses
	builder.detached(beats=0.5)

	# Gap 48 - 12 = 36
	assert pat.steps[0].notes[0].duration == 36
	assert pat.steps[48].notes[0].duration == 36


def test_detached_single_note () -> None:

	"""Test detached with a single note — wraps to itself."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Note at beat 1.0 (24)
	builder.note(pitch=60, beat=1.0, duration=0.1)

	# 0.25-beat silence = 6 pulses
	builder.detached(beats=0.25)

	# Wrap-around: gap = 96 (full cycle) - 6 = 90
	assert pat.steps[24].notes[0].duration == 90


def test_detached_empty () -> None:

	"""Test detached on empty pattern (no-op)."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.detached()
	assert len(pat.steps) == 0


def test_detached_minimum_duration () -> None:

	"""Ensure duration is at least 1 pulse when the gap is fully consumed."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Two notes very close together: gap = 24 pulses (1 beat).
	# A detached value of 2 beats (48 pulses) would push duration negative.
	builder.note(pitch=60, beat=0.0)
	builder.note(pitch=60, beat=1.0)

	builder.detached(beats=2.0)

	# Must clamp to 1 pulse minimum.
	assert pat.steps[0].notes[0].duration == 1


def test_detached_invalid_beats () -> None:

	"""beats <= 0 must raise ValueError."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	with pytest.raises(ValueError, match="detached beats must be positive"):
		builder.detached(beats=0)

	with pytest.raises(ValueError, match="detached beats must be positive"):
		builder.detached(beats=-0.1)


def test_detached_returns_self () -> None:

	"""detached() must return self for chaining."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.note(pitch=60, beat=0.0)
	result = builder.detached()
	assert result is builder
