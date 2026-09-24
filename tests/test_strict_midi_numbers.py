"""A number MIDI cannot carry is refused where it is written (#3004).

`p.cc(200, 64)`, `note(140)`, `velocity=300` and a pitch of -3 were all stored
happily, and then rejected by mido at every single send — logged as "MIDI send
failed (device may be disconnected)", so the composer looked at their cables.
One run of `hit_steps(velocity=(100, 160))` dropped five notes of eight.

And the library produced them by itself: `branch_sequence([78, 40, 69], 2, 1)`
gave 154, `quantize_pitch(127, C# major)` gave 128, and
`chord("C", root=110, count=8)` reached 132 and 136.

The technical call in #2957: strict numbers.  What a person writes raises,
naming the value; what a generator computes is folded into range — pitches by
octaves, so they keep the note they are.
"""

import logging
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.intervals
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequence_utils


def _builder () -> typing.Tuple[subsequence.pattern.Pattern, typing.Any]:

	"""A pattern and a builder to write into it."""

	pattern = subsequence.pattern.Pattern(channel = 1, length = 4)

	return pattern, subsequence.pattern_builder.PatternBuilder(pattern = pattern, cycle = 0)


# ---------------------------------------------------------------------------
# What a person writes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pitch", [128, 140, -1, -3, 1000])
def test_a_pitch_outside_the_range_is_refused (pitch: int) -> None:

	"""It was stored and then dropped at every cycle."""

	_, p = _builder()

	with pytest.raises(ValueError, match = "pitch must be 0–127"):
		p.note(pitch, beat = 0.0)


@pytest.mark.parametrize("velocity", [128, 300, -1])
def test_a_velocity_outside_the_range_is_refused (velocity: int) -> None:

	"""`velocity=300` reached mido once per note and was thrown away each time."""

	_, p = _builder()

	with pytest.raises(ValueError, match = "velocity must be 0–127"):
		p.note(60, beat = 0.0, velocity = velocity)


@pytest.mark.parametrize("control", [128, 200, -1])
def test_a_cc_number_outside_the_range_is_refused (control: int) -> None:

	"""NRPN and RPN numbers were checked; CC numbers were not, though cc() said 0–127."""

	_, p = _builder()

	with pytest.raises(ValueError, match = "CC number must be 0–127"):
		p.cc(control, 64, beat = 0.0)


def test_a_cc_name_mapped_to_a_bad_number_is_refused () -> None:

	"""The map is written by hand too, and a name hides the number behind it."""

	pattern = subsequence.pattern.Pattern(channel = 1, length = 4)
	p = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern, cycle = 0, cc_name_map = {"filter": 200},
	)

	with pytest.raises(ValueError, match = "CC number must be 0–127"):
		p.cc("filter", 64, beat = 0.0)


def test_the_refusal_names_the_value () -> None:

	"""A message that does not say which number sends you hunting for it."""

	_, p = _builder()

	with pytest.raises(ValueError) as raised:
		p.note(140, beat = 0.0)

	assert "140" in str(raised.value)


@pytest.mark.parametrize("bad", [(100, 160), (0, 100), (-5, 60), [100, 200]])
def test_a_velocity_range_outside_one_to_127_is_refused (bad: typing.Any) -> None:

	"""`hit_steps(velocity=(100, 160))` dropped five notes of eight, intermittently.

	Both ends are checked, not the draw: a range whose top is out of reach
	fails only sometimes, which reads as a flaky pattern rather than an error.
	A velocity of 0 is a note-off, not a quiet note, so the floor is 1.
	"""

	_, p = _builder()

	with pytest.raises(ValueError, match = "velocity range"):
		p.note(60, beat = 0.0, velocity = bad)


@pytest.mark.parametrize("good", [(1, 127), (60, 90), [40, 80]])
def test_a_velocity_range_inside_the_range_is_accepted (good: typing.Any) -> None:

	"""The refusal must not catch what people actually write."""

	pattern, p = _builder()
	p.note(60, beat = 0.0, velocity = good)
	p._finish_build()

	drawn = [note.velocity for step in pattern.steps.values() for note in step.notes]

	assert len(drawn) == 1
	assert good[0] <= drawn[0] <= good[1]


@pytest.mark.parametrize("pitch, velocity", [(0, 1), (127, 127), (60, 0)])
def test_the_edges_of_the_range_are_accepted (pitch: int, velocity: int) -> None:

	"""0 and 127 are notes; velocity 0 is a release, and writing one is allowed."""

	pattern, p = _builder()
	p.note(pitch, beat = 0.0, velocity = velocity)
	p._finish_build()

	assert [(n.pitch, n.velocity) for s in pattern.steps.values() for n in s.notes] == [(pitch, velocity)]


def test_a_cc_value_out_of_range_still_clamps () -> None:

	"""Deliberately unchanged: a computed value running past an end is a controller
	at its limit, and every sibling verb clamps it the same way."""

	pattern, p = _builder()
	p.cc(74, 300, beat = 0.0)
	p.cc(74, -50, beat = 1.0)
	p._finish_build()

	assert sorted(event.value for event in pattern.cc_events) == [0, 127]


@pytest.mark.parametrize("parameter, allowed", [(9000, True), (16383, True), (20000, False), (-1, False)])
def test_an_nrpn_number_keeps_its_own_fourteen_bit_range (parameter: int, allowed: bool) -> None:

	"""NRPN is a 14-bit parameter, so 9000 is perfectly valid — this is not 0–127."""

	_, p = _builder()

	if allowed:
		p.nrpn(parameter, 64, beat = 0.0)
	else:
		with pytest.raises(ValueError, match = "0–16383"):
			p.nrpn(parameter, 64, beat = 0.0)


# ---------------------------------------------------------------------------
# What a generator computes
# ---------------------------------------------------------------------------

def test_branch_sequence_folds_its_variations_into_range () -> None:

	"""`branch_sequence([78, 40, 69], 2, 1)` gave [78, 154, 96]."""

	assert subsequence.sequence_utils.branch_sequence([78, 40, 69], 2, 1) == [78, 118, 96]


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 4, 5])
def test_branch_sequence_never_leaves_the_range (depth: int) -> None:

	"""Every path of every depth, over a trunk near the top of the keyboard."""

	for path in range(2 ** depth if depth else 1):
		for pitch in subsequence.sequence_utils.branch_sequence([78, 40, 69], depth, path):
			assert 0 <= pitch <= 127, f"depth {depth} path {path} produced {pitch}"


def test_a_folded_pitch_keeps_its_pitch_class () -> None:

	"""Folding by octaves, not clamping: a melody must not become a wall at 127."""

	assert subsequence.sequence_utils.fold_to_midi_range(154) == 118
	assert 154 % 12 == 118 % 12
	assert subsequence.sequence_utils.fold_to_midi_range(-3) == 9
	assert subsequence.sequence_utils.fold_to_midi_range(64) == 64


def test_quantize_pitch_stays_inside_the_range_at_the_top () -> None:

	"""`quantize_pitch(127, C# major)` answered 128, which is not a note."""

	c_sharp_major = subsequence.intervals.scale_pitch_classes(1, "major")

	assert subsequence.intervals.quantize_pitch(127, c_sharp_major) == 126


@pytest.mark.parametrize("root_pc", range(12))
def test_quantize_pitch_never_leaves_the_range (root_pc: int) -> None:

	"""Every pitch, every key — at both ends, which is where there is nowhere to go."""

	scale = subsequence.intervals.scale_pitch_classes(root_pc, "major")

	for pitch in list(range(0, 4)) + list(range(124, 128)):
		snapped = subsequence.intervals.quantize_pitch(pitch, scale)
		assert 0 <= snapped <= 127, f"pitch {pitch} in key {root_pc} snapped to {snapped}"


def test_quantize_pitch_will_not_snap_below_zero (caplog: pytest.LogCaptureFixture) -> None:

	"""A sparse custom scale can put the only near note below the bottom of the range.

	A major scale never reaches this — it is dense enough that the upward
	search, which is preferred, always wins near the floor.  With `{10}` alone,
	pitch 1's only note within six semitones is three below it, at -2.  Better
	to hand back the pitch unquantized, and say so, than a number that cannot
	be sent.
	"""

	with caplog.at_level(logging.WARNING):
		snapped = subsequence.intervals.quantize_pitch(1, [10])

	assert snapped == 1
	assert "no scale note within" in caplog.text


def test_a_chord_stacked_past_the_ceiling_folds () -> None:

	"""`chord("C", root=110, count=8)` reached 132 and 136.

	Folded, they landed on 120 and 124, which the chord already held, and are left out (#3529).
	"""

	tones = subsequence.chords.parse_chord("C").tones(110, count = 8)

	assert tones == [108, 112, 115, 120, 124, 127]
	assert all(0 <= tone <= 127 for tone in tones)


@pytest.mark.parametrize("root", [0, 4, 60, 110, 120, 127])
@pytest.mark.parametrize("count", [3, 6, 8, 12])
def test_a_chord_never_leaves_the_range (root: int, count: int) -> None:

	"""Anywhere on the keyboard, however many tones are asked for."""

	for tone in subsequence.chords.parse_chord("Cmaj7").tones(root, count = count):
		assert 0 <= tone <= 127, f"root {root} count {count} produced {tone}"


@pytest.mark.parametrize("name", ["C", "Cm", "Caug", "Csus4", "Cmaj7", "C7", "Cm7", "Cdim7"])
@pytest.mark.parametrize("root", [0, 4, 60, 110, 120, 127])
@pytest.mark.parametrize("count", [None, 3, 6, 8, 12])
def test_a_voicing_never_doubles_a_pitch (name: str, root: int, count: typing.Optional[int]) -> None:

	"""One pitch twice on one channel is one note that the first note-off ends (#3529)."""

	tones = subsequence.chords.parse_chord(name).tones(root, count = count)

	assert len(tones) == len(set(tones)), f"{name} from {root}, count {count}: {tones}"


def test_the_chord_verb_sends_each_pitch_once () -> None:

	"""What reaches the channel: six distinct notes of C major fit between 108 and 127."""

	pattern = subsequence.pattern.Pattern(channel = 0, length = 4)
	builder = subsequence.pattern_builder.PatternBuilder(pattern = pattern, cycle = 0, default_grid = 16)
	builder.chord(subsequence.chords.parse_chord("C"), root = 110, count = 8)

	assert sorted(note.pitch for step in pattern.steps.values() for note in step.notes) == [108, 112, 115, 120, 124, 127]


def test_an_ordinary_chord_is_untouched () -> None:

	"""Folding must not move a chord that was already where it should be."""

	assert subsequence.chords.parse_chord("C").tones(60) == [60, 64, 67]
	assert subsequence.chords.parse_chord("C").tones(60, count = 5) == [60, 64, 67, 72, 76]


def test_recaman_is_left_as_the_integer_sequence_it_is () -> None:

	"""It generates Recamán's sequence, not pitches, and folding would be a lie.

	The review reached 131 by mapping it onto a 96–107 pool, which is the
	caller's arithmetic — and a pitch written out of range is refused above.
	"""

	assert subsequence.sequence_utils.recaman(8) == [0, 1, 3, 6, 2, 7, 13, 20]


# ---------------------------------------------------------------------------
# If one gets through anyway
# ---------------------------------------------------------------------------

class _Refusing:

	"""A port standing in for mido's own refusal of a byte it cannot send."""

	def send (self, message: typing.Any) -> None:
		raise ValueError("data byte must be in range 0..127")


def _dispatch (event: typing.Any, caplog: pytest.LogCaptureFixture) -> str:

	"""Push one event at a port that refuses it, and hand back what was logged."""

	import subsequence.sequencer

	sequencer = subsequence.sequencer.Sequencer(output_device_name = "Dummy MIDI", initial_bpm = 120)
	sequencer.midi_out = _Refusing()

	with caplog.at_level(logging.ERROR):
		sequencer._dispatch_with_compensation(event)

	return caplog.text


def test_a_send_that_fails_on_a_bad_number_says_which_number (
	patch_midi: None, caplog: pytest.LogCaptureFixture,
) -> None:

	"""It blamed the cable, and people went and checked their cables."""

	import subsequence.sequencer

	logged = _dispatch(subsequence.sequencer.MidiEvent(
		pulse = 0, message_type = "note_on", channel = 1, note = 140, velocity = 100, device = 0,
	), caplog)

	assert "140" in logged, logged
	assert "note" in logged
	assert "disconnected" not in logged


def test_a_send_that_fails_for_another_reason_still_suspects_the_device (
	patch_midi: None, caplog: pytest.LogCaptureFixture,
) -> None:

	"""A port that has gone away is the other thing this message is for."""

	import subsequence.sequencer

	logged = _dispatch(subsequence.sequencer.MidiEvent(
		pulse = 0, message_type = "note_on", channel = 1, note = 60, velocity = 100, device = 0,
	), caplog)

	assert "disconnected" in logged, logged


def test_the_failure_names_a_bad_velocity_too (
	patch_midi: None, caplog: pytest.LogCaptureFixture,
) -> None:

	"""Whichever of the numbers it was."""

	import subsequence.sequencer

	logged = _dispatch(subsequence.sequencer.MidiEvent(
		pulse = 0, message_type = "note_on", channel = 1, note = 60, velocity = 200, device = 0,
	), caplog)

	assert "velocity 200" in logged, logged
