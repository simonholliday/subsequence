
import pytest
import typing

import subsequence.pattern
import subsequence.pattern_builder
import subsequence.constants.pulses


def test_staccato_fixed_duration () -> None:

	"""Test staccato sets fixed duration relative to quarter note."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Place notes with different durations
	builder.note(pitch=60, beat=0.0, duration=1.0) # Long note
	builder.note(pitch=62, beat=1.0, duration=0.1) # Short note

	# Apply staccato(0.5) -> duration should be 0.5 * 24 = 12 pulses
	builder.staccato(0.5)

	assert pat.steps[0].notes[0].duration == 12
	assert pat.steps[24].notes[0].duration == 12


def test_staccato_short_ratio () -> None:

	"""Test very short staccato ratio."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.note(60, 0.0)

	# 0.1 beats -> 2.4 pulses -> truncated to 2 pulses
	builder.staccato(0.1)

	assert pat.steps[0].notes[0].duration == int(24 * 0.1)


def test_staccato_long_ratio () -> None:

	"""Test ratio > 1.0 (actually legato/tenuto but valid parameter)."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.note(60, 0.0)

	# 2.0 beats -> 48 pulses
	builder.staccato(2.0)

	assert pat.steps[0].notes[0].duration == 48


def test_staccato_minimum_duration () -> None:

	"""Ensure duration is at least 1 pulse."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.note(60, 0.0)

	# Tiny ratio
	builder.staccato(0.0001)

	assert pat.steps[0].notes[0].duration == 1


def test_staccato_invalid_ratio () -> None:

	"""Test that negative/zero ratio raises ValueError."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.note(60, 0.0)

	with pytest.raises(ValueError):
		builder.staccato(0)
		
	with pytest.raises(ValueError):
		builder.staccato(-0.5)
