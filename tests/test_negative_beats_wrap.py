"""A negative beat counts from the end of the pattern, for every verb (#3005).

``note()`` has always wrapped one — ``beat=-1`` is one beat before the end —
but every control verb converted it straight to a negative *pulse*. Live, the
event went out in the previous cycle; in a recording, the negative delta was
clamped to zero and shifted every later event, tempo and time signature with
them.

The ramps are their own case: wrapping the start alone leaves the span
negative, and a negative span emits nothing at all, so a ramp keeps its length
and crosses the cycle's end instead.
"""

import pathlib
import random
import typing

import mido
import pytest

import subsequence
import subsequence.chords
import subsequence.constants
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequencer


PPQ = subsequence.constants.MIDI_QUARTER_NOTE


def _builder (length: float = 4.0) -> subsequence.pattern_builder.PatternBuilder:

	"""A standalone builder over a fresh pattern."""

	pattern = subsequence.pattern.Pattern(channel = 0, length = length)

	return subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		key = "C",
		scale = "ionian",
		rng = random.Random(1),
	)


def _pulses (builder: subsequence.pattern_builder.PatternBuilder) -> typing.List[int]:

	"""Every pulse the builder placed something at, notes and controls alike."""

	builder._finish_build()

	return sorted(
		[pulse for pulse, step in builder._pattern.steps.items() for _ in step.notes]
		+ [event.pulse for event in builder._pattern.cc_events]
		+ [event.pulse for event in getattr(builder._pattern, "osc_events", [])]
	)


# ---------------------------------------------------------------------------
# One position for every verb
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("place", [
	lambda p: p.note(60, beat = -1, duration = 1),
	lambda p: p.cc(74, 64, beat = -1),
	lambda p: p.pitch_bend(0.5, beat = -1),
	lambda p: p.program_change(3, beat = -1),
	lambda p: p.nrpn(1, 64, beat = -1),
	lambda p: p.rpn(0, 64, beat = -1),
	lambda p: p.sysex([1, 2], beat = -1),
	lambda p: p.osc("/x", 1, beat = -1),
	lambda p: p.motif(subsequence.Motif.cc(74, [64], beats = [0.0]), beat = -1),
	lambda p: p.chord([60, 64, 67], beat = -1, duration = 1),
])
def test_a_negative_beat_counts_from_the_end (place: typing.Callable[[typing.Any], None]) -> None:

	"""Beat -1 of a four-beat pattern is beat 3 — pulse 72 — whatever the verb."""

	builder = _builder()
	place(builder)

	placed = _pulses(builder)

	assert placed, "the verb placed nothing at all"
	assert set(placed) == {72}


@pytest.mark.parametrize("verb, expected", [
	("arpeggio", [72, 78, 84, 90]),
	("broken_chord", [72, 78, 84, 90]),
	("strum", [72, 78, 84]),
])
def test_a_figure_at_a_negative_beat_starts_that_far_from_the_end (verb: str, expected: typing.List[int]) -> None:

	"""chord(), arpeggio() and broken_chord() refused a negative beat, which 7200913 meant every verb to take (#3528).

	strum() already counted one from the end, so its case is a guard that held before as well.
	"""

	builder = _builder()
	triad = subsequence.chords.parse_chord("C")

	if verb == "arpeggio":
		builder.arpeggio([60, 64, 67], beat = -1, span = 1, spacing = 0.25)
	elif verb == "broken_chord":
		builder.broken_chord(triad, root = 60, order = [0, 1, 2], beat = -1, span = 1, spacing = 0.25)
	else:
		builder.strum([60, 64, 67], beat = -1, spacing = 0.25, duration = 0.25)

	assert _pulses(builder) == expected


@pytest.mark.parametrize("length, beat, expected", [
	(4.0, -1.0, 3.0),
	(4.0, -0.5, 3.5),
	(2.0, -0.5, 1.5),
	(4.0, -5.0, 3.0),		# any magnitude wraps
	(3.0, -1.0, 2.0),
])
def test_the_wrap_follows_the_pattern_s_own_length (length: float, beat: float, expected: float) -> None:

	"""It is the pattern's length that says where the end is, not a fixed bar."""

	builder = _builder(length)
	builder.cc(74, 64, beat = beat)

	assert _pulses(builder) == [int(expected * PPQ)]


def test_a_positive_beat_is_untouched () -> None:

	"""Nothing changes for the ordinary case."""

	builder = _builder()
	builder.cc(74, 64, beat = 1.5)

	assert _pulses(builder) == [36]


# ---------------------------------------------------------------------------
# Ramps, which have a length as well as a position
# ---------------------------------------------------------------------------

def test_a_ramp_starting_before_zero_keeps_its_length_and_crosses_the_end () -> None:

	"""It sounds over the cycle's end: the tail of this pattern into its head."""

	builder = _builder()
	builder.cc_ramp(74, 0, 127, beat_start = -1, beat_end = 1, resolution = 12)

	placed = _pulses(builder)

	assert placed == [0, 12, 24, 72, 84]
	assert all(0 <= pulse < 4 * PPQ for pulse in placed)


def test_a_ramp_starting_before_zero_still_ramps () -> None:

	"""Wrapping only the start left the span negative, and a negative span emits nothing."""

	builder = _builder()
	builder.cc_ramp(74, 0, 127, beat_start = -1, beat_end = 1, resolution = 12)

	values = [event.value for event in sorted(builder._pattern.cc_events, key = lambda e: e.pulse)]

	assert len(values) == 5
	assert values[0] != values[-1]


def test_a_ramp_inside_the_pattern_is_untouched () -> None:

	"""The ordinary ramp keeps every pulse it had."""

	builder = _builder()
	builder.cc_ramp(74, 0, 127, beat_start = 1, beat_end = 3, resolution = 12)

	assert _pulses(builder) == [24, 36, 48, 60, 72]


# ---------------------------------------------------------------------------
# The recording, which measures from the session's start
# ---------------------------------------------------------------------------

def test_a_recording_that_starts_with_silence_keeps_it (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""The origin is still pulse 0, so a piece that comes in on bar 2 still does."""

	filename = str(tmp_path / "late.mid")
	sequencer = subsequence.sequencer.Sequencer(record = True, record_filename = filename)
	sequencer.recorded_events.clear()

	sequencer._record_event(96, mido.Message("note_on", channel = 0, note = 60, velocity = 100))
	sequencer._record_event(120, mido.Message("note_off", channel = 0, note = 60, velocity = 0))
	sequencer.save_recording()

	first = [message for track in mido.MidiFile(filename).tracks for message in track if message.type == "note_on"][0]

	assert first.time == 96 * 20


def test_an_event_before_the_start_does_not_shift_the_file (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""A negative pulse became the origin's problem: everything after it moved late."""

	filename = str(tmp_path / "early.mid")
	sequencer = subsequence.sequencer.Sequencer(record = True, record_filename = filename)
	sequencer.recorded_events.clear()

	sequencer._record_event(-24, mido.Message("control_change", channel = 0, control = 74, value = 64))
	sequencer._record_event(0, mido.Message("note_on", channel = 0, note = 60, velocity = 100))
	sequencer._record_event(96, mido.Message("note_on", channel = 0, note = 62, velocity = 100))
	sequencer.save_recording()

	notes = []
	now = 0

	for track in mido.MidiFile(filename).tracks:
		now = 0
		for message in track:
			now += message.time
			if message.type == "note_on":
				notes.append((now, message.note))

	# The stray control sounds at the start, and the notes keep their own
	# ticks: 0 and 96 pulses.  Clamping its delta instead moved both late.
	assert [tick for tick, _ in notes] == [0, 96 * 20]
