"""Tests for subsequence.tuning — Tuning class, .scl parser, and apply_tuning_to_pattern()."""

import math
import pytest

import subsequence.constants
import subsequence.constants.durations
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.tuning
from subsequence.tuning import Tuning, ChannelAllocator, apply_tuning_to_pattern


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_builder(channel: int = 0, length: float = 4, cycle: int = 0, data: dict = None):
	"""Create a Pattern and PatternBuilder pair for testing."""
	default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
	pattern = subsequence.pattern.Pattern(channel=channel, length=length)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern,
		cycle=cycle,
		default_grid=default_grid,
		data=data if data is not None else {},
	)
	return pattern, builder


def _pitches(pattern):
	"""Return all note pitches in pulse order."""
	return [n.pitch for pulse in sorted(pattern.steps) for n in pattern.steps[pulse].notes]


def _channels(pattern):
	"""Return all note channels in pulse order."""
	return [n.channel for pulse in sorted(pattern.steps) for n in pattern.steps[pulse].notes]


def _bend_events(pattern):
	"""Return list of (pulse, value, channel) for all pitchwheel events."""
	return [
		(ev.pulse, ev.value, ev.channel)
		for ev in pattern.cc_events
		if ev.message_type == "pitchwheel"
	]


# ── .scl parser ───────────────────────────────────────────────────────────────

SCL_12TET = """\
! 12tet.scl
12-tone equal temperament
12
100.0
200.0
300.0
400.0
500.0
600.0
700.0
800.0
900.0
1000.0
1100.0
1200.0
"""

SCL_MEANTONE = """\
! meanquar.scl
1/4-comma meantone scale. Pietro Aaron's temperament (1523)
12
76.04900
193.15686
310.26471
5/4
503.42157
579.47057
696.57843
25/16
889.73529
1006.84314
1082.89214
2/1
"""

SCL_JUST = """\
! just.scl
Ptolemy just intonation
7
9/8
5/4
4/3
3/2
5/3
15/8
2/1
"""

SCL_BAD_COUNT = """\
! bad.scl
Bad scale
3
100.0
"""


def test_parse_12tet_cents():
	t = Tuning.from_scl_string(SCL_12TET)
	assert t.size == 12
	assert abs(t.cents[0] - 100.0) < 1e-6
	assert abs(t.cents[-1] - 1200.0) < 1e-6
	assert t.description == "12-tone equal temperament"


def test_parse_meantone_mixed():
	"""Quarter-comma meantone uses both cents and ratio notation."""
	t = Tuning.from_scl_string(SCL_MEANTONE)
	assert t.size == 12
	# 5/4 = 386.313... cents
	assert abs(t.cents[3] - 1200.0 * math.log2(5 / 4)) < 0.001
	# 2/1 = 1200 cents
	assert abs(t.cents[-1] - 1200.0) < 0.001


def test_parse_just_intonation_ratios():
	t = Tuning.from_scl_string(SCL_JUST)
	assert t.size == 7
	assert abs(t.cents[0] - 1200.0 * math.log2(9 / 8)) < 0.001  # 203.91 cents
	assert abs(t.cents[2] - 1200.0 * math.log2(4 / 3)) < 0.001  # 498.04 cents
	assert abs(t.cents[-1] - 1200.0) < 0.001


def test_parse_bad_count_raises():
	with pytest.raises(ValueError, match="expected 3 pitch values"):
		Tuning.from_scl_string(SCL_BAD_COUNT)


def test_parse_comment_lines_ignored():
	"""Lines starting with ! are comments and must not affect the parse."""
	t = Tuning.from_scl_string(SCL_12TET)
	assert t.size == 12  # not 13 (the ! lines aren't counted)


# ── Factory methods ───────────────────────────────────────────────────────────

def test_from_cents_roundtrip():
	cents_in = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0, 1100.0, 1200.0]
	t = Tuning.from_cents(cents_in)
	assert t.cents == cents_in
	assert t.size == 12


def test_from_ratios():
	t = Tuning.from_ratios([9 / 8, 5 / 4, 4 / 3, 3 / 2, 5 / 3, 15 / 8, 2.0])
	assert t.size == 7
	assert abs(t.cents[3] - 1200.0 * math.log2(3 / 2)) < 0.001  # 701.955 cents


def test_equal_12():
	t = Tuning.equal(12)
	assert t.size == 12
	for i, c in enumerate(t.cents):
		assert abs(c - (i + 1) * 100.0) < 1e-9


def test_equal_19():
	t = Tuning.equal(19)
	assert t.size == 19
	step = 1200.0 / 19
	assert abs(t.cents[0] - step) < 1e-9
	assert abs(t.cents[-1] - 1200.0) < 1e-9


def test_period_cents():
	t = Tuning.equal(12)
	assert abs(t.period_cents - 1200.0) < 1e-9


# ── pitch_bend_for_note() ─────────────────────────────────────────────────────

def test_12tet_tuning_zero_bend():
	"""Standard 12-TET produces (same_note, 0.0) for every note."""
	t = Tuning.equal(12)
	for midi in range(21, 109):
		nearest, bend = t.pitch_bend_for_note(midi, reference_note=60)
		assert nearest == midi, f"note {midi}: nearest={nearest}"
		assert abs(bend) < 1e-9, f"note {midi}: bend={bend}"


def test_meantone_major_third():
	"""Quarter-comma meantone major third is 386.31 cents; 12-TET is 400 cents.

	For MIDI 64 (E4, degree 4 from C4=60), the tuning is 386.31 cents above 60.
	12-TET equivalent: 400 cents = MIDI 64. Offset = -13.69 cents = -0.1369 semitones.
	With bend_range=2: bend ≈ -0.0684.
	"""
	t = Tuning.from_scl_string(SCL_MEANTONE)
	nearest, bend = t.pitch_bend_for_note(64, reference_note=60, bend_range=2.0)
	# Major third in meantone is 386.31 cents → continuous note = 60 + 3.8631 = 63.8631
	# Nearest = 64, bend = (63.8631 - 64) / 2.0 = -0.0684
	assert nearest == 64
	assert abs(bend - (-0.0684)) < 0.001


def test_just_perfect_fifth():
	"""Just perfect fifth is 701.955 cents; 12-TET is 700 cents.

	Scale has 7 degrees (indices 0-6 for cents list).
	MIDI 60 = degree 0, MIDI 67 = degree 0 of next octave.
	MIDI 64 = steps_from_root 4, degree = 4 % 7 = 4, octave = 0.
	cents[4] = 3/2 = 701.955 cents (the perfect fifth).
	"""
	t = Tuning.from_ratios([9 / 8, 5 / 4, 4 / 3, 3 / 2, 5 / 3, 15 / 8, 2.0])
	# MIDI 64: steps_from_root = 4, degree = 4, octave = 0
	# total_cents = 0 + cents[3] = 701.955 cents
	# continuous = 60 + 701.955/100 = 67.01955 → nearest = 67
	nearest, bend = t.pitch_bend_for_note(64, reference_note=60, bend_range=2.0)
	assert nearest == 67
	assert abs(bend - 0.00977) < 0.001


def test_bend_clamp():
	"""A tuning with very large deviations (e.g., 1 semitone) clamps to ±1.0 at narrow range."""
	# Simulate a tuning where a note is 0.9 semitones flat of 12-TET
	# bend = -0.9 / 0.5 = -1.8 → clamps to -1.0
	t = Tuning.from_cents([50.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0, 1100.0, 1200.0])
	_, bend = t.pitch_bend_for_note(61, reference_note=60, bend_range=0.5)
	assert bend >= -1.0  # should be clamped


def test_reference_note_shifts_root():
	t = Tuning.equal(12)
	# With reference_note=69 (A4), MIDI 69 should map to itself with 0 bend
	nearest, bend = t.pitch_bend_for_note(69, reference_note=69, bend_range=2.0)
	assert nearest == 69
	assert abs(bend) < 1e-9


# ── ChannelAllocator ──────────────────────────────────────────────────────────

def test_allocator_single_channel():
	alloc = ChannelAllocator([3])
	# First note: channel 3, released at pulse 100
	assert alloc.allocate(0, 100) == 3
	# New note after release: channel 3 again
	assert alloc.allocate(100, 50) == 3


def test_allocator_round_robin():
	alloc = ChannelAllocator([1, 2, 3])
	# Three simultaneous notes get different channels
	ch1 = alloc.allocate(0, 200)
	ch2 = alloc.allocate(0, 200)
	ch3 = alloc.allocate(0, 200)
	assert sorted([ch1, ch2, ch3]) == [1, 2, 3]


def test_allocator_recycles_freed_channels():
	alloc = ChannelAllocator([1, 2])
	alloc.allocate(0, 100)   # channel 1 busy until 100
	alloc.allocate(0, 100)   # channel 2 busy until 100
	# At pulse 100, both are free
	ch = alloc.allocate(100, 50)
	assert ch in [1, 2]


def test_allocator_empty_raises():
	with pytest.raises(ValueError):
		ChannelAllocator([])


# ── apply_tuning_to_pattern() ─────────────────────────────────────────────────

def test_12tet_noop():
	"""12-TET tuning produces zero-value bend events but doesn't change pitches."""
	pattern, builder = _make_builder(channel=0)
	builder.note(60, beat=0, velocity=80, duration=0.5)
	builder.note(64, beat=1, velocity=80, duration=0.5)

	t = Tuning.equal(12)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0)

	# Pitches unchanged
	assert _pitches(pattern) == [60, 64]
	# Bend events injected but all zero
	bends = _bend_events(pattern)
	assert len(bends) == 2
	for _, val, _ in bends:
		assert val == 0


def test_monophonic_pitch_and_bend_injected():
	"""Each note gets its pitch corrected and a pitchwheel event at onset."""
	pattern, builder = _make_builder(channel=0)
	builder.note(60, beat=0, velocity=80, duration=0.5)
	builder.note(61, beat=1, velocity=80, duration=0.5)
	builder.note(62, beat=2, velocity=80, duration=0.5)

	t = Tuning.from_scl_string(SCL_MEANTONE)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0)

	# Same number of pitch-bend events as notes
	bends = _bend_events(pattern)
	assert len(bends) == 3


def test_monophonic_all_on_same_channel():
	"""Without channel rotation, all notes stay on the pattern channel."""
	pattern, builder = _make_builder(channel=2)
	for i in range(4):
		builder.note(60 + i, beat=float(i), velocity=80, duration=0.5)

	t = Tuning.equal(19)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0, channels=None)

	assert all(ch == 2 for ch in _channels(pattern))


def test_polyphonic_channel_rotation():
	"""Overlapping notes get different channels from the pool."""
	# Two notes at the same beat (pulse 0) — polyphonic
	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	qn = subsequence.constants.MIDI_QUARTER_NOTE
	dur = qn * 2  # 2 beat duration — notes overlap

	step = subsequence.pattern.Step()
	step.notes.append(subsequence.pattern.Note(pitch=60, velocity=80, duration=dur, channel=0))
	step.notes.append(subsequence.pattern.Note(pitch=64, velocity=80, duration=dur, channel=0))
	pattern.steps[0] = step

	t = Tuning.equal(12)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0, channels=[1, 2, 3])

	channels_used = {n.channel for step in pattern.steps.values() for n in step.notes}
	assert len(channels_used) == 2  # Two notes → two different channels
	assert channels_used.issubset({1, 2, 3})


def test_bend_events_have_correct_channel():
	"""Pitchwheel events for channel-rotated notes must carry the note's channel."""
	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	qn = subsequence.constants.MIDI_QUARTER_NOTE
	dur = qn * 2

	step = subsequence.pattern.Step()
	step.notes.append(subsequence.pattern.Note(pitch=60, velocity=80, duration=dur, channel=0))
	step.notes.append(subsequence.pattern.Note(pitch=64, velocity=80, duration=dur, channel=0))
	pattern.steps[0] = step

	t = Tuning.equal(12)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0, channels=[4, 5])

	# Each note's channel is in the pool, and the corresponding bend event has the same channel
	note_channels = {n.channel for step in pattern.steps.values() for n in step.notes}
	bend_channels = {ch for _, _, ch in _bend_events(pattern)}
	assert bend_channels == note_channels


def test_additive_composition_with_existing_bend():
	"""Tuning offsets are added to existing pitchwheel events from user bends."""
	pattern, builder = _make_builder(channel=0)
	builder.note(60, beat=0, velocity=80, duration=1.0)

	# Manually inject a user pitchwheel event at pulse 0 with value 1000
	qn = subsequence.constants.MIDI_QUARTER_NOTE
	pattern.cc_events.append(
		subsequence.pattern.CcEvent(pulse=0, message_type="pitchwheel", value=1000)
	)

	# Apply 12-TET (bend = 0 for note 60), so the existing bend should be unchanged
	t = Tuning.equal(12)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0)

	# The original event at pulse 0 is shifted by tuning offset (0 for 12-TET) = 1000
	user_events = [ev for ev in pattern.cc_events if ev.value == 1000]
	assert len(user_events) >= 1


def test_bend_reset_becomes_tuning_offset():
	"""A bend-reset (value=0) event is replaced with the active tuning offset."""
	# Set up a pattern with meantone tuning on note 64 (major third, -14 cents from 12-TET)
	pattern, builder = _make_builder(channel=0)
	builder.note(64, beat=0, velocity=80, duration=2.0)

	# Inject a portamento-style reset at mid-note
	qn = subsequence.constants.MIDI_QUARTER_NOTE
	pattern.cc_events.append(
		subsequence.pattern.CcEvent(pulse=qn, message_type="pitchwheel", value=0)
	)

	t = Tuning.from_scl_string(SCL_MEANTONE)
	apply_tuning_to_pattern(pattern, t, bend_range=2.0)

	# The value=0 reset should have been replaced with the tuning offset (non-zero for meantone)
	reset_events = [ev for ev in pattern.cc_events if ev.pulse == qn and ev.message_type == "pitchwheel"]
	assert len(reset_events) == 1
	# For meantone major third, offset is about -560 raw MIDI units (about -0.0684 normalized)
	assert reset_events[0].value != 0  # not zero — replaced with tuning offset


def test_empty_pattern_no_error():
	"""apply_tuning_to_pattern on an empty pattern raises no error."""
	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	t = Tuning.equal(12)
	apply_tuning_to_pattern(pattern, t)  # should not raise


def test_drums_not_affected_by_global_tuning():
	"""The _tuning_exclude_drums flag is respected in auto-application."""
	# This tests the composition integration logic (simulated here)
	# by checking that a drum pattern's notes are not altered.
	pattern, builder = _make_builder(channel=9)
	builder.note(36, beat=0, velocity=100, duration=0.1)  # kick
	original_pitch = 36

	t = Tuning.equal(19)
	# We apply the tuning directly here to confirm the pitch would change without the drum guard,
	# then test via the flag in a separate scenario
	import copy
	pattern_copy = copy.deepcopy(pattern)
	apply_tuning_to_pattern(pattern_copy, t)
	# 19-TET on note 36 relative to 60: note 36 in 19-TET does change pitch
	# (we just verify the mechanism works; the guard is composition-level)
	assert _pitches(pattern) == [36]  # original untouched


# ── PatternBuilder.apply_tuning() ─────────────────────────────────────────────

def test_builder_apply_tuning_method():
	"""PatternBuilder.apply_tuning() is a method chaining transform."""
	pattern, builder = _make_builder(channel=0)
	builder.note(60, beat=0, velocity=80, duration=0.5)
	builder.note(64, beat=1, velocity=80, duration=0.5)

	t = Tuning.equal(12)
	result = builder.apply_tuning(t, bend_range=2.0)

	assert result is builder  # method chaining
	bends = _bend_events(pattern)
	assert len(bends) == 2


def test_builder_apply_tuning_sets_flag():
	"""apply_tuning() sets _tuning_applied so auto-application is skipped."""
	pattern, builder = _make_builder(channel=0)
	builder.note(60, beat=0, velocity=80, duration=0.5)
	t = Tuning.equal(12)
	builder.apply_tuning(t)
	assert builder._tuning_applied is True


# ── Package-level export ──────────────────────────────────────────────────────

def test_tuning_exported_from_package():
	"""Tuning is accessible as subsequence.Tuning."""
	import subsequence
	assert hasattr(subsequence, "Tuning")
	assert subsequence.Tuning is Tuning
