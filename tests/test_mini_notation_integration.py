
import pytest
import subsequence.pattern
import subsequence.pattern_builder


def test_seq_rhythm ():

	"""Test p.seq() with fixed pitch (rhythm mode)."""
	
	pattern = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0, drum_note_map={"k": 36})
	
	# 4 beats: Hit at 0, 1, 2, 3
	builder.seq("x x x x", pitch="k")
	
	steps = pattern.steps
	
	# beat 0
	assert 0 in steps
	assert steps[0].notes[0].pitch == 36
	
	# beat 1 (24 pulses)
	assert 24 in steps
	assert steps[24].notes[0].pitch == 36


def test_seq_melody ():

	"""Test p.seq() with symbols as pitches."""
	
	pattern = subsequence.pattern.Pattern(channel=0, length=4.0)
	builder = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0)
	
	# 4 beats: 60, 62, 64, 65
	builder.seq("60 62 64 65")
	
	steps = pattern.steps
	
	assert steps[0].notes[0].pitch == 60
	assert steps[24].notes[0].pitch == 62
	assert steps[48].notes[0].pitch == 64
	assert steps[72].notes[0].pitch == 65

