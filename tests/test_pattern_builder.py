import pytest

import subsequence.chords
import subsequence.constants
import subsequence.pattern
import subsequence.pattern_builder


def _make_builder (channel: int = 0, length: int = 4, drum_note_map: dict = None) -> tuple:

	"""
	Create a Pattern and PatternBuilder pair for testing.
	"""

	pattern = subsequence.pattern.Pattern(channel=channel, length=length)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		drum_note_map = drum_note_map
	)

	return pattern, builder


def test_note_places_at_beat () -> None:

	"""
	A note placed at beat 1.0 should appear at the correct pulse position.
	"""

	pattern, builder = _make_builder()

	builder.note(60, beat=1.0, velocity=100, duration=0.5)

	expected_pulse = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	assert expected_pulse in pattern.steps
	assert len(pattern.steps[expected_pulse].notes) == 1
	assert pattern.steps[expected_pulse].notes[0].pitch == 60
	assert pattern.steps[expected_pulse].notes[0].velocity == 100


def test_note_negative_beat_wraps () -> None:

	"""
	A negative beat value should wrap to the end of the pattern.
	"""

	pattern, builder = _make_builder(length=4)

	builder.note(60, beat=-0.5, velocity=85)

	expected_beat = 4 - 0.5
	expected_pulse = int(expected_beat * subsequence.constants.MIDI_QUARTER_NOTE)

	assert expected_pulse in pattern.steps


def test_hit_places_multiple_beats () -> None:

	"""
	Hits placed at beats 1 and 3 should create notes at both positions.
	"""

	pattern, builder = _make_builder()

	builder.hit(38, beats=[1, 3], velocity=100)

	pulse_1 = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)
	pulse_3 = int(3.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	assert pulse_1 in pattern.steps
	assert pulse_3 in pattern.steps

	assert pattern.steps[pulse_1].notes[0].pitch == 38
	assert pattern.steps[pulse_3].notes[0].pitch == 38


def test_fill_covers_pattern () -> None:

	"""
	Fill with step=0.25 over a 4-beat pattern should place 16 notes.
	"""

	pattern, builder = _make_builder(length=4)

	builder.fill(60, step=0.25, velocity=90, duration=0.2)

	# 4 beats / 0.25 step = 16 notes
	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 16


def test_fill_invalid_step_raises () -> None:

	"""
	Fill with non-positive step should raise ValueError.
	"""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError):
		builder.fill(60, step=0)

	with pytest.raises(ValueError):
		builder.fill(60, step=-1)


def test_chord_places_all_tones () -> None:

	"""
	A major chord should place 3 notes at beat 0.
	"""

	pattern, builder = _make_builder()

	chord = subsequence.chords.Chord(root_pc=4, quality="major")

	builder.chord(chord, root=52, velocity=90)

	# Beat 0 = pulse 0
	assert 0 in pattern.steps
	assert len(pattern.steps[0].notes) == 3

	pitches = sorted([n.pitch for n in pattern.steps[0].notes])

	assert pitches == [52, 56, 59]


def test_chord_sustain () -> None:

	"""
	Sustain=True should set note duration to the full pattern length.
	"""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	builder.chord(chord, root=60, velocity=90, sustain=True)

	expected_duration = int(4 * subsequence.constants.MIDI_QUARTER_NOTE)

	for note in pattern.steps[0].notes:
		assert note.duration == expected_duration


def test_swing_applies () -> None:

	"""
	Swing should modify step positions in the pattern.
	"""

	pattern, builder = _make_builder(length=2)

	# Place notes on every 8th note
	for i in range(4):
		builder.note(60, beat=i * 0.5, velocity=100, duration=0.25)

	positions_before = set(pattern.steps.keys())

	builder.swing(2.0)

	positions_after = set(pattern.steps.keys())

	# Swing should move at least one off-beat position
	assert positions_before != positions_after


def test_drum_note_map_resolves_strings () -> None:

	"""
	String pitches should resolve to MIDI notes via the drum note map.
	"""

	drum_map = {"kick": 36, "snare": 38}
	pattern, builder = _make_builder(drum_note_map=drum_map)

	builder.note("kick", beat=0, velocity=100)
	builder.note("snare", beat=1, velocity=100)

	notes_at_0 = pattern.steps[0].notes
	pulse_1 = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)
	notes_at_1 = pattern.steps[pulse_1].notes

	assert notes_at_0[0].pitch == 36
	assert notes_at_1[0].pitch == 38


def test_drum_note_map_missing_raises () -> None:

	"""
	An unknown string pitch should raise a clear error.
	"""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(drum_note_map=drum_map)

	with pytest.raises(ValueError, match="Unknown drum name"):
		builder.note("cymbal", beat=0)


def test_string_pitch_without_map_raises () -> None:

	"""
	String pitches without a drum note map should raise a clear error.
	"""

	pattern, builder = _make_builder(drum_note_map=None)

	with pytest.raises(ValueError, match="requires a drum_note_map"):
		builder.note("kick", beat=0)


def test_integer_pitch_bypasses_map () -> None:

	"""
	Integer pitches should work regardless of drum note map presence.
	"""

	pattern, builder = _make_builder(drum_note_map=None)

	builder.note(60, beat=0, velocity=100)

	assert 0 in pattern.steps
	assert pattern.steps[0].notes[0].pitch == 60


def test_chord_tones_method () -> None:

	"""
	Chord.tones() should return MIDI note numbers for all chord tones.
	"""

	chord = subsequence.chords.Chord(root_pc=4, quality="major")

	tones = chord.tones(root=76)

	assert tones == [76, 80, 83]


def test_chord_tones_seventh () -> None:

	"""
	Chord.tones() on a dominant 7th should return 4 notes.
	"""

	chord = subsequence.chords.Chord(root_pc=7, quality="dominant_7th")

	tones = chord.tones(root=55)

	assert tones == [55, 59, 62, 65]


# --- Phase 3: Rhythm Helpers ---


def test_euclidean_generates_rhythm () -> None:

	"""
	Euclidean with 4 pulses over 16 steps should place exactly 4 hits.
	"""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.euclidean("kick", pulses=4, velocity=100)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 4


def test_bresenham_generates_rhythm () -> None:

	"""
	Bresenham with 3 pulses over 16 steps should place exactly 3 hits.
	"""

	drum_map = {"snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham("snare", pulses=3, velocity=110)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 3


def test_dropout_removes_some_hits () -> None:

	"""
	Dropout at 0.5 probability with a seeded RNG should remove approximately half.
	"""

	import random

	pattern, builder = _make_builder(length=4)

	builder.fill(60, step=0.25, velocity=100)

	total_before = sum(len(step.notes) for step in pattern.steps.values())

	assert total_before == 16

	seeded_rng = random.Random(42)

	builder.dropout(probability=0.5, rng=seeded_rng)

	total_after = sum(len(step.notes) for step in pattern.steps.values())

	assert 0 < total_after < total_before


def test_velocity_shape_applies () -> None:

	"""
	Velocity shaping should change note velocities to non-uniform values.
	"""

	pattern, builder = _make_builder(length=2)

	builder.fill(60, step=0.5, velocity=100)

	builder.velocity_shape(low=40, high=120)

	velocities = []

	for step in pattern.steps.values():
		for note in step.notes:
			velocities.append(note.velocity)

	# All velocities should be within range
	assert all(40 <= v <= 120 for v in velocities)

	# Velocities should not all be the same (van der Corput is non-uniform)
	assert len(set(velocities)) > 1


def test_arpeggio_cycles_pitches () -> None:

	"""
	Arpeggio with 3 pitches over 4 beats at step=0.5 should produce 8 notes cycling through the pitches.
	"""

	pattern, builder = _make_builder(length=4)

	builder.arpeggio([60, 64, 67], step=0.5, velocity=90)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 8

	# Verify pitch cycling
	positions = sorted(pattern.steps.keys())
	pitches = [pattern.steps[pos].notes[0].pitch for pos in positions]

	expected_pitches = [60, 64, 67, 60, 64, 67, 60, 64]

	assert pitches == expected_pitches


def test_arpeggio_fills_pattern () -> None:

	"""
	Arpeggio with step=0.25 over 4 beats should produce 16 notes.
	"""

	pattern, builder = _make_builder(length=4)

	builder.arpeggio([60, 64, 67], step=0.25, velocity=90)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 16


def test_arpeggio_empty_pitches_raises () -> None:

	"""
	Arpeggio with empty pitches list should raise ValueError.
	"""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError, match="Pitches list cannot be empty"):
		builder.arpeggio([], step=0.25)


def test_arpeggio_invalid_step_raises () -> None:

	"""
	Arpeggio with non-positive step should raise ValueError.
	"""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError, match="Step must be positive"):
		builder.arpeggio([60, 64, 67], step=0)

	with pytest.raises(ValueError, match="Step must be positive"):
		builder.arpeggio([60, 64, 67], step=-1)

