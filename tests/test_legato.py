
import pytest
import typing

import subsequence.pattern
import subsequence.pattern_builder
import subsequence.constants.pulses


def test_legato_uniform_gap () -> None:

	"""Test legato transform with uniform note spacing."""

	# 4-beat pattern (96 pulses)
	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at beat 0 and 2 (pulses 0 and 48)
	builder.note(pitch=60, beat=0.0, duration=0.1)
	builder.note(pitch=62, beat=2.0, duration=0.1)

	# Apply legato (defaults to ratio 1.0)
	builder.legato()

	# Pulse 0 -> 48 gap is 48
	# Pulse 48 -> 96 (wrap to 0) gap is 48
	assert pat.steps[0].notes[0].duration == 48
	assert pat.steps[48].notes[0].duration == 48


def test_legato_varying_gaps () -> None:

	"""Test legato transform with irregular spacing."""

	# 4-beat pattern (96 pulses)
	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at 0, 1.0 (24), 3.0 (72)
	builder.note(pitch=60, beat=0.0, duration=0.1)
	builder.note(pitch=60, beat=1.0, duration=0.1)
	builder.note(pitch=60, beat=3.0, duration=0.1)

	builder.legato()

	# 0 -> 24 (gap 24)
	assert pat.steps[0].notes[0].duration == 24
	# 24 -> 72 (gap 48)
	assert pat.steps[24].notes[0].duration == 48
	# 72 -> 0 (wrap: 96-72 = 24)
	assert pat.steps[72].notes[0].duration == 24


def test_legato_ratio () -> None:

	"""Test legato with a ratio < 1.0."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at 0 and 2.0 (48)
	builder.note(pitch=60, beat=0.0, duration=0.1)
	builder.note(pitch=60, beat=2.0, duration=0.1)

	# 50% legato
	builder.legato(ratio=0.5)

	# Gap 48 * 0.5 = 24
	assert pat.steps[0].notes[0].duration == 24
	assert pat.steps[48].notes[0].duration == 24


def test_legato_single_note () -> None:

	"""Test legato with a single note (should fill pattern)."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Note at beat 1.0 (24)
	builder.note(pitch=60, beat=1.0, duration=0.1)

	builder.legato()

	# Should fill 96 pulses (full length)
	assert pat.steps[24].notes[0].duration == 96


def test_legato_empty () -> None:

	"""Test legato on empty pattern (no-op)."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	builder.legato()
	assert len(pat.steps) == 0


def test_legato_minimum_duration () -> None:

	"""Ensure duration is at least 1 pulse."""

	pat = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

	# Notes at 0 and 0 + epsilon (simulate tight spacing or tiny ratio)
	# But pulse resolution is integers.
	# Let's use a very small ratio on a normal gap.
	
	builder.note(pitch=60, beat=0.0)
	builder.note(pitch=60, beat=1.0) # Gap 24

	# Ratio 0.0001 -> duration would be 0
	builder.legato(ratio=0.0001)

	assert pat.steps[0].notes[0].duration == 1
