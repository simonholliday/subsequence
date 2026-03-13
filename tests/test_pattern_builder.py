import random

import pytest

import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.constants.velocity
import subsequence.melodic_state
import subsequence.pattern
import subsequence.pattern_builder


def _make_builder (channel: int = 0, length: float = 4, drum_note_map: dict = None, default_grid: int = None) -> tuple:

	"""
	Create a Pattern and PatternBuilder pair for testing.

	When *default_grid* is not given it is derived from *length* using
	sixteenth-note resolution, matching the composition decorator fallback.
	"""

	if default_grid is None:
		default_grid = round(length / subsequence.constants.durations.SIXTEENTH)

	pattern = subsequence.pattern.Pattern(channel=channel, length=length)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		drum_note_map = drum_note_map,
		default_grid = default_grid
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
	Fill with spacing=0.25 over a 4-beat pattern should place 16 notes.
	"""

	pattern, builder = _make_builder(length=4)

	builder.fill(60, spacing=0.25, velocity=90, duration=0.2)

	# 4 beats / 0.25 step = 16 notes
	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 16


def test_fill_invalid_step_raises () -> None:

	"""
	Fill with non-positive step should raise ValueError.
	"""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError):
		builder.fill(60, spacing=0)

	with pytest.raises(ValueError):
		builder.fill(60, spacing=-1)


def test_duck_map_builds_multiplier_list () -> None:

	"""
	duck_map should return floor at trigger steps and 1.0 elsewhere.
	"""

	_, builder = _make_builder(default_grid=4)

	result = builder.duck_map(steps=[0, 2], floor=0.0)

	assert result == [0.0, 1.0, 0.0, 1.0]


def test_duck_map_partial_floor () -> None:

	"""
	duck_map should write the given floor value, not just 0.0.
	"""

	_, builder = _make_builder(default_grid=4)

	result = builder.duck_map(steps=[1], floor=0.5)

	assert result == [1.0, 0.5, 1.0, 1.0]


def test_scale_velocities_applies_factors () -> None:

	"""
	scale_velocities should multiply each note's velocity by the per-step factor.
	"""

	pattern, builder = _make_builder(default_grid=4, length=4)

	builder.sequence(steps=[0, 1, 2, 3], pitches=60, velocities=100, durations=0.1)
	builder.scale_velocities([0.0, 0.5, 1.0, 1.0])

	pps = subsequence.constants.MIDI_QUARTER_NOTE

	assert pattern.steps[0].notes[0].velocity == 0
	assert pattern.steps[pps].notes[0].velocity == 50
	assert pattern.steps[pps * 2].notes[0].velocity == 100


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
	p.swing() takes a percentage: 67 ≈ triplet swing.
	"""

	pattern, builder = _make_builder(length=2)

	# Place notes on every 8th note
	for i in range(4):
		builder.note(60, beat=i * 0.5, velocity=100, duration=0.25)

	positions_before = set(pattern.steps.keys())

	builder.swing(67, grid=0.5)  # triplet swing on 8th-note grid

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


def test_note_on_adds_raw_event () -> None:

	"""
	p.note_on() should append to pattern.raw_note_events without creating steps.
	"""

	pattern, builder = _make_builder()

	builder.note_on(60, beat=1.0, velocity=95)

	assert not pattern.steps
	assert len(pattern.raw_note_events) == 1
	event = pattern.raw_note_events[0]
	assert event.message_type == 'note_on'
	assert event.pulse == int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)
	assert event.pitch == 60
	assert event.velocity == 95


def test_note_off_adds_raw_event () -> None:

	"""
	p.note_off() should append to pattern.raw_note_events without creating steps.
	"""

	pattern, builder = _make_builder()

	builder.note_off(60, beat=2.0)

	assert not pattern.steps
	assert len(pattern.raw_note_events) == 1
	event = pattern.raw_note_events[0]
	assert event.message_type == 'note_off'
	assert event.pulse == int(2.0 * subsequence.constants.MIDI_QUARTER_NOTE)
	assert event.pitch == 60
	assert event.velocity == 0


def test_drone_adds_raw_event_at_zero () -> None:

	"""
	p.drone() should alias p.note_on() at beat 0.0 by default.
	"""

	pattern, builder = _make_builder()
	builder.drone(36, velocity=85)

	assert len(pattern.raw_note_events) == 1
	event = pattern.raw_note_events[0]
	assert event.message_type == 'note_on'
	assert event.pulse == 0
	assert event.pitch == 36
	assert event.velocity == 85


def test_drone_off_adds_raw_event_at_zero () -> None:

	"""
	p.drone_off() should alias p.note_off() at beat 0.0.
	"""

	pattern, builder = _make_builder()
	builder.drone_off(36)

	assert len(pattern.raw_note_events) == 1
	event = pattern.raw_note_events[0]
	assert event.message_type == 'note_off'
	assert event.pulse == 0
	assert event.pitch == 36
	assert event.velocity == 0


def test_silence_adds_all_notes_sound_off () -> None:

	"""
	p.silence() should append CC 123 and 120 messages at beat 0.0 by default.
	"""

	pattern, builder = _make_builder()
	builder.silence(beat=1.0)

	assert len(pattern.cc_events) == 2
	
	cc123_event = pattern.cc_events[0]
	assert cc123_event.message_type == 'control_change'
	assert cc123_event.control == 123
	assert cc123_event.value == 0
	assert cc123_event.pulse == int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	cc120_event = pattern.cc_events[1]
	assert cc120_event.message_type == 'control_change'
	assert cc120_event.control == 120
	assert cc120_event.value == 0
	assert cc120_event.pulse == int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)


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

	builder.fill(60, spacing=0.25, velocity=100)

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

	builder.fill(60, spacing=0.5, velocity=100)

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
	Arpeggio with 3 pitches over 4 beats at spacing=0.5 should produce 8 notes cycling through the pitches.
	"""

	pattern, builder = _make_builder(length=4)

	builder.arpeggio([60, 64, 67], spacing=0.5, velocity=90)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 8

	# Verify pitch cycling
	positions = sorted(pattern.steps.keys())
	pitches = [pattern.steps[pos].notes[0].pitch for pos in positions]

	expected_pitches = [60, 64, 67, 60, 64, 67, 60, 64]

	assert pitches == expected_pitches


def test_arpeggio_fills_pattern () -> None:

	"""
	Arpeggio with spacing=0.25 over 4 beats should produce 16 notes.
	"""

	pattern, builder = _make_builder(length=4)

	builder.arpeggio([60, 64, 67], spacing=0.25, velocity=90)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 16


def test_arpeggio_empty_pitches_raises () -> None:

	"""
	Arpeggio with empty pitches list should raise ValueError.
	"""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError, match="Pitches list cannot be empty"):
		builder.arpeggio([], spacing=0.25)


def test_arpeggio_invalid_step_raises () -> None:

	"""
	Arpeggio with non-positive step should raise ValueError.
	"""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError, match="Spacing must be positive"):
		builder.arpeggio([60, 64, 67], spacing=0)

	with pytest.raises(ValueError, match="Spacing must be positive"):
		builder.arpeggio([60, 64, 67], spacing=-1)


# --- Phase 4: Step-Based Hits ---


def test_hit_steps_places_at_correct_pulses () -> None:

	"""Steps 0, 4, 8, 12 on a 16-step / 4-beat grid should map to beats 0, 1, 2, 3."""

	pattern, builder = _make_builder(length=4)

	builder.hit_steps(60, steps=[0, 4, 8, 12], velocity=127)

	expected_pulses = [
		int(0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(1 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(2 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(3 * subsequence.constants.MIDI_QUARTER_NOTE),
	]

	assert sorted(pattern.steps.keys()) == expected_pulses

	for pulse in expected_pulses:
		assert pattern.steps[pulse].notes[0].pitch == 60
		assert pattern.steps[pulse].notes[0].velocity == 127


def test_hit_steps_with_drum_note_map () -> None:

	"""String pitches should resolve via the drum note map in hit_steps."""

	drum_map = {"kick": 36, "snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.hit_steps("kick", steps=[0, 4, 8, 12], velocity=127)

	assert 0 in pattern.steps
	assert pattern.steps[0].notes[0].pitch == 36


def test_hit_steps_custom_grid () -> None:

	"""A custom grid of 8 on a 4-beat pattern should place steps at half-beat intervals."""

	pattern, builder = _make_builder(length=4)

	builder.hit_steps(60, steps=[0, 2, 4, 6], velocity=100, grid=8)

	# step_duration = 4 / 8 = 0.5 beats per step
	expected_pulses = [
		int(0.0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(2.0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(3.0 * subsequence.constants.MIDI_QUARTER_NOTE),
	]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_hit_steps_default_grid_from_length () -> None:

	"""Without an explicit grid, a 6-sixteenth-note pattern should auto-derive grid=6."""

	pattern, builder = _make_builder(length=1.5)  # 6 * dur.SIXTEENTH = 1.5 beats

	builder.hit_steps(60, steps=[0, 3], velocity=100)

	# step_duration = 1.5 / 6 = 0.25 beats per step (sixteenth notes)
	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected_pulses = [
		int(0.0 * ppq),   # step 0 → beat 0.0
		int(0.75 * ppq),  # step 3 → beat 0.75
	]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_hit_steps_default_grid_from_unit () -> None:

	"""When default_grid is set explicitly (as the decorator does with unit), the grid matches."""

	dur = subsequence.constants.durations
	beat_length = 6 * dur.SIXTEENTH  # 1.5 beats
	pattern, builder = _make_builder(length=beat_length, default_grid=6)

	builder.hit_steps(60, steps=[0, 3], velocity=100)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected_pulses = [
		int(0.0 * ppq),
		int(0.75 * ppq),
	]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_hit_steps_triplet_default_grid () -> None:

	"""A triplet-based pattern with explicit default_grid avoids the SIXTEENTH derivation bug."""

	dur = subsequence.constants.durations
	beat_length = 4 * dur.TRIPLET_EIGHTH  # ~2.667 beats
	pattern, builder = _make_builder(length=beat_length, default_grid=4)

	builder.hit_steps(60, steps=[0, 2], velocity=100)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	step_dur = beat_length / 4  # one triplet eighth per step
	expected_pulses = [
		int(0 * step_dur * ppq),
		int(2 * step_dur * ppq),
	]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_hit_steps_backbeat_positions () -> None:

	"""Steps 4 and 12 on a 16-step grid should place notes at beats 1 and 3."""

	pattern, builder = _make_builder(length=4)

	builder.hit_steps(38, steps=[4, 12], velocity=100)

	pulse_1 = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)
	pulse_3 = int(3.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	assert sorted(pattern.steps.keys()) == [pulse_1, pulse_3]


# --- Probability and RNG ---


def test_hit_steps_probability_one_places_all () -> None:

	"""probability=1.0 should place all hits (default behaviour)."""

	pattern, builder = _make_builder(length=4)

	builder.hit_steps(60, steps=[0, 4, 8, 12], velocity=100, probability=1.0)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 4


def test_hit_steps_probability_zero_places_none () -> None:

	"""probability=0.0 should place no hits."""

	pattern, builder = _make_builder(length=4)

	builder.hit_steps(60, steps=[0, 4, 8, 12], velocity=100, probability=0.0)

	assert len(pattern.steps) == 0


def test_hit_steps_probability_partial () -> None:

	"""Intermediate probability should place some but not all hits."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		rng = random.Random(42)
	)

	builder.hit_steps(60, steps=list(range(16)), velocity=100, probability=0.5)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert 0 < total_notes < 16


def test_euclidean_with_rng_deterministic () -> None:

	"""Euclidean with dropout and a seeded rng should be deterministic."""

	def build_with_seed (seed: int) -> set:

		pattern = subsequence.pattern.Pattern(channel=0, length=4)

		builder = subsequence.pattern_builder.PatternBuilder(
			pattern = pattern,
			cycle = 0,
			rng = random.Random(seed)
		)

		builder.euclidean(60, pulses=8, dropout=0.3)

		return set(pattern.steps.keys())

	run_1 = build_with_seed(42)
	run_2 = build_with_seed(42)
	run_3 = build_with_seed(99)

	assert run_1 == run_2
	assert run_1 != run_3  # different seed should (almost certainly) differ


def test_bresenham_with_rng_deterministic () -> None:

	"""Bresenham with dropout and a seeded rng should be deterministic."""

	def build_with_seed (seed: int) -> set:

		pattern = subsequence.pattern.Pattern(channel=0, length=4)

		builder = subsequence.pattern_builder.PatternBuilder(
			pattern = pattern,
			cycle = 0,
			rng = random.Random(seed)
		)

		builder.bresenham(60, pulses=8, dropout=0.3)

		return set(pattern.steps.keys())

	run_1 = build_with_seed(42)
	run_2 = build_with_seed(42)

	assert run_1 == run_2


def test_builder_rng_available () -> None:

	"""Builder should expose an rng attribute."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		rng = random.Random(42)
	)

	assert isinstance(builder.rng, random.Random)

	# Should produce deterministic values.
	val = builder.rng.random()
	expected = random.Random(42).random()

	assert val == expected


def test_builder_rng_default_unseeded () -> None:

	"""When no rng is provided, builder should create a fresh Random."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	assert isinstance(builder.rng, random.Random)


def test_dropout_uses_builder_rng () -> None:

	"""dropout() without explicit rng should use self.rng for determinism."""

	def build_with_seed (seed: int) -> int:

		pattern = subsequence.pattern.Pattern(channel=0, length=4)

		builder = subsequence.pattern_builder.PatternBuilder(
			pattern = pattern,
			cycle = 0,
			rng = random.Random(seed)
		)

		builder.fill(60, spacing=0.25, velocity=100)
		builder.dropout(probability=0.5)

		return sum(len(step.notes) for step in pattern.steps.values())

	run_1 = build_with_seed(42)
	run_2 = build_with_seed(42)

	assert run_1 == run_2


# --- p.grid property ---


def test_grid_property_default () -> None:

	"""p.grid returns 16 for a standard 4-beat pattern."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		default_grid = 16
	)

	assert builder.grid == 16


def test_grid_property_custom () -> None:

	"""p.grid returns the grid set by a unit-based pattern."""

	pattern = subsequence.pattern.Pattern(channel=0, length=1.5)  # 6 * SIXTEENTH
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		default_grid = 6
	)

	assert builder.grid == 6



def test_float_length_hit_steps () -> None:

	"""hit_steps should work with a float pattern length."""

	pattern = subsequence.pattern.Pattern(channel=0, length=10.5)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	# 16-step grid over 10.5 beats: step_duration = 10.5/16 = 0.65625
	builder.hit_steps(60, steps=[0, 4, 8, 12], velocity=100)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 4


def test_float_length_fill () -> None:

	"""fill should work with a float pattern length."""

	pattern = subsequence.pattern.Pattern(channel=0, length=3.5)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	# spacing=0.5 over 3.5 beats = 7 notes (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
	builder.fill(60, spacing=0.5, velocity=100)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 7


def test_float_length_euclidean () -> None:

	"""euclidean should work with a float pattern length."""

	pattern = subsequence.pattern.Pattern(channel=0, length=10.5)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	# int(10.5 * 4) = 42 steps, 5 pulses
	builder.euclidean(60, pulses=5, velocity=100)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 5


def test_float_length_bresenham () -> None:

	"""bresenham should work with a float pattern length."""

	pattern = subsequence.pattern.Pattern(channel=0, length=5.5)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	# int(5.5 * 4) = 22 steps, 3 pulses
	builder.bresenham(60, pulses=3, velocity=100)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 3


def test_set_length_updates_pattern () -> None:

	"""set_length should change the underlying pattern's length."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	assert pattern.length == 4

	builder.set_length(8)

	assert pattern.length == 8


def test_set_length_affects_fill () -> None:

	"""After set_length, fill should use the new length."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	builder.set_length(2)
	builder.fill(60, spacing=0.5, velocity=100)

	# 2 beats / 0.5 step = 4 notes
	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 4


# --- Pattern Transforms ---


def test_reverse_mirrors_positions () -> None:

	"""reverse() should mirror note positions so the first note moves to the end."""

	pattern, builder = _make_builder(length=4)

	# Place notes at beats 0, 1, 2, 3 (pulses 0, 24, 48, 72).
	builder.hit(60, beats=[0, 1, 2, 3], velocity=100)

	builder.reverse()

	total_pulses = int(4 * subsequence.constants.MIDI_QUARTER_NOTE)  # 96
	positions = sorted(pattern.steps.keys())

	# Beat 0 (pulse 0) → pulse 95, beat 1 (pulse 24) → pulse 71, etc.
	expected = sorted([total_pulses - 1 - p for p in [0, 24, 48, 72]])

	assert positions == expected


def test_reverse_empty_pattern () -> None:

	"""reverse() on an empty pattern should be a no-op."""

	pattern, builder = _make_builder(length=4)

	builder.reverse()

	assert len(pattern.steps) == 0


def test_double_time_halves_positions () -> None:

	"""double_time() should compress notes into the first half with halved durations."""

	pattern, builder = _make_builder(length=4)

	# Place notes at beats 0, 1, 2, 3 (pulses 0, 24, 48, 72).
	builder.hit(60, beats=[0, 1, 2, 3], velocity=100, duration=0.5)

	builder.double_time()

	positions = sorted(pattern.steps.keys())

	# Positions should be halved: 0, 12, 24, 36.
	assert positions == [0, 12, 24, 36]

	# Durations should be halved too.
	original_duration = int(0.5 * subsequence.constants.MIDI_QUARTER_NOTE)  # 12

	for pos in positions:
		for note in pattern.steps[pos].notes:
			assert note.duration == original_duration // 2


def test_half_time_doubles_positions () -> None:

	"""half_time() should expand notes and drop those that exceed the pattern boundary."""

	pattern, builder = _make_builder(length=4)

	# Place notes at beats 0, 1, 2, 3 (pulses 0, 24, 48, 72).
	builder.hit(60, beats=[0, 1, 2, 3], velocity=100, duration=0.25)

	builder.half_time()

	total_pulses = int(4 * subsequence.constants.MIDI_QUARTER_NOTE)  # 96
	positions = sorted(pattern.steps.keys())

	# Doubled: 0, 48, 96, 144 - but 96 and 144 >= total_pulses, so dropped.
	assert positions == [0, 48]

	# Durations should be doubled.
	original_duration = int(0.25 * subsequence.constants.MIDI_QUARTER_NOTE)  # 6

	for pos in positions:
		for note in pattern.steps[pos].notes:
			assert note.duration == original_duration * 2


def test_shift_wraps_around () -> None:

	"""shift() should rotate note positions and wrap past the end back to the start."""

	pattern, builder = _make_builder(length=4)

	# Place notes at steps 0, 4, 8, 12 on a 16-step grid.
	builder.hit_steps(60, steps=[0, 4, 8, 12], velocity=100)

	# Shift by 4 steps = 1 beat = 24 pulses.
	builder.shift(4)

	positions = sorted(pattern.steps.keys())

	# Original: 0, 24, 48, 72 → shifted: 24, 48, 72, 0 (96 wraps to 0).
	assert positions == [0, 24, 48, 72]


def test_shift_negative () -> None:

	"""Negative shift should move notes earlier, wrapping from start to end."""

	pattern, builder = _make_builder(length=4)

	# Place a single note at beat 0 (pulse 0).
	builder.note(60, beat=0, velocity=100)

	# Shift by -4 steps = -24 pulses → wraps to 72.
	builder.shift(-4)

	assert 72 in pattern.steps
	assert 0 not in pattern.steps


def test_transpose_shifts_pitches () -> None:

	"""transpose() should shift all pitches by the given number of semitones."""

	pattern, builder = _make_builder(length=4)

	builder.note(60, beat=0, velocity=100)
	builder.note(64, beat=1, velocity=100)
	builder.note(67, beat=2, velocity=100)

	builder.transpose(12)

	pitches = sorted(
		note.pitch
		for step in pattern.steps.values()
		for note in step.notes
	)

	assert pitches == [72, 76, 79]


def test_transpose_clamps_to_midi_range () -> None:

	"""transpose() should clamp pitches to 0-127."""

	pattern, builder = _make_builder(length=4)

	# +20 would take 120 → 140, but should clamp to 127.
	builder.note(120, beat=0, velocity=100)
	builder.transpose(20)

	assert pattern.steps[0].notes[0].pitch == 127

	# Test downward clamping separately.
	pattern2, builder2 = _make_builder(length=4)
	builder2.note(5, beat=0, velocity=100)
	builder2.transpose(-20)

	assert pattern2.steps[0].notes[0].pitch == 0


def test_transpose_negative () -> None:

	"""transpose() with negative semitones should shift down."""

	pattern, builder = _make_builder(length=4)

	builder.note(72, beat=0, velocity=100)

	builder.transpose(-12)

	assert pattern.steps[0].notes[0].pitch == 60


def test_invert_mirrors_around_pivot () -> None:

	"""invert() should mirror pitches around the pivot note."""

	pattern, builder = _make_builder(length=4)

	# C=60, E=64, G=67
	builder.note(60, beat=0, velocity=100)
	builder.note(64, beat=1, velocity=100)
	builder.note(67, beat=2, velocity=100)

	# Invert around E (64): 60→68, 64→64, 67→61
	builder.invert(pivot=64)

	pitches = []

	for pos in sorted(pattern.steps.keys()):
		pitches.append(pattern.steps[pos].notes[0].pitch)

	assert pitches == [68, 64, 61]


def test_invert_clamps_to_midi_range () -> None:

	"""invert() should clamp pitches to 0-127."""

	pattern, builder = _make_builder(length=4)

	builder.note(10, beat=0, velocity=100)

	# Invert around 120: 120 + (120 - 10) = 230 → clamp to 127.
	builder.invert(pivot=120)

	assert pattern.steps[0].notes[0].pitch == 127


def test_every_fires_on_matching_cycle () -> None:

	"""every() should apply the transform when cycle is a multiple of n."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 4,
	)

	builder.note(60, beat=0, velocity=100)

	# Cycle 4 % 4 == 0, so this should fire.
	builder.every(4, lambda p: p.transpose(12))

	assert pattern.steps[0].notes[0].pitch == 72


def test_every_skips_non_matching_cycle () -> None:

	"""every() should skip the transform when cycle is not a multiple of n."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 3,
	)

	builder.note(60, beat=0, velocity=100)

	# Cycle 3 % 4 != 0, so this should NOT fire.
	builder.every(4, lambda p: p.transpose(12))

	assert pattern.steps[0].notes[0].pitch == 60


def test_every_fires_on_cycle_zero () -> None:

	"""every() should fire on cycle 0 (the first cycle)."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
	)

	builder.note(60, beat=0, velocity=100)

	builder.every(8, lambda p: p.reverse())

	# Reverse should have fired - note at pulse 0 moves to total_pulses - 1.
	total_pulses = int(4 * subsequence.constants.MIDI_QUARTER_NOTE)

	assert (total_pulses - 1) in pattern.steps
	assert 0 not in pattern.steps


# --- sequence() ---


def test_sequence_places_per_step_pitches () -> None:

	"""sequence() should place different pitches at each step position."""

	pattern, builder = _make_builder(length=4)

	builder.sequence(
		steps=[0, 4, 8, 12],
		pitches=[60, 64, 67, 72],
	)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected = {0: 60, ppq: 64, ppq * 2: 67, ppq * 3: 72}

	for pulse, expected_pitch in expected.items():
		assert pulse in pattern.steps
		assert pattern.steps[pulse].notes[0].pitch == expected_pitch


def test_sequence_scalar_pitch_expands () -> None:

	"""A single int pitch should be applied to all steps."""

	pattern, builder = _make_builder(length=4)

	builder.sequence([0, 4, 8, 12], pitches=60)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 4

	for step in pattern.steps.values():
		assert step.notes[0].pitch == 60


def test_sequence_scalar_velocity_expands () -> None:

	"""Default velocity=100 should apply to all steps."""

	pattern, builder = _make_builder(length=4)

	builder.sequence([0, 4, 8, 12], pitches=[60, 64, 67, 72])

	for step in pattern.steps.values():
		assert step.notes[0].velocity == 100


def test_sequence_scalar_duration_expands () -> None:

	"""Default duration=0.1 should apply to all steps."""

	pattern, builder = _make_builder(length=4)

	builder.sequence([0, 4, 8, 12], pitches=[60, 64, 67, 72])

	expected_dur = int(0.1 * subsequence.constants.MIDI_QUARTER_NOTE)

	for step in pattern.steps.values():
		assert step.notes[0].duration == expected_dur


def test_sequence_per_step_velocities () -> None:

	"""Per-step velocity lists should set different velocities at each position."""

	pattern, builder = _make_builder(length=4)

	builder.sequence(
		steps=[0, 4, 8, 12],
		pitches=60,
		velocities=[127, 90, 110, 80],
	)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected = {0: 127, ppq: 90, ppq * 2: 110, ppq * 3: 80}

	for pulse, expected_vel in expected.items():
		assert pattern.steps[pulse].notes[0].velocity == expected_vel


def test_sequence_list_longer_truncates () -> None:

	"""A pitches list longer than steps should be truncated."""

	pattern, builder = _make_builder(length=4)

	# 2 steps but 4 pitches - extra values should be ignored.
	builder.sequence([0, 4], pitches=[60, 64, 67, 72])

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 2

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	assert pattern.steps[0].notes[0].pitch == 60
	assert pattern.steps[ppq].notes[0].pitch == 64


def test_sequence_list_shorter_repeats_last () -> None:

	"""A pitches list shorter than steps should repeat the last value."""

	pattern, builder = _make_builder(length=4)

	# 4 steps but only 2 pitches - last value (64) fills remaining.
	builder.sequence([0, 4, 8, 12], pitches=[60, 64])

	ppq = subsequence.constants.MIDI_QUARTER_NOTE

	assert pattern.steps[0].notes[0].pitch == 60
	assert pattern.steps[ppq].notes[0].pitch == 64
	assert pattern.steps[ppq * 2].notes[0].pitch == 64
	assert pattern.steps[ppq * 3].notes[0].pitch == 64


def test_sequence_empty_steps_raises () -> None:

	"""An empty steps list should raise ValueError."""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError, match="steps list cannot be empty"):
		builder.sequence([], pitches=60)


def test_sequence_empty_pitches_list_raises () -> None:

	"""An empty pitches list should raise ValueError."""

	pattern, builder = _make_builder()

	with pytest.raises(ValueError, match="pitches list cannot be empty"):
		builder.sequence([0, 4], pitches=[])


def test_sequence_custom_grid () -> None:

	"""grid=8 should map steps to correct beat positions."""

	pattern, builder = _make_builder(length=4)

	# grid=8 over 4 beats = 0.5 beats per step.
	builder.sequence([0, 2, 4, 6], pitches=60, grid=8)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected_pulses = [0, ppq, ppq * 2, ppq * 3]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_sequence_default_grid_from_length () -> None:

	"""Without an explicit grid, a 6-sixteenth-note pattern should auto-derive grid=6."""

	pattern, builder = _make_builder(length=1.5)  # 6 * dur.SIXTEENTH = 1.5 beats

	builder.sequence([0, 3, 5], pitches=60)

	# step_duration = 1.5 / 6 = 0.25 beats per step (sixteenth notes)
	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected_pulses = [
		int(0.0 * ppq),   # step 0 → beat 0.0
		int(0.75 * ppq),  # step 3 → beat 0.75
		int(1.25 * ppq),  # step 5 → beat 1.25
	]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_sequence_default_grid_from_unit () -> None:

	"""When default_grid is set explicitly (as the decorator does with unit), the grid matches."""

	dur = subsequence.constants.durations
	beat_length = 6 * dur.SIXTEENTH  # 1.5 beats
	pattern, builder = _make_builder(length=beat_length, default_grid=6)

	builder.sequence([0, 3, 5], pitches=60)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected_pulses = [
		int(0.0 * ppq),
		int(0.75 * ppq),
		int(1.25 * ppq),
	]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_sequence_triplet_default_grid () -> None:

	"""A triplet-based pattern with explicit default_grid avoids the SIXTEENTH derivation bug."""

	dur = subsequence.constants.durations
	beat_length = 4 * dur.TRIPLET_EIGHTH  # ~2.667 beats
	pattern, builder = _make_builder(length=beat_length, default_grid=4)

	builder.sequence([0, 1, 2, 3], pitches=60)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	step_dur = beat_length / 4
	expected_pulses = [int(i * step_dur * ppq) for i in range(4)]

	assert sorted(pattern.steps.keys()) == expected_pulses


def test_sequence_probability_zero_places_none () -> None:

	"""probability=0.0 should place no notes."""

	pattern, builder = _make_builder(length=4)

	builder.sequence([0, 4, 8, 12], pitches=60, probability=0.0)

	assert len(pattern.steps) == 0


def test_sequence_probability_one_places_all () -> None:

	"""probability=1.0 should place all notes."""

	pattern, builder = _make_builder(length=4)

	builder.sequence([0, 4, 8, 12], pitches=60, probability=1.0)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 4


def test_sequence_with_drum_names () -> None:

	"""String pitches should resolve via the drum note map."""

	drum_map = {"kick": 36, "snare": 38}
	pattern, builder = _make_builder(drum_note_map=drum_map)

	builder.sequence([0, 4, 8, 12], pitches=["kick", "snare", "kick", "snare"])

	ppq = subsequence.constants.MIDI_QUARTER_NOTE

	assert pattern.steps[0].notes[0].pitch == 36
	assert pattern.steps[ppq].notes[0].pitch == 38
	assert pattern.steps[ppq * 2].notes[0].pitch == 36
	assert pattern.steps[ppq * 3].notes[0].pitch == 38


def test_sequence_truncation_logs_warning (caplog) -> None:

	"""Truncating a longer list should log a warning."""

	import logging

	pattern, builder = _make_builder(length=4)

	with caplog.at_level(logging.WARNING, logger="subsequence.pattern_builder"):
		builder.sequence([0, 4], pitches=[60, 64, 67, 72])

	assert "truncating" in caplog.text


def test_sequence_repeat_logs_warning (caplog) -> None:

	"""Repeating the last value for a shorter list should log a warning."""

	import logging

	pattern, builder = _make_builder(length=4)

	with caplog.at_level(logging.WARNING, logger="subsequence.pattern_builder"):
		builder.sequence([0, 4, 8, 12], pitches=[60, 64])

	assert "repeating last value" in caplog.text


# --- Strum ---


def test_strum_places_notes_with_offset () -> None:

	"""Strum with offset=0.1 should place notes at beats 0.0, 0.1, 0.2."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=4, quality="major")

	builder.strum(chord, root=52, velocity=90, offset=0.1)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE

	expected_pulses = [
		int(0.0 * ppq),
		int(0.1 * ppq),
		int(0.2 * ppq),
	]

	positions = sorted(pattern.steps.keys())

	assert positions == expected_pulses
	assert len(positions) == 3

	# All notes present.
	pitches = sorted(
		note.pitch
		for pos in positions
		for note in pattern.steps[pos].notes
	)

	assert pitches == [52, 56, 59]


def test_strum_direction_down () -> None:

	"""direction='down' should reverse pitch order (highest first at beat 0)."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=4, quality="major")

	builder.strum(chord, root=52, velocity=90, offset=0.1, direction="down")

	positions = sorted(pattern.steps.keys())

	# First note (beat 0) should be the highest pitch.
	first_pitch = pattern.steps[positions[0]].notes[0].pitch
	last_pitch = pattern.steps[positions[-1]].notes[0].pitch

	assert first_pitch > last_pitch


def test_strum_with_count () -> None:

	"""count=5 should produce 5 notes with extended octave tones."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	builder.strum(chord, root=60, velocity=90, offset=0.1, count=5)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 5


def test_strum_default_direction_is_up () -> None:

	"""Default direction should be 'up' (first note is lowest pitch)."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=4, quality="major")

	builder.strum(chord, root=52, velocity=90, offset=0.1)

	positions = sorted(pattern.steps.keys())

	first_pitch = pattern.steps[positions[0]].notes[0].pitch
	last_pitch = pattern.steps[positions[-1]].notes[0].pitch

	assert first_pitch < last_pitch


def test_strum_invalid_offset () -> None:

	"""offset=0 and offset<0 should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	with pytest.raises(ValueError, match="offset must be positive"):
		builder.strum(chord, root=60, offset=0)

	with pytest.raises(ValueError, match="offset must be positive"):
		builder.strum(chord, root=60, offset=-0.1)


def test_strum_invalid_direction () -> None:

	"""Invalid direction should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	with pytest.raises(ValueError, match="direction must be"):
		builder.strum(chord, root=60, direction="sideways")


# --- legato= shorthand on chord() and strum() ---


def test_chord_legato_reshapes_durations () -> None:

	"""chord(legato=0.9) should call p.legato() — durations differ from the default."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	# Without legato, default duration is 1.0 beat = MIDI_QUARTER_NOTE pulses
	builder.chord(chord, root=60, velocity=90, legato=0.9)

	# legato() wraps around to the full pattern for a lone chord, so duration
	# should be 0.9 × total_pulses, not the default 1.0-beat value.
	total_pulses = int(4 * subsequence.constants.MIDI_QUARTER_NOTE)
	expected_duration = max(1, int(total_pulses * 0.9))

	for note in pattern.steps[0].notes:
		assert note.duration == expected_duration


def test_chord_legato_sustain_clash_raises () -> None:

	"""chord(sustain=True, legato=0.9) should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	with pytest.raises(ValueError, match="mutually exclusive"):
		builder.chord(chord, root=60, sustain=True, legato=0.9)


def test_chord_default_no_legato_unchanged () -> None:

	"""chord() without legato= leaves note durations at the default value (regression)."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	builder.chord(chord, root=60, velocity=90)

	expected_duration = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	for note in pattern.steps[0].notes:
		assert note.duration == expected_duration


def test_strum_legato_reshapes_durations () -> None:

	"""strum(legato=0.9) should call p.legato() after placing notes."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	builder.strum(chord, root=60, velocity=90, offset=0.1, legato=0.9)

	# Each note is at a different pulse position due to strum offset;
	# legato stretches each to fill the gap to the next. Verify that
	# note durations are not the default 1.0-beat value (24 pulses).
	default_duration = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	for step in pattern.steps.values():
		for note in step.notes:
			assert note.duration != default_duration


def test_strum_legato_sustain_clash_raises () -> None:

	"""strum(sustain=True, legato=0.9) should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	with pytest.raises(ValueError, match="mutually exclusive"):
		builder.strum(chord, root=60, sustain=True, legato=0.9)


# --- Broken Chord ---


def test_broken_chord_places_notes_in_order () -> None:

	"""broken_chord should map order indices correctly."""

	pattern, builder = _make_builder(length=4)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	builder.broken_chord(chord, root=60, order=[2, 0, 1], spacing=0.25)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	positions = sorted(pattern.steps.keys())
	assert len(positions) == 16 # 4 beats / 0.25 step = 16 steps
	assert positions[0] == 0
	assert positions[1] == int(0.25 * ppq)
	assert positions[2] == int(0.50 * ppq)

	# Verify the cycling pitch order: 67, 60, 64
	pitches = [pattern.steps[pos].notes[0].pitch for pos in positions]
	assert pitches[:6] == [67, 60, 64, 67, 60, 64]


def test_broken_chord_empty_order_raises () -> None:

	"""broken_chord with empty order should raise ValueError."""

	pattern, builder = _make_builder(length=4)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	with pytest.raises(ValueError, match="order list cannot be empty"):
		builder.broken_chord(chord, root=60, order=[])


def test_broken_chord_negative_index_raises () -> None:

	"""broken_chord with negative index should raise ValueError."""

	pattern, builder = _make_builder(length=4)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	with pytest.raises(ValueError, match="non-negative integers"):
		builder.broken_chord(chord, root=60, order=[0, -1])


# --- p.param() ---


def test_param_returns_default_when_no_tweak () -> None:

	"""p.param() should return the default when no tweak is set."""

	_, builder = _make_builder()

	assert builder.param("pitches", [60, 64]) == [60, 64]


def test_param_returns_tweaked_value () -> None:

	"""p.param() should return the tweaked value when set."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		tweaks = {"pitches": [48, 52]}
	)

	assert builder.param("pitches", [60, 64]) == [48, 52]


def test_param_returns_none_when_no_default () -> None:

	"""p.param() with no default should return None for missing keys."""

	_, builder = _make_builder()

	assert builder.param("missing") is None


# --- Randomize ---


def test_randomize_timing_shifts_notes () -> None:

	"""randomize(timing=0.5) should shift at least one note from its original pulse."""

	import random

	_, builder = _make_builder()

	# Place notes at all 16 sixteenth-note positions using MIDI note numbers.
	builder.hit_steps(36, list(range(16)), velocity=100)
	original_pulses = set(builder._pattern.steps.keys())

	builder.randomize(timing=0.5, rng=random.Random(42))

	new_pulses = set(builder._pattern.steps.keys())

	# At least one note should have moved.
	assert new_pulses != original_pulses


def test_randomize_timing_zero_no_change () -> None:

	"""randomize(timing=0.0) should leave all pulse positions unchanged."""

	import random

	_, builder = _make_builder()
	builder.hit_steps(36, list(range(16)), velocity=100)
	original_pulses = set(builder._pattern.steps.keys())

	builder.randomize(timing=0.0, rng=random.Random(42))

	assert set(builder._pattern.steps.keys()) == original_pulses


def test_randomize_velocity_changes_velocity () -> None:

	"""randomize(velocity=0.5) should change at least one note's velocity."""

	import random

	_, builder = _make_builder()
	builder.hit_steps(36, list(range(16)), velocity=100)

	original_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	builder.randomize(velocity=0.5, rng=random.Random(42))

	new_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	assert new_velocities != original_velocities


def test_randomize_velocity_zero_no_change () -> None:

	"""randomize(velocity=0.0) should leave all velocities unchanged."""

	import random

	_, builder = _make_builder()
	builder.hit_steps(36, list(range(16)), velocity=100)

	original_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	builder.randomize(velocity=0.0, rng=random.Random(42))

	new_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	assert new_velocities == original_velocities


def test_randomize_deterministic_with_rng () -> None:

	"""Same RNG seed produces identical results; different seed produces different results."""

	import random

	def build_with_seed (seed: int) -> set:
		_, builder = _make_builder()
		builder.hit_steps(36, list(range(16)), velocity=80)
		builder.randomize(timing=0.5, velocity=0.3, rng=random.Random(seed))
		return set(builder._pattern.steps.keys())

	run_a = build_with_seed(1)
	run_b = build_with_seed(1)
	run_c = build_with_seed(99)

	assert run_a == run_b
	assert run_a != run_c


def test_randomize_velocity_stays_in_range () -> None:

	"""All velocities must remain in the valid MIDI range (1–127) after randomize."""

	import random

	_, builder = _make_builder()

	# Use edge-case velocities to stress-test the clamp.
	builder.note(60, beat=0, velocity=1)
	builder.note(60, beat=1, velocity=127)
	builder.note(60, beat=2, velocity=64)

	builder.randomize(velocity=1.0, rng=random.Random(42))

	for step in builder._pattern.steps.values():
		for note in step.notes:
			assert 1 <= note.velocity <= 127


# ── CC / Pitch Bend ──────────────────────────────────────────────────


def test_cc_adds_event () -> None:

	"""p.cc() should create a CcEvent at the correct pulse."""

	_, builder = _make_builder()

	builder.cc(74, 100, beat=1.0)

	assert len(builder._pattern.cc_events) == 1

	event = builder._pattern.cc_events[0]
	assert event.message_type == 'control_change'
	assert event.control == 74
	assert event.value == 100
	assert event.pulse == 24  # 1 beat * 24 ppq


def test_cc_ramp_generates_interpolated_events () -> None:

	"""cc_ramp should produce linearly interpolated CC events."""

	_, builder = _make_builder()

	builder.cc_ramp(74, start=0, end=127, beat_start=0, beat_end=1, resolution=6)

	events = builder._pattern.cc_events
	# From pulse 0 to pulse 24 in steps of 6 → pulses 0, 6, 12, 18, 24
	assert len(events) == 5

	# All should be control_change for CC 74
	for event in events:
		assert event.message_type == 'control_change'
		assert event.control == 74

	# First and last values
	assert events[0].value == 0
	assert events[-1].value == 127

	# Values should be monotonically increasing
	values = [e.value for e in events]
	assert values == sorted(values)


def test_cc_ramp_resolution () -> None:

	"""Higher resolution value should produce fewer events."""

	_, builder_fine = _make_builder()
	_, builder_coarse = _make_builder()

	builder_fine.cc_ramp(1, 0, 127, beat_start=0, beat_end=1, resolution=1)
	builder_coarse.cc_ramp(1, 0, 127, beat_start=0, beat_end=1, resolution=6)

	assert len(builder_fine._pattern.cc_events) > len(builder_coarse._pattern.cc_events)


def test_pitch_bend_normalised_range () -> None:

	"""pitch_bend should map -1.0..1.0 to -8192..8191."""

	_, builder = _make_builder()

	builder.pitch_bend(1.0, beat=0)
	builder.pitch_bend(-1.0, beat=1)
	builder.pitch_bend(0.0, beat=2)

	events = builder._pattern.cc_events

	assert events[0].message_type == 'pitchwheel'
	assert events[0].value == 8191  # clamped to max
	assert events[1].value == -8192
	assert events[2].value == 0


def test_pitch_bend_ramp () -> None:

	"""pitch_bend_ramp should produce interpolated pitchwheel events."""

	_, builder = _make_builder()

	builder.pitch_bend_ramp(-1.0, 1.0, beat_start=0, beat_end=1, resolution=6)

	events = builder._pattern.cc_events
	# From pulse 0 to 24 in steps of 6 → 5 events
	assert len(events) == 5

	for event in events:
		assert event.message_type == 'pitchwheel'
		assert -8192 <= event.value <= 8191

	# Should go from negative to positive
	assert events[0].value < 0
	assert events[-1].value > 0


def test_cc_ramp_defaults_beat_end_to_pattern_length () -> None:

	"""When beat_end is omitted, the ramp should extend to pattern length."""

	_, builder = _make_builder(length=2)

	builder.cc_ramp(74, 0, 127, beat_start=0, resolution=12)

	events = builder._pattern.cc_events
	# 2 beats = 48 pulses, step 12 → pulses 0, 12, 24, 36, 48 → 5 events
	assert len(events) == 5
	assert events[-1].pulse == 48


def test_cc_ramp_with_ease_in_shape () -> None:

	"""cc_ramp with shape='ease_in' produces non-linear (quadratic) CC values."""

	_, builder = _make_builder(length=4)

	# 4 beats = 96 pulses; with resolution=96 we get exactly 2 events: pulse 0 and pulse 96
	builder.cc_ramp(74, 0, 100, beat_start=0, beat_end=4, resolution=96, shape="ease_in")

	events = sorted(builder._pattern.cc_events, key=lambda e: e.pulse)
	assert events[0].value == 0    # t=0.0 → ease_in(0) = 0
	assert events[1].value == 100  # t=1.0 → ease_in(1) = 1.0 → 100

	# Check a mid-ramp event: use resolution=48 (3 events: 0, 48, 96)
	_, builder2 = _make_builder(length=4)
	builder2.cc_ramp(74, 0, 100, beat_start=0, beat_end=4, resolution=48, shape="ease_in")
	mid_events = sorted(builder2._pattern.cc_events, key=lambda e: e.pulse)
	# t=0.5 → ease_in(0.5) = 0.25 → value ≈ 25
	assert mid_events[1].value == 25


def test_cc_ramp_default_shape_is_linear () -> None:

	"""cc_ramp with no shape argument remains linear (regression test)."""

	_, builder = _make_builder(length=4)
	builder.cc_ramp(74, 0, 100, beat_start=0, beat_end=4, resolution=48)

	events = sorted(builder._pattern.cc_events, key=lambda e: e.pulse)
	# t=0.5 → linear → value = 50
	assert events[1].value == 50


def test_cc_events_cleared_on_rebuild () -> None:

	"""Pattern.cc_events should be reset to [] each cycle."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	pattern.cc_events.append(
		subsequence.pattern.CcEvent(pulse=0, message_type='control_change', control=74, value=100)
	)

	assert len(pattern.cc_events) == 1

	# Simulate what _rebuild does
	pattern.steps = {}
	pattern.cc_events = []

	assert len(pattern.cc_events) == 0


# ── OSC output ────────────────────────────────────────────────────────────────


def test_osc_adds_event () -> None:

	"""p.osc() should create an OscEvent at the correct pulse."""

	_, builder = _make_builder()

	builder.osc("/mixer/fader/1", 0.5, beat=1.0)

	assert len(builder._pattern.osc_events) == 1

	event = builder._pattern.osc_events[0]
	assert event.address == "/mixer/fader/1"
	assert event.args == (0.5,)
	assert event.pulse == 24  # 1 beat * 24 ppq


def test_osc_no_args () -> None:

	"""p.osc() with no extra arguments should produce an event with empty args."""

	_, builder = _make_builder()

	builder.osc("/scene/next", beat=0.0)

	assert len(builder._pattern.osc_events) == 1

	event = builder._pattern.osc_events[0]
	assert event.address == "/scene/next"
	assert event.args == ()
	assert event.pulse == 0


def test_osc_multiple_args () -> None:

	"""p.osc() should accept and preserve multiple arguments."""

	_, builder = _make_builder()

	builder.osc("/matrix/cell", 3, 7, 0.8, beat=2.0)

	event = builder._pattern.osc_events[0]
	assert event.args == (3, 7, 0.8)


def test_osc_ramp_generates_interpolated_events () -> None:

	"""osc_ramp should produce linearly interpolated float events."""

	_, builder = _make_builder()

	builder.osc_ramp("/filter/cutoff", start=0.0, end=1.0, beat_start=0, beat_end=1, resolution=6)

	events = builder._pattern.osc_events
	# From pulse 0 to pulse 24 in steps of 6 → pulses 0, 6, 12, 18, 24
	assert len(events) == 5

	for event in events:
		assert event.address == "/filter/cutoff"
		assert len(event.args) == 1

	# First and last values
	assert events[0].args[0] == pytest.approx(0.0)
	assert events[-1].args[0] == pytest.approx(1.0)

	# Values should be monotonically increasing
	values = [e.args[0] for e in events]
	assert values == sorted(values)


def test_osc_ramp_resolution () -> None:

	"""Higher resolution value should produce fewer events."""

	_, builder_fine = _make_builder()
	_, builder_coarse = _make_builder()

	builder_fine.osc_ramp("/fader", 0.0, 1.0, beat_start=0, beat_end=1, resolution=1)
	builder_coarse.osc_ramp("/fader", 0.0, 1.0, beat_start=0, beat_end=1, resolution=6)

	assert len(builder_fine._pattern.osc_events) > len(builder_coarse._pattern.osc_events)


def test_osc_ramp_defaults_beat_end_to_pattern_length () -> None:

	"""osc_ramp with no beat_end should ramp to the full pattern length."""

	_, builder = _make_builder(length=4)

	builder.osc_ramp("/fader", 0.0, 1.0, beat_start=0, resolution=96)

	events = builder._pattern.osc_events
	# 4 beats = 96 pulses; resolution=96 → events at pulse 0 and 96
	assert len(events) == 2
	assert events[0].pulse == 0
	assert events[-1].pulse == 96


def test_osc_ramp_with_easing () -> None:

	"""osc_ramp with shape='ease_in' should produce non-linear values."""

	_, builder = _make_builder(length=4)

	# 4 beats = 96 pulses; resolution=48 → 3 events at pulses 0, 48, 96
	builder.osc_ramp("/filter", 0.0, 1.0, beat_start=0, beat_end=4, resolution=48, shape="ease_in")

	events = sorted(builder._pattern.osc_events, key=lambda e: e.pulse)
	assert len(events) == 3

	# t=0.5 → ease_in(0.5) = 0.25 (quadratic), so midpoint ≈ 0.25 not 0.5
	mid_val = events[1].args[0]
	assert mid_val == pytest.approx(0.25, abs=0.01)


def test_osc_events_cleared_on_rebuild () -> None:

	"""Pattern.osc_events should be reset to [] each cycle."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	pattern.osc_events.append(
		subsequence.pattern.OscEvent(pulse=0, address="/fader", args=(0.5,))
	)

	assert len(pattern.osc_events) == 1

	# Simulate what _rebuild does
	pattern.steps = {}
	pattern.cc_events = []
	pattern.osc_events = []

	assert len(pattern.osc_events) == 0


# ── p.bend() ──────────────────────────────────────────────────────────────────


def test_bend_last_note () -> None:

	"""bend(note=-1) should place ramp events within the last note's duration."""

	_, builder = _make_builder(length=4)

	# 4 notes at pulses 0, 24, 48, 72; use add_note to avoid needing a drum_note_map
	for pos in (0, 24, 48, 72):
		builder._pattern.add_note(position=pos, pitch=40, velocity=80, duration=6)
	builder.legato(0.9)

	sorted_positions = sorted(builder._pattern.steps.keys())
	last_pos = sorted_positions[-1]
	last_duration = max(n.duration for n in builder._pattern.steps[last_pos].notes)

	builder.bend(note=-1, amount=0.5)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']

	# All ramp events (excluding reset) should be within [last_pos, last_pos + duration]
	ramp_events = bend_events[:-1]  # last event is the reset
	for e in ramp_events:
		assert last_pos <= e.pulse <= last_pos + last_duration


def test_bend_first_note () -> None:

	"""bend(note=0) should place ramp events starting at position 0."""

	_, builder = _make_builder(length=4)
	for pos in (0, 24, 48, 72):
		builder._pattern.add_note(position=pos, pitch=40, velocity=80, duration=6)
	builder.legato(0.9)

	builder.bend(note=0, amount=-0.5)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	assert bend_events[0].pulse == 0  # ramp starts at note onset


def test_bend_with_start_end_fraction () -> None:

	"""bend() with start=0.5, end=0.9 should narrow the ramp to that fraction."""

	_, builder = _make_builder(length=4)
	for pos in (0, 24, 48, 72):
		builder._pattern.add_note(position=pos, pitch=40, velocity=80, duration=6)
	builder.legato(0.9)

	sorted_positions = sorted(builder._pattern.steps.keys())
	first_pos = sorted_positions[0]
	duration = max(n.duration for n in builder._pattern.steps[first_pos].notes)

	builder.bend(note=0, amount=1.0, start=0.5, end=0.9, resolution=1)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	ramp_events = bend_events[:-1]

	expected_start = first_pos + int(duration * 0.5)
	expected_end = first_pos + int(duration * 0.9)

	assert ramp_events[0].pulse == expected_start
	assert ramp_events[-1].pulse == expected_end


def test_bend_inserts_reset_at_next_note () -> None:

	"""bend() should insert a pitch_bend(0) at the onset of the following note."""

	_, builder = _make_builder(length=4)
	for pos in (0, 24, 48, 72):
		builder._pattern.add_note(position=pos, pitch=40, velocity=80, duration=6)
	builder.legato(0.9)

	sorted_positions = sorted(builder._pattern.steps.keys())
	next_note_pulse = sorted_positions[1]  # note after note 0

	builder.bend(note=0, amount=0.5)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	reset_event = bend_events[-1]

	assert reset_event.pulse == next_note_pulse
	assert reset_event.value == 0


def test_bend_reset_wraps_to_bar_start () -> None:

	"""bend() on the last note should place the reset at pulse 0."""

	_, builder = _make_builder(length=4)
	for pos in (0, 24, 48, 72):
		builder._pattern.add_note(position=pos, pitch=40, velocity=80, duration=6)
	builder.legato(0.9)

	builder.bend(note=-1, amount=0.5)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	reset_event = bend_events[-1]

	assert reset_event.pulse == 0
	assert reset_event.value == 0


def test_bend_with_easing () -> None:

	"""bend() with shape='ease_in' should produce a non-linear ramp."""

	_, builder = _make_builder(length=4)
	# Single note at pulse 0 with long duration so we can observe the curve
	builder._pattern.add_note(position=0, pitch=40, velocity=80, duration=48)

	# resolution=48 → 2 events: pulse 0 (t=0) and pulse 48 (t=1)
	builder.bend(note=0, amount=1.0, shape="ease_in", resolution=48)

	bend_events = sorted(
		[e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel'],
		key=lambda e: e.pulse
	)
	ramp_events = [e for e in bend_events if e.value != 0 or e.pulse == 0]

	# t=0 → ease_in(0)=0 → value=0; t=1 → ease_in(1)=1 → value≈8191
	assert ramp_events[0].value == 0
	assert ramp_events[-1].value == 8191


def test_bend_empty_pattern () -> None:

	"""bend() on an empty pattern should be a no-op."""

	_, builder = _make_builder(length=4)
	builder.bend(note=0, amount=0.5)  # should not raise

	assert builder._pattern.cc_events == []


def test_bend_index_out_of_range () -> None:

	"""bend() with an out-of-range index should raise IndexError."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0, pitch=40, velocity=80, duration=6)

	with pytest.raises(IndexError):
		builder.bend(note=5, amount=0.5)


# ── p.portamento() ────────────────────────────────────────────────────────────


def test_portamento_generates_glides_between_notes () -> None:

	"""portamento() should insert pitchwheel events in the tail of each note."""

	_, builder = _make_builder(length=4)
	# Two notes at pulse 0 and 48
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)

	builder.portamento(time=0.25, resolution=1, wrap=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']

	# Ramp events should be in the tail of note at pulse 0: [0 + int(40*0.75), 0+40] = [30, 40]
	ramp_events = [e for e in bend_events if e.value != 0]
	assert len(ramp_events) > 0
	for e in ramp_events:
		assert 30 <= e.pulse <= 40


def test_portamento_resets_at_each_note_onset () -> None:

	"""portamento() should insert a pitch_bend(0) reset at each destination note onset."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)

	builder.portamento(time=0.25, resolution=1, wrap=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	reset_events = [e for e in bend_events if e.value == 0 and e.pulse == 48]

	assert len(reset_events) == 1


def test_portamento_skips_large_intervals () -> None:

	"""portamento() should skip pairs whose interval exceeds bend_range."""

	_, builder = _make_builder(length=4)
	# Interval of 5 semitones — exceeds default bend_range=2
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=45, velocity=80, duration=40)

	builder.portamento(time=0.25, bend_range=2.0, wrap=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	assert len(bend_events) == 0  # skipped — no events generated


def test_portamento_bend_range_none () -> None:

	"""portamento(bend_range=None) should generate events regardless of interval size."""

	_, builder = _make_builder(length=4)
	# Large interval
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=55, velocity=80, duration=40)

	builder.portamento(time=0.25, bend_range=None, wrap=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	# Should have generated events despite large interval; value clamped to ±8191
	assert len(bend_events) > 0
	for e in bend_events:
		assert -8192 <= e.value <= 8191


def test_portamento_wrap_true () -> None:

	"""portamento(wrap=True) should glide from the last note toward the first."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)

	builder.portamento(time=0.25, resolution=1, wrap=True)

	# With wrap=True there should be a reset at pulse 0 (wrapping from last→first)
	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	reset_at_zero = [e for e in bend_events if e.pulse == 0 and e.value == 0]

	assert len(reset_at_zero) >= 1


def test_portamento_wrap_false () -> None:

	"""portamento(wrap=False) should not generate a glide from the last note."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)

	builder.portamento(time=0.25, resolution=1, wrap=False)

	# With wrap=False there should be no *ramp* events (non-zero value) in the tail
	# of the last note (position 48, duration 40, tail starts at 60)
	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	events_in_last_note_tail = [e for e in bend_events if e.pulse > 48 and e.value != 0]
	assert len(events_in_last_note_tail) == 0


def test_portamento_time_fraction () -> None:

	"""portamento() glide should occupy the correct fraction of the note duration."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)

	time_frac = 0.5
	builder.portamento(time=time_frac, resolution=1, wrap=False)

	# Collect all pitchwheel events except the reset at pulse 48
	all_bend = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']
	ramp_events = [e for e in all_bend if e.pulse != 48]

	# Glide starts at 0 + int(40 * 0.5) = 20, ends at 40
	assert ramp_events[0].pulse == 20
	assert ramp_events[-1].pulse == 40


# ── p.slide() ─────────────────────────────────────────────────────────────────


def test_slide_by_note_index () -> None:

	"""slide(notes=[1]) should only glide into the 2nd note."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)
	builder._pattern.add_note(position=72, pitch=43, velocity=80, duration=20)

	# Only slide into note index 1 (position 48)
	builder.slide(notes=[1], time=0.25, wrap=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']

	# Ramp events should be in tail of note 0 (pos 0, duration 40) → [30, 40]
	ramp_events = [e for e in bend_events if e.value != 0]
	assert len(ramp_events) > 0
	for e in ramp_events:
		assert 30 <= e.pulse <= 40

	# No ramp events in tail of note 1 (pos 48) since note 2 isn't flagged
	events_in_note1_tail = [e for e in ramp_events if 60 <= e.pulse <= 72]
	assert len(events_in_note1_tail) == 0


def test_slide_by_step_index () -> None:

	"""slide(steps=[4]) should slide into the note at step 4 (pulse 24)."""

	_, builder = _make_builder(length=4, default_grid=16)
	# step 0 → pulse 0, step 4 → pulse 24 (16-step grid over 4 beats = 6 pulses/step)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=20)
	builder._pattern.add_note(position=24, pitch=42, velocity=80, duration=20)

	builder.slide(steps=[4], time=0.5, wrap=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']

	# Glide should be in tail of note at pulse 0
	ramp_events = [e for e in bend_events if e.value != 0]
	assert len(ramp_events) > 0
	reset_events = [e for e in bend_events if e.pulse == 24 and e.value == 0]
	assert len(reset_events) == 1


def test_slide_extend_true () -> None:

	"""slide(extend=True) should extend the preceding note to meet the target."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=20)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=20)

	builder.slide(notes=[1], time=0.25, extend=True, wrap=False)

	# Preceding note (at position 0) should be extended to reach position 48
	preceding_note = builder._pattern.steps[0].notes[0]
	assert preceding_note.duration == 48


def test_slide_extend_false () -> None:

	"""slide(extend=False) should leave the preceding note's duration unchanged."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=20)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=20)

	builder.slide(notes=[1], time=0.25, extend=False, wrap=False)

	preceding_note = builder._pattern.steps[0].notes[0]
	assert preceding_note.duration == 20  # unchanged


def test_slide_requires_notes_or_steps () -> None:

	"""slide() with neither notes nor steps should raise ValueError."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0, pitch=40, velocity=80, duration=20)

	with pytest.raises(ValueError):
		builder.slide()


def test_slide_wrap () -> None:

	"""slide(notes=[-1 mapped to last], wrap=True) glides from last to first."""

	_, builder = _make_builder(length=4)
	builder._pattern.add_note(position=0,  pitch=40, velocity=80, duration=40)
	builder._pattern.add_note(position=48, pitch=42, velocity=80, duration=40)

	# Flag note at index 0 as the destination (wrap from last → first)
	builder.slide(notes=[0], time=0.5, wrap=True, extend=False)

	bend_events = [e for e in builder._pattern.cc_events if e.message_type == 'pitchwheel']

	# Ramp events should be in tail of last note (pos 48, duration 40)
	ramp_events = [e for e in bend_events if e.value != 0]
	for e in ramp_events:
		assert e.pulse >= 48  # within or after the last note's position

	# Reset at pulse 0 (wrap-around)
	reset_at_zero = [e for e in bend_events if e.pulse == 0 and e.value == 0]
	assert len(reset_at_zero) >= 1


# --- bresenham_poly ---

def test_bresenham_poly_full_density_fills_all_steps () -> None:

	"""Weights summing to 1.0 should produce a hit on every grid step."""

	drum_map = {"kick": 36, "snare": 38, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.25, "snare": 0.25, "hat": 0.5},
		velocity=100,
	)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())
	assert total_notes == 16


def test_bresenham_poly_rest_voice_reduces_notes () -> None:

	"""Weights summing to 0.5 should produce half as many notes as grid steps."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.25, "hat": 0.25},
		velocity=100,
	)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())
	assert total_notes == 8


def test_bresenham_poly_no_overlaps () -> None:

	"""No two voices should fire on the same step."""

	drum_map = {"kick": 36, "snare": 38, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.3, "snare": 0.2, "hat": 0.5},
		velocity=100,
	)

	for step in pattern.steps.values():
		assert len(step.notes) <= 1


def test_bresenham_poly_per_voice_velocity () -> None:

	"""Each voice should use its own velocity from the velocity dict."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.5, "hat": 0.5},
		velocity={"kick": 127, "hat": 60},
	)

	pitch_velocities: dict = {}
	for step in pattern.steps.values():
		for note in step.notes:
			pitch_velocities[note.pitch] = note.velocity

	assert pitch_velocities[36] == 127
	assert pitch_velocities[42] == 60


def test_bresenham_poly_scalar_velocity_applies_to_all () -> None:

	"""A single int velocity should apply to every placed note."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.5, "hat": 0.5},
		velocity=77,
	)

	for step in pattern.steps.values():
		for note in step.notes:
			assert note.velocity == 77


def test_bresenham_poly_velocity_dict_missing_key_uses_default () -> None:

	"""Voices absent from the velocity dict should use DEFAULT_VELOCITY."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.5, "hat": 0.5},
		velocity={"kick": 127},  # hat not specified
	)

	for step in pattern.steps.values():
		for note in step.notes:
			if note.pitch == 42:
				assert note.velocity == subsequence.constants.velocity.DEFAULT_VELOCITY


def test_bresenham_poly_dropout_reduces_notes () -> None:

	"""Dropout should reduce the total number of placed notes."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.bresenham_poly(
		parts={"kick": 0.5, "hat": 0.5},
		velocity=100,
		dropout=0.5,
	)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())
	assert 0 < total_notes < 16


def test_bresenham_poly_custom_grid () -> None:

	"""A custom grid should be used as the step count."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.bresenham_poly(
		parts={"kick": 0.5, "hat": 0.5},
		velocity=100,
		grid=8,
	)

	total_notes = sum(len(step.notes) for step in pattern.steps.values())
	assert total_notes == 8


def test_bresenham_poly_empty_parts_raises () -> None:

	"""An empty parts dict should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	with pytest.raises(ValueError):
		builder.bresenham_poly(parts={})


def test_bresenham_poly_negative_weight_raises () -> None:

	"""Negative density weights should raise ValueError."""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	with pytest.raises(ValueError):
		builder.bresenham_poly(parts={"kick": -0.5})


def test_bresenham_poly_deterministic_with_seed () -> None:

	"""Same seed should produce the same pattern when dropout is used."""

	drum_map = {"kick": 36, "hat": 42}

	def build (seed: int) -> set:
		pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
		builder.rng = random.Random(seed)
		builder.bresenham_poly(
			parts={"kick": 0.25, "hat": 0.5},
			velocity=100,
			dropout=0.3,
		)
		return set(pattern.steps.keys())

	assert build(42) == build(42)


# --- no_overlap ---

def test_bresenham_no_overlap_skips_existing_pitch () -> None:

	"""With no_overlap=True, bresenham should not place a note where the same pitch exists."""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	# Place anchor kicks on beats 1, 2, 3, 4 (steps 0, 4, 8, 12).
	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)
	anchors_placed = sum(len(s.notes) for s in pattern.steps.values())
	assert anchors_placed == 4

	# Ghost kicks with no_overlap — should skip steps that already have kick.
	builder.bresenham("kick", pulses=5, velocity=45, no_overlap=True)

	for step in pattern.steps.values():
		kick_notes = [n for n in step.notes if n.pitch == 36]
		assert len(kick_notes) <= 1


def test_bresenham_without_no_overlap_allows_duplicates () -> None:

	"""Without no_overlap, bresenham places notes even where the same pitch exists."""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)
	builder.bresenham("kick", pulses=5, velocity=45)

	total_notes = sum(len(s.notes) for s in pattern.steps.values())
	assert total_notes == 9  # 4 anchors + 5 ghost kicks, overlaps allowed


def test_euclidean_no_overlap () -> None:

	"""no_overlap should work for euclidean too (shared _place_rhythm_sequence)."""

	drum_map = {"snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.hit_steps("snare", [4, 12], velocity=100)
	builder.euclidean("snare", pulses=4, velocity=50, no_overlap=True)

	for step in pattern.steps.values():
		snare_notes = [n for n in step.notes if n.pitch == 38]
		assert len(snare_notes) <= 1


def test_bresenham_poly_no_overlap () -> None:

	"""bresenham_poly with no_overlap should skip steps with existing same-pitch notes."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	# Place kick anchors first.
	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)

	# Poly layer includes kick at ghost velocity — should skip occupied kick steps.
	builder.bresenham_poly(
		parts={"kick": 0.5, "hat": 0.5},
		velocity={"kick": 45, "hat": 70},
		no_overlap=True,
	)

	for step in pattern.steps.values():
		kick_notes = [n for n in step.notes if n.pitch == 36]
		assert len(kick_notes) <= 1


def test_no_overlap_allows_different_pitches_on_same_step () -> None:

	"""no_overlap only prevents same-pitch collisions — different pitches can share a step."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	# Place kicks on every beat.
	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)

	# Bresenham hat with no_overlap — hats are a different pitch, should still be placed.
	builder.bresenham("hat", pulses=4, velocity=70, no_overlap=True)

	total_notes = sum(len(s.notes) for s in pattern.steps.values())
	assert total_notes == 8  # 4 kicks + 4 hats, no collisions because different pitches


# --- ghost_fill ---


def test_ghost_fill_places_notes () -> None:

	"""ghost_fill should place at least some notes at moderate density."""

	drum_map = {"snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.ghost_fill("snare", density=0.5, velocity=35, bias="uniform")

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total > 0


def test_ghost_fill_no_overlap_respects_anchors () -> None:

	"""ghost_fill with no_overlap should not place notes where anchors exist."""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)
	builder.ghost_fill("kick", density=1.0, velocity=40, bias="uniform", no_overlap=True)

	# Check anchor positions — should have exactly 1 kick each
	step_dur = 4.0 / 16
	for step_idx in [0, 4, 8, 12]:
		pulse = int(step_idx * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
		if pulse in pattern.steps:
			kick_notes = [n for n in pattern.steps[pulse].notes if n.pitch == 36]
			assert len(kick_notes) == 1


def test_ghost_fill_sixteenths_bias () -> None:

	"""Sixteenths bias should strongly prefer non-downbeat positions."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.ghost_fill("hat", density=0.8, velocity=50, bias="sixteenths")

	# Count hits on downbeats vs offbeats
	step_dur = 4.0 / 16
	downbeat_hits = 0
	offbeat_hits = 0
	for step_idx in range(16):
		pulse = int(step_idx * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
		if pulse in pattern.steps:
			count = len(pattern.steps[pulse].notes)
			if step_idx % 4 == 0:
				downbeat_hits += count
			else:
				offbeat_hits += count

	assert offbeat_hits > downbeat_hits


def test_ghost_fill_velocity_tuple () -> None:

	"""When velocity is a (low, high) tuple, all velocities should be in range."""

	drum_map = {"snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.ghost_fill("snare", density=0.8, velocity=(25, 45), bias="uniform")

	for step in pattern.steps.values():
		for note in step.notes:
			assert 25 <= note.velocity <= 45


def test_ghost_fill_density_zero () -> None:

	"""Density 0 should place no notes."""

	drum_map = {"snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	builder.ghost_fill("snare", density=0.0, velocity=35)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total == 0


def test_ghost_fill_custom_bias_list () -> None:

	"""A custom probability list should work as bias."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	# Only allow ghost notes on steps 0 and 8
	probs = [0.0] * 16
	probs[0] = 1.0
	probs[8] = 1.0

	builder.ghost_fill("hat", density=1.0, velocity=60, bias=probs)

	# All hits should be on steps 0 and 8 only
	step_dur = 4.0 / 16
	for step_idx in range(16):
		pulse = int(step_idx * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
		if pulse in pattern.steps and pattern.steps[pulse].notes:
			assert step_idx in (0, 8), f"Unexpected hit at step {step_idx}"


def test_ghost_fill_unknown_bias_raises () -> None:

	"""An unknown bias string should raise ValueError."""

	drum_map = {"snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)

	with pytest.raises(ValueError, match="Unknown ghost_fill bias"):
		builder.ghost_fill("snare", density=0.5, bias="nonexistent")


def test_ghost_fill_deterministic () -> None:

	"""Same seed should produce the same ghost pattern."""

	drum_map = {"snare": 38}

	def _run (seed: int) -> list:
		pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
		builder.rng = random.Random(seed)
		builder.ghost_fill("snare", density=0.4, velocity=35, bias="sixteenths")
		return sorted(pattern.steps.keys())

	assert _run(42) == _run(42)


def test_ghost_fill_velocity_sequence () -> None:

	"""A sequence passed to velocity should assign per-step velocities."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	velocities = [20, 40, 60, 80]
	builder.ghost_fill(38, density=1.0, velocity=velocities, bias="uniform")

	# grid is 16 by default, so steps 0-15.
	for step_idx in range(16):
		pulse = int(step_idx * 0.25 * subsequence.constants.MIDI_QUARTER_NOTE)
		assert pattern.steps[pulse].notes[0].velocity == velocities[step_idx % len(velocities)]


def test_ghost_fill_velocity_callable () -> None:

	"""A callable passed to velocity should evaluate per step."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	def my_vel (i: int) -> int:
		return 10 + (i * 5)

	builder.ghost_fill(38, density=1.0, velocity=my_vel, bias="uniform")

	for step_idx in range(16):
		pulse = int(step_idx * 0.25 * subsequence.constants.MIDI_QUARTER_NOTE)
		assert pattern.steps[pulse].notes[0].velocity == 10 + (step_idx * 5)

# --- cellular_1d ---


def test_cellular_places_notes () -> None:

	"""cellular_1d() should place notes from the CA pattern."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	# Use generation 5 where Rule 30 produces multiple active cells
	builder.cellular_1d("hat", rule=30, generation=5, velocity=50)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total > 0


def test_cellular_evolves_across_cycles () -> None:

	"""Different generations should produce different patterns."""

	drum_map = {"hat": 42}

	def _run (gen: int) -> list:
		pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
		builder.rng = random.Random(42)
		builder.cellular_1d("hat", rule=30, generation=gen, velocity=50)
		return sorted(pattern.steps.keys())

	assert _run(5) != _run(10)


def test_cellular_no_overlap () -> None:

	"""cellular_1d with no_overlap should skip positions where the pitch exists."""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)
	builder.cellular_1d("kick", rule=30, generation=5, velocity=40, no_overlap=True)

	# Anchor positions should have exactly 1 kick
	step_dur = 4.0 / 16
	for step_idx in [0, 4, 8, 12]:
		pulse = int(step_idx * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
		if pulse in pattern.steps:
			kick_notes = [n for n in pattern.steps[pulse].notes if n.pitch == 36]
			assert len(kick_notes) == 1


def test_cellular_defaults_to_cycle () -> None:

	"""When generation is not specified, it should use self.cycle."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	# Set cycle to a specific value
	builder.cycle = 7
	builder.cellular_1d("hat", rule=30, velocity=50)

	# Compare with explicit generation=7
	pattern2, builder2 = _make_builder(length=4, drum_note_map=drum_map)
	builder2.rng = random.Random(42)
	builder2.cellular_1d("hat", rule=30, generation=7, velocity=50)

	assert sorted(pattern.steps.keys()) == sorted(pattern2.steps.keys())


def test_cellular_dropout () -> None:

	"""Dropout should reduce the number of placed notes."""

	drum_map = {"hat": 42}

	pattern_full, builder_full = _make_builder(length=4, drum_note_map=drum_map)
	builder_full.rng = random.Random(42)
	builder_full.cellular_1d("hat", rule=30, generation=10, velocity=50, dropout=0.0)

	pattern_drop, builder_drop = _make_builder(length=4, drum_note_map=drum_map)
	builder_drop.rng = random.Random(42)
	builder_drop.cellular_1d("hat", rule=30, generation=10, velocity=50, dropout=0.5)

	full_count = sum(len(s.notes) for s in pattern_full.steps.values())
	drop_count = sum(len(s.notes) for s in pattern_drop.steps.values())

	assert drop_count < full_count


# --- cellular_2d ---


def test_cellular_2d_places_notes () -> None:

	"""cellular_2d() should place notes from live cells in the grid."""

	drum_map = {"kick": 36, "snare": 38, "hat": 42, "open": 46}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	pitches = ["kick", "snare", "hat", "open"]
	builder.cellular_2d(pitches, rule="B368/S245", generation=5, seed=99, density=0.4)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total > 0


def test_cellular_2d_pitch_mapping () -> None:

	"""Each row in the grid should map to the corresponding pitch."""

	drum_map = {"kick": 36, "snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	# Explicit seed: only row 0 has live cells (kick only)
	seed_grid = [[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
	             [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]
	builder.cellular_2d(["kick", "snare"], generation=0, seed=seed_grid)

	all_pitches = [n.pitch for step in pattern.steps.values() for n in step.notes]
	assert 36 in all_pitches      # kick present
	assert 38 not in all_pitches  # snare absent


def test_cellular_2d_velocity_single () -> None:

	"""A single velocity int should apply to all rows."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	seed_grid = [[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
	             [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]]
	builder.cellular_2d(["kick", "hat"], generation=0, seed=seed_grid, velocity=77)

	all_velocities = [n.velocity for step in pattern.steps.values() for n in step.notes]
	assert all(v == 77 for v in all_velocities)


def test_cellular_2d_velocity_list () -> None:

	"""A velocity list should apply per-row velocities."""

	drum_map = {"kick": 36, "hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	# Row 0 (kick): velocity 90. Row 1 (hat): velocity 50.
	seed_grid = [[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
	             [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]]
	builder.cellular_2d(["kick", "hat"], generation=0, seed=seed_grid, velocity=[90, 50])

	kick_velocities = [
		n.velocity for step in pattern.steps.values()
		for n in step.notes if n.pitch == 36
	]
	hat_velocities = [
		n.velocity for step in pattern.steps.values()
		for n in step.notes if n.pitch == 42
	]

	assert all(v == 90 for v in kick_velocities)
	assert all(v == 50 for v in hat_velocities)


def test_cellular_2d_generation_none_uses_cycle () -> None:

	"""When generation is None, it should use self.cycle."""

	drum_map = {"hat": 42, "snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)
	builder.cycle = 5

	pattern2, builder2 = _make_builder(length=4, drum_note_map=drum_map)
	builder2.rng = random.Random(42)

	pitches = ["hat", "snare"]
	builder.cellular_2d(pitches, seed=42, density=0.4)
	builder2.cellular_2d(pitches, generation=5, seed=42, density=0.4)

	assert sorted(pattern.steps.keys()) == sorted(pattern2.steps.keys())


def test_cellular_2d_drum_name_strings () -> None:

	"""Pitches passed as drum name strings resolve to MIDI numbers via drum_note_map."""

	drum_map = {"c4": 60, "g4": 67}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	seed_grid = [[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
	             [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]]
	builder.cellular_2d(["c4", "g4"], generation=0, seed=seed_grid)

	all_pitches = {n.pitch for step in pattern.steps.values() for n in step.notes}
	assert 60 in all_pitches
	assert 67 in all_pitches


def test_cellular_2d_dropout () -> None:

	"""Dropout should reduce the number of placed notes."""

	drum_map = {"hat": 42, "kick": 36}
	pitches = ["hat", "kick"]

	pattern_full, builder_full = _make_builder(length=4, drum_note_map=drum_map)
	builder_full.rng = random.Random(42)
	builder_full.cellular_2d(pitches, seed=7, density=0.6, generation=3, dropout=0.0)

	pattern_drop, builder_drop = _make_builder(length=4, drum_note_map=drum_map)
	builder_drop.rng = random.Random(42)
	builder_drop.cellular_2d(pitches, seed=7, density=0.6, generation=3, dropout=0.8)

	full_count = sum(len(s.notes) for s in pattern_full.steps.values())
	drop_count = sum(len(s.notes) for s in pattern_drop.steps.values())

	assert drop_count < full_count


def test_cellular_2d_invalid_rule_raises () -> None:

	"""An invalid rule string should raise ValueError."""

	import pytest

	drum_map = {"kick": 36}
	_, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	with pytest.raises(ValueError):
		builder.cellular_2d(["kick"], rule="notarule", seed=42)


# --- p.markov() ---


def test_markov_places_notes () -> None:

	"""markov() should place at least one note for a simple chain."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.markov(
		transitions={"root": [("3rd", 2), ("5th", 1)], "3rd": [("root", 1)], "5th": [("root", 1)]},
		pitch_map={"root": 52, "3rd": 56, "5th": 59},
		velocity=80,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())

	assert total > 0


def test_markov_correct_step_count () -> None:

	"""markov() should place int(length / step) notes (one per grid position)."""

	# length=4, spacing=0.25 → 16 notes
	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.markov(
		transitions={"root": [("root", 1)]},
		pitch_map={"root": 52},
		velocity=80,
		spacing=0.25,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())

	assert total == 16


def test_markov_pitches_come_from_pitch_map () -> None:

	"""All placed pitches should be values from the pitch_map dict."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	pitch_map = {"root": 52, "3rd": 56, "5th": 59}

	builder.markov(
		transitions={"root": [("3rd", 3), ("5th", 2)], "3rd": [("root", 1)], "5th": [("root", 1)]},
		pitch_map=pitch_map,
		velocity=80,
	)

	allowed = set(pitch_map.values())

	for step in pattern.steps.values():
		for note in step.notes:
			assert note.pitch in allowed


def test_markov_deterministic () -> None:

	"""Same seed should produce identical pitch sequences."""

	def _run (seed: int) -> list:
		pattern, builder = _make_builder(length=4)
		builder.rng = random.Random(seed)
		builder.markov(
			transitions={"root": [("3rd", 3), ("5th", 2)], "3rd": [("5th", 3), ("root", 2)], "5th": [("root", 3)]},
			pitch_map={"root": 52, "3rd": 56, "5th": 59},
		)
		return [n.pitch for s in sorted(pattern.steps.keys()) for n in pattern.steps[s].notes]

	assert _run(42) == _run(42)
	assert _run(42) != _run(99)


def test_markov_custom_start_state () -> None:

	"""When start is given, the first note should use that state's pitch."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.markov(
		transitions={"root": [("3rd", 1)], "3rd": [("root", 1)], "5th": [("root", 1)]},
		pitch_map={"root": 52, "3rd": 56, "5th": 59},
		start="5th",
		spacing=0.25,
	)

	# The first note placed (beat 0) should be pitch 59 (5th).
	first_note = pattern.steps[0].notes[0]

	assert first_note.pitch == 59


def test_markov_velocity_applied () -> None:

	"""All placed notes should have the specified velocity."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.markov(
		transitions={"root": [("root", 1)]},
		pitch_map={"root": 52},
		velocity=73,
	)

	for step in pattern.steps.values():
		for note in step.notes:
			assert note.velocity == 73


def test_markov_empty_transitions_raises () -> None:

	"""An empty transitions dict should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	with pytest.raises(ValueError, match="transitions dict cannot be empty"):
		builder.markov(transitions={}, pitch_map={"root": 52})


def test_markov_empty_pitch_map_raises () -> None:

	"""An empty pitch_map should raise ValueError."""

	pattern, builder = _make_builder(length=4)

	with pytest.raises(ValueError, match="pitch_map dict cannot be empty"):
		builder.markov(transitions={"root": [("root", 1)]}, pitch_map={})


def test_markov_step_size_controls_density () -> None:

	"""Larger step should place fewer notes over the same pattern length."""

	def _count (step: float) -> int:
		pattern, builder = _make_builder(length=4)
		builder.rng = random.Random(42)
		builder.markov(
			transitions={"root": [("root", 1)]},
			pitch_map={"root": 52},
			spacing=step,
		)
		return sum(len(s.notes) for s in pattern.steps.values())

	# spacing=0.25 → 16 notes; spacing=0.5 → 8 notes
	assert _count(0.25) == 16
	assert _count(0.5) == 8


# --- p.melody() ---


def _melody_state (
	key: str = "C",
	mode: str = "ionian",
	low: int = 60,
	high: int = 72,
	nir_strength: float = 0.5,
	chord_weight: float = 0.0,
	rest_probability: float = 0.0,
	pitch_diversity: float = 1.0,
) -> subsequence.melodic_state.MelodicState:

	"""Return a MelodicState with test defaults."""

	return subsequence.melodic_state.MelodicState(
		key=key, mode=mode, low=low, high=high,
		nir_strength=nir_strength, chord_weight=chord_weight,
		rest_probability=rest_probability, pitch_diversity=pitch_diversity,
	)


def test_melody_places_notes () -> None:

	"""melody() should place at least one note over a default-length pattern."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	ms = _melody_state()
	builder.melody(state=ms)

	total = sum(len(s.notes) for s in pattern.steps.values())

	assert total > 0


def test_melody_correct_step_count () -> None:

	"""melody() should place int(length / step) notes when rest_probability is 0."""

	# length=4, spacing=0.25 → 16 steps, all filled (no rests)
	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	ms = _melody_state(rest_probability=0.0)
	builder.melody(state=ms, spacing=0.25)

	total = sum(len(s.notes) for s in pattern.steps.values())

	assert total == 16


def test_melody_step_size_controls_density () -> None:

	"""Larger step should produce fewer notes over the same pattern length."""

	def _count (step: float) -> int:
		pattern, builder = _make_builder(length=4)
		builder.rng = random.Random(0)
		ms = _melody_state(rest_probability=0.0)
		builder.melody(state=ms, spacing=step)
		return sum(len(s.notes) for s in pattern.steps.values())

	assert _count(0.25) == 16
	assert _count(0.5) == 8


def test_melody_pitches_in_scale (self=None) -> None:

	"""All placed pitches should belong to the scale defined in MelodicState."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	ms = _melody_state(key="C", mode="ionian", low=60, high=72)
	builder.melody(state=ms, spacing=0.25)

	allowed = set(ms._pitch_pool)

	for step in pattern.steps.values():
		for note in step.notes:
			assert note.pitch in allowed


def test_melody_velocity_fixed (self=None) -> None:

	"""A fixed integer velocity should be applied to all placed notes."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	ms = _melody_state(rest_probability=0.0)
	builder.melody(state=ms, velocity=77)

	for step in pattern.steps.values():
		for note in step.notes:
			assert note.velocity == 77


def test_melody_velocity_tuple (self=None) -> None:

	"""A velocity tuple should produce values within the specified range."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	low_vel, high_vel = 60, 100
	ms = _melody_state(rest_probability=0.0)
	builder.melody(state=ms, velocity=(low_vel, high_vel))

	for step in pattern.steps.values():
		for note in step.notes:
			assert low_vel <= note.velocity <= high_vel


def test_melody_deterministic () -> None:

	"""Same seed and same MelodicState should produce identical pitch sequences."""

	def _run (seed: int) -> list:
		pattern, builder = _make_builder(length=4)
		builder.rng = random.Random(seed)
		ms = _melody_state()
		builder.melody(state=ms, spacing=0.25, velocity=80)
		return sorted(
			(beat, n.pitch, n.velocity)
			for beat, step in pattern.steps.items()
			for n in step.notes
		)

	assert _run(42) == _run(42)
	assert _run(42) != _run(99)


def test_melody_rest_probability_produces_gaps () -> None:

	"""With rest_probability=0.5, fewer than all steps should contain a note."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(7)

	ms = _melody_state(rest_probability=0.5)
	builder.melody(state=ms, spacing=0.25)

	total = sum(len(s.notes) for s in pattern.steps.values())

	assert total < 16


def test_melody_chord_tones_passed_through () -> None:

	"""chord_tones list should be forwarded to MelodicState without error."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	ms = _melody_state(chord_weight=0.8, rest_probability=0.0)
	chord_tones = [60, 64, 67]

	# Should not raise; notes should be placed
	builder.melody(state=ms, spacing=0.5, chord_tones=chord_tones)

	total = sum(len(s.notes) for s in pattern.steps.values())

	assert total == 8


# ─────────────────────────────────────────────────────────────
# thin()
# ─────────────────────────────────────────────────────────────

def _count_notes_at_pitch (pattern: subsequence.pattern.Pattern, midi_pitch: int) -> int:
	"""Count notes with a given MIDI pitch across all steps."""
	return sum(
		1
		for step in pattern.steps.values()
		for note in step.notes
		if note.pitch == midi_pitch
	)


def test_thin_amount_zero () -> None:

	"""amount=0.0 must remove nothing."""

	drum_map = {"hat": 42, "kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(0)

	builder.hit_steps("hat", range(16), velocity=80)
	before = _count_notes_at_pitch(pattern, 42)

	builder.thin("hat", "strength", amount=0.0)
	after = _count_notes_at_pitch(pattern, 42)

	assert after == before


def test_thin_amount_one () -> None:

	"""amount=1.0 with uniform strategy removes all notes for the instrument."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(0)

	builder.hit_steps("hat", range(16), velocity=80)
	builder.thin("hat", "uniform", amount=1.0)

	assert _count_notes_at_pitch(pattern, 42) == 0


def test_thin_per_instrument () -> None:

	"""thin() should only affect the named instrument, not other pitches."""

	drum_map = {"hat": 42, "kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(0)

	builder.hit_steps("hat",  range(16), velocity=80)
	builder.hit_steps("kick", [0, 4, 8, 12], velocity=100)

	kick_before = _count_notes_at_pitch(pattern, 36)

	# Thin hats completely
	builder.thin("hat", "uniform", amount=1.0)

	assert _count_notes_at_pitch(pattern, 42) == 0
	assert _count_notes_at_pitch(pattern, 36) == kick_before


def test_thin_sixteenths_preserves_beats () -> None:

	"""sixteenths strategy should remove e/a positions and preserve downbeats."""

	# Strategy mirrors ghost_fill bias "sixteenths" but inverted:
	# ghost_fill "sixteenths" adds to e/a; thin "sixteenths" removes from e/a.
	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	# Fill all 16 steps
	builder.hit_steps("hat", range(16), velocity=80)

	# After thinning with amount=1.0, downbeats (steps 0,4,8,12) should
	# be protected (priority ~0.05) while e/a steps (priority 1.0) are gone.
	builder.thin("hat", "sixteenths", amount=1.0, rng=random.Random(42))

	step_dur = 4.0 / 16
	downbeat_notes = 0
	for step_idx in [0, 4, 8, 12]:
		pulse = int(step_idx * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
		if pulse in pattern.steps:
			downbeat_notes += sum(1 for n in pattern.steps[pulse].notes if n.pitch == 42)

	assert downbeat_notes > 0


def test_thin_strength_drops_weakest_first () -> None:

	"""strength strategy should drop e/a before & before downbeats."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(99)

	builder.hit_steps("hat", range(16), velocity=80)

	# amount=0.4: enough to drop most e/a (priority 1.0 * 0.4 = 0.4)
	# but not downbeats (priority 0.05 * 0.4 = 0.02 → almost never dropped)
	builder.thin("hat", "strength", amount=0.4, rng=random.Random(99))

	step_dur = 4.0 / 16
	downbeat_notes = 0
	ea_notes = 0

	for step_idx in range(16):
		pulse = int(step_idx * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
		count = 0
		if pulse in pattern.steps:
			count = sum(1 for n in pattern.steps[pulse].notes if n.pitch == 42)
		pos = step_idx % 4
		if pos == 0:
			downbeat_notes += count
		elif pos != 2:  # e and a positions
			ea_notes += count

	assert downbeat_notes >= ea_notes


def test_thin_custom_list () -> None:

	"""A custom float list should be used as drop priorities."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(0)

	builder.hit_steps("hat", range(16), velocity=80)

	# Drop all steps except step 0 (priority 0.0 = never dropped)
	priorities = [0.0] + [1.0] * 15
	builder.thin("hat", priorities, amount=1.0)

	step_dur = 4.0 / 16
	pulse_0 = int(0 * step_dur * subsequence.constants.MIDI_QUARTER_NOTE)
	assert _count_notes_at_pitch(pattern, 42) == 1
	assert pulse_0 in pattern.steps


def test_thin_invalid_strategy () -> None:

	"""Unknown strategy string should raise ValueError."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.hit_steps("hat", range(16), velocity=80)

	with pytest.raises(ValueError):
		builder.thin("hat", "no_such_strategy", amount=0.5)


def test_thin_invalid_list_length () -> None:

	"""Custom list with wrong length should raise ValueError."""

	drum_map = {"hat": 42}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.hit_steps("hat", range(16), velocity=80)

	with pytest.raises(ValueError):
		builder.thin("hat", [0.5] * 8, amount=0.5)  # grid=16, list len=8


def test_thin_deterministic () -> None:

	"""Same seed should always produce the same thinned pattern."""

	drum_map = {"hat": 42}

	def _run (seed: int) -> list:
		pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
		builder.hit_steps("hat", range(16), velocity=80)
		builder.thin("hat", "strength", amount=0.5, rng=random.Random(seed))
		return sorted(pattern.steps.keys())

	assert _run(7) == _run(7)
	assert _run(7) != _run(8)  # different seeds → different results (overwhelmingly likely)


def test_thin_no_pitch_thins_all () -> None:

	"""pitch=None with amount=1.0 removes all notes regardless of pitch."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	# Place notes at two different integer pitches
	for step in range(16):
		beat = step * 0.25
		builder.note(pitch=60, beat=beat, velocity=80, duration=0.1)
		builder.note(pitch=64, beat=beat, velocity=80, duration=0.1)

	total_before = sum(len(s.notes) for s in pattern.steps.values())
	assert total_before == 32

	builder.thin(strategy="uniform", amount=1.0)

	total_after = sum(len(s.notes) for s in pattern.steps.values())
	assert total_after == 0


def test_thin_no_pitch_amount_zero () -> None:

	"""pitch=None with amount=0.0 removes nothing."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	for step in range(16):
		beat = step * 0.25
		builder.note(pitch=60, beat=beat, velocity=80, duration=0.1)
		builder.note(pitch=64, beat=beat, velocity=80, duration=0.1)

	total_before = sum(len(s.notes) for s in pattern.steps.values())

	builder.thin(strategy="strength", amount=0.0)

	total_after = sum(len(s.notes) for s in pattern.steps.values())
	assert total_after == total_before


def test_thin_no_pitch_respects_strategy () -> None:

	"""pitch=None still honours the strategy — priority-0 positions are never thinned."""

	pattern, builder = _make_builder(length=4)

	# Fill all 16 steps with two pitches
	for step in range(16):
		builder.note(pitch=60, beat=step * 0.25, velocity=80, duration=0.1)
		builder.note(pitch=64, beat=step * 0.25, velocity=80, duration=0.1)

	# Custom strategy: first 8 steps priority=1.0 (always drop with amount=1.0),
	# last 8 steps priority=0.0 (never drop).  This is fully deterministic.
	custom = [1.0] * 8 + [0.0] * 8
	builder.thin(strategy=custom, amount=1.0, grid=16)

	total = sum(len(s.notes) for s in pattern.steps.values())
	# Steps 0-7: 16 notes removed.  Steps 8-15: 16 notes protected.
	assert total == 16


def test_thin_no_pitch_deletes_empty_steps () -> None:

	"""pitch=None should delete entire steps (not leave empty step objects)."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(0)

	# Single pitch per step so each step has exactly one note
	for step in range(16):
		builder.note(pitch=60, beat=step * 0.25, velocity=80, duration=0.1)

	builder.thin(strategy="uniform", amount=1.0)

	# All steps should be fully removed from the dict
	assert len(pattern.steps) == 0


# --- p.lsystem() ---


def test_lsystem_places_notes () -> None:

	"""lsystem() should place at least one note for a simple deterministic rule."""

	drum_map = {"kick": 36}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": "kick"},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=3,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total > 0


def test_lsystem_autofit_places_all_mapped_symbols () -> None:

	"""With spacing=None, every mapped symbol in the expanded string gets a note."""

	# "A" maps to a pitch; "B" is a rest.
	# Fibonacci gen=4: "ABAABABA" — 5 A's, 3 B's → 5 notes expected.
	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": 60},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=4,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total == 5


def test_lsystem_fixed_step_truncates () -> None:

	"""With a fixed step, symbols past the bar end are ignored."""

	# spacing=0.5 in a 4-beat bar fits exactly 8 symbols.
	# generations=6 produces 13 Fibonacci symbols — only first 8 used.
	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	# "A" maps to note, "B" is rest — we just check total notes ≤ 8.
	builder.lsystem(
		pitch_map={"A": 60, "B": 62},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=6,
		spacing=0.5,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total <= 8


def test_lsystem_unmapped_symbols_are_rests () -> None:

	"""Characters not in pitch_map produce silence; time still advances."""

	# Fibonacci gen=2: "ABA" — 2 A's, 1 B. Only A is mapped → 2 notes.
	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": 60},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=2,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total == 2


def test_lsystem_empty_pitch_map_produces_silence () -> None:

	"""An empty pitch_map should produce no notes."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=5,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total == 0


def test_lsystem_pitches_from_map () -> None:

	"""All placed note pitches should be values from pitch_map."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": 60, "B": 64},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=4,
	)

	all_pitches = {n.pitch for step in pattern.steps.values() for n in step.notes}
	assert all_pitches <= {60, 64}


def test_lsystem_drum_names () -> None:

	"""String values in pitch_map resolve to MIDI via drum_note_map."""

	drum_map = {"kick": 36, "snare": 38}
	pattern, builder = _make_builder(length=4, drum_note_map=drum_map)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": "kick", "B": "snare"},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=3,
	)

	all_pitches = {n.pitch for step in pattern.steps.values() for n in step.notes}
	assert all_pitches <= {36, 38}


def test_lsystem_velocity_fixed () -> None:

	"""A fixed integer velocity applies to all notes."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": 60, "B": 62},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=4,
		velocity=73,
	)

	all_velocities = [n.velocity for step in pattern.steps.values() for n in step.notes]
	assert all(v == 73 for v in all_velocities)


def test_lsystem_velocity_tuple () -> None:

	"""A velocity (low, high) tuple randomises per note within the range."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	builder.lsystem(
		pitch_map={"A": 60, "B": 62},
		axiom="A",
		rules={"A": "AB", "B": "A"},
		generations=4,
		velocity=(60, 100),
	)

	all_velocities = [n.velocity for step in pattern.steps.values() for n in step.notes]
	assert all(60 <= v <= 100 for v in all_velocities)


def test_lsystem_deterministic () -> None:

	"""Same rng produces identical pitch sequence; different rng may differ."""

	def _run (seed: int) -> list:
		pattern, builder = _make_builder(length=4)
		builder.rng = random.Random(seed)
		builder.lsystem(
			pitch_map={"A": 60, "B": 62},
			axiom="A",
			rules={"A": [("AB", 3), ("BA", 1)], "B": "A"},
			generations=4,
			velocity=80,
		)
		# Sort by pulse position, return pitch list to detect stochastic differences.
		return [n.pitch for pos in sorted(pattern.steps) for n in pattern.steps[pos].notes]

	assert _run(42) == _run(42)
	# Different seeds produce different stochastic expansions (overwhelmingly likely).
	assert _run(1) != _run(2)


def test_lsystem_generations_zero () -> None:

	"""generations=0 uses the axiom directly."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(42)

	# Axiom "AB" → 2 symbols, both mapped → 2 notes.
	builder.lsystem(
		pitch_map={"A": 60, "B": 64},
		axiom="AB",
		rules={"A": "ABC", "B": "A"},
		generations=0,
	)

	total = sum(len(s.notes) for s in pattern.steps.values())
	assert total == 2


def test_lsystem_stochastic_rules () -> None:

	"""Stochastic rules produce valid output without errors."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(7)

	builder.lsystem(
		pitch_map={"A": 60, "B": 62, "C": 64},
		axiom="A",
		rules={"A": [("AB", 2), ("AC", 1)], "B": "A", "C": "BA"},
		generations=4,
	)

	all_pitches = {n.pitch for step in pattern.steps.values() for n in step.notes}
	assert all_pitches <= {60, 62, 64}


# --- program_change ---


def test_program_change_no_bank () -> None:

	"""program_change() with no bank args emits a single program_change event."""

	pattern, builder = _make_builder(length=4)
	builder.program_change(48)

	assert len(pattern.cc_events) == 1
	assert pattern.cc_events[0].message_type == 'program_change'
	assert pattern.cc_events[0].value == 48


def test_program_change_bank_msb_only () -> None:

	"""bank_msb emits CC 0 before the program change."""

	pattern, builder = _make_builder(length=4)
	builder.program_change(10, bank_msb=81)

	assert len(pattern.cc_events) == 2
	cc, pc = pattern.cc_events
	assert cc.message_type == 'control_change'
	assert cc.control == 0
	assert cc.value == 81
	assert pc.message_type == 'program_change'
	assert pc.value == 10


def test_program_change_bank_lsb_only () -> None:

	"""bank_lsb emits CC 32 before the program change."""

	pattern, builder = _make_builder(length=4)
	builder.program_change(10, bank_lsb=3)

	assert len(pattern.cc_events) == 2
	cc, pc = pattern.cc_events
	assert cc.message_type == 'control_change'
	assert cc.control == 32
	assert cc.value == 3
	assert pc.message_type == 'program_change'


def test_program_change_bank_both () -> None:

	"""Both bank_msb and bank_lsb emit CC 0, CC 32, then program change — in order."""

	pattern, builder = _make_builder(length=4)
	builder.program_change(48, bank_msb=81, bank_lsb=0)

	assert len(pattern.cc_events) == 3
	msb, lsb, pc = pattern.cc_events
	assert msb.message_type == 'control_change' and msb.control == 0  and msb.value == 81
	assert lsb.message_type == 'control_change' and lsb.control == 32 and lsb.value == 0
	assert pc.message_type == 'program_change'  and pc.value == 48


def test_program_change_bank_same_pulse () -> None:

	"""All three events share the same pulse position as the beat argument."""

	pattern, builder = _make_builder(length=4)
	builder.program_change(10, beat=2.0, bank_msb=1, bank_lsb=0)

	pulses = {e.pulse for e in pattern.cc_events}
	assert len(pulses) == 1  # all at the same pulse


def test_program_change_clamped () -> None:

	"""Program and bank values outside 0–127 are clamped."""

	pattern, builder = _make_builder(length=4)
	builder.program_change(200, bank_msb=-5, bank_lsb=999)

	msb, lsb, pc = pattern.cc_events
	assert msb.value == 0
	assert lsb.value == 127
	assert pc.value == 127


# --- p.data — shared inter-pattern state ---


def test_data_read_write () -> None:

	"""p.data supports standard dict read/write."""

	shared = {}
	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern, cycle=0, default_grid=16, data=shared
	)

	builder.data["root"] = 60
	assert builder.data["root"] == 60
	assert shared["root"] == 60


def test_data_get_default_when_missing () -> None:

	"""p.data.get() returns the default when the key is absent."""

	shared = {}
	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern, cycle=0, default_grid=16, data=shared
	)

	assert builder.data.get("missing") is None
	assert builder.data.get("missing", 48) == 48


def test_data_cross_pattern () -> None:

	"""Two builders sharing the same dict can read each other's writes."""

	shared = {}
	pat_a = subsequence.pattern.Pattern(channel=0, length=4)
	pat_b = subsequence.pattern.Pattern(channel=1, length=4)

	builder_a = subsequence.pattern_builder.PatternBuilder(
		pattern=pat_a, cycle=0, default_grid=16, data=shared
	)
	builder_b = subsequence.pattern_builder.PatternBuilder(
		pattern=pat_b, cycle=0, default_grid=16, data=shared
	)

	builder_a.data["bass_root"] = 36
	assert builder_b.data.get("bass_root") == 36


def test_data_persists_across_rebuilds () -> None:

	"""Values survive a rebuild (new builder instance, same dict reference)."""

	shared = {}
	pat = subsequence.pattern.Pattern(channel=0, length=4)

	builder_1 = subsequence.pattern_builder.PatternBuilder(
		pattern=pat, cycle=0, default_grid=16, data=shared
	)
	builder_1.data["density"] = 0.75

	builder_2 = subsequence.pattern_builder.PatternBuilder(
		pattern=pat, cycle=1, default_grid=16, data=shared
	)
	assert builder_2.data.get("density") == 0.75


def test_data_without_composition_uses_isolated_dict () -> None:

	"""A builder created without data= gets its own empty dict and does not crash."""

	pattern, builder = _make_builder()
	builder.data["x"] = 42
	assert builder.data["x"] == 42


# --- thue_morse ---


def test_thue_morse_places_notes () -> None:

	"""thue_morse places at least one note (sequence has 1s)."""

	pattern, builder = _make_builder(length=4)
	builder.thue_morse(60, velocity=80)
	assert len(pattern.steps) > 0


def test_thue_morse_single_pitch_count () -> None:

	"""Note count equals number of 1s in the Thue-Morse sequence."""

	import subsequence.sequence_utils
	pattern, builder = _make_builder(length=4)
	builder.thue_morse(60, velocity=80)
	expected = sum(subsequence.sequence_utils.thue_morse(16))
	assert len(pattern.steps) == expected


def test_thue_morse_two_pitch_mode () -> None:

	"""In two-pitch mode, all 16 grid steps produce a note."""

	pattern, builder = _make_builder(length=4)
	builder.thue_morse(60, pitch_b=64, velocity=80)
	assert len(pattern.steps) == 16


def test_thue_morse_no_overlap () -> None:

	"""no_overlap=True prevents duplicate pitches at the same pulse."""

	pattern, builder = _make_builder(length=4)
	# Place pitch 60 at every step first, then thue_morse with no_overlap
	for i in range(16):
		builder.note(pitch=60, beat=i * 0.25, velocity=90, duration=0.1)
	initial_count = len(pattern.steps)
	builder.thue_morse(60, no_overlap=True, velocity=80)
	# no_overlap should not add any new steps (pitch 60 already present everywhere)
	assert len(pattern.steps) == initial_count


# --- de_bruijn ---


def test_de_bruijn_places_notes () -> None:

	"""de_bruijn places notes for each symbol in the sequence."""

	pattern, builder = _make_builder(length=4)
	builder.de_bruijn([60, 62, 64], window=2)
	assert len(pattern.steps) > 0


def test_de_bruijn_autofit_note_count () -> None:

	"""Auto-fit mode places exactly k**n notes."""

	pattern, builder = _make_builder(length=4)
	builder.de_bruijn([60, 62], window=3)  # 2**3 = 8 notes
	assert len(pattern.steps) == 8


def test_de_bruijn_fixed_step_truncates () -> None:

	"""Fixed step mode places at most int(length / step) notes."""

	pattern, builder = _make_builder(length=4)
	builder.de_bruijn([60, 62], window=4, spacing=0.25)  # 2**4=16 notes, 4/0.25=16 slots
	assert len(pattern.steps) <= 16


def test_de_bruijn_pitches_from_list () -> None:

	"""All placed pitches are from the provided list."""

	pattern, builder = _make_builder(length=4)
	pitches = [60, 62, 64]
	builder.de_bruijn(pitches, window=2)
	placed = {note.pitch for step in pattern.steps.values() for note in step.notes}
	assert placed.issubset(set(pitches))


# --- fibonacci ---


def test_fibonacci_places_notes () -> None:

	"""fibonacci places the requested number of notes."""

	pattern, builder = _make_builder(length=4)
	builder.fibonacci(60, steps=8, velocity=80)
	assert len(pattern.steps) == 8


def test_fibonacci_correct_count () -> None:

	"""Total placed notes equals steps parameter."""

	pattern, builder = _make_builder(length=4)
	builder.fibonacci(60, steps=11)
	assert len(pattern.steps) == 11


def test_fibonacci_velocity_tuple () -> None:

	"""Velocity tuple produces velocities within the given range."""

	pattern, builder = _make_builder(length=4)
	builder.rng = random.Random(1)
	builder.fibonacci(60, steps=8, velocity=(60, 100))
	vels = [note.velocity for step in pattern.steps.values() for note in step.notes]
	assert all(60 <= v <= 100 for v in vels)


# --- lorenz ---


def test_lorenz_places_notes () -> None:

	"""lorenz places notes at each step."""

	pattern, builder = _make_builder(length=4)
	builder.lorenz([60, 62, 64, 65, 67], spacing=0.25)
	assert len(pattern.steps) > 0


def test_lorenz_correct_step_count () -> None:

	"""lorenz places int(length / step) notes."""

	pattern, builder = _make_builder(length=4)
	builder.lorenz([60, 62, 64, 65, 67], spacing=0.25)
	assert len(pattern.steps) == 16


def test_lorenz_pitches_from_list () -> None:

	"""All placed pitches are from the pitches list."""

	pattern, builder = _make_builder(length=4)
	pitches = [60, 62, 64]
	builder.lorenz(pitches, spacing=0.5)
	placed = {note.pitch for step in pattern.steps.values() for note in step.notes}
	assert placed.issubset(set(pitches))


def test_lorenz_custom_mapping () -> None:

	"""Custom mapping callable controls pitch, velocity, duration."""

	pattern, builder = _make_builder(length=4)

	def my_map (x, y, z):
		return (60, 90, 0.1)

	builder.lorenz([60, 62], spacing=0.5, mapping=my_map)
	vels = [note.velocity for step in pattern.steps.values() for note in step.notes]
	assert all(v == 90 for v in vels)


# --- reaction_diffusion ---


def test_reaction_diffusion_places_notes () -> None:

	"""reaction_diffusion places at least one note at default threshold."""

	pattern, builder = _make_builder(length=4)
	builder.reaction_diffusion(60, threshold=0.3, steps=500)
	assert len(pattern.steps) > 0


def test_reaction_diffusion_threshold_affects_density () -> None:

	"""Lower threshold produces at least as many notes as higher threshold."""

	pattern_lo, builder_lo = _make_builder(length=4)
	builder_lo.reaction_diffusion(60, threshold=0.2, steps=500)

	pattern_hi, builder_hi = _make_builder(length=4)
	builder_hi.reaction_diffusion(60, threshold=0.8, steps=500)

	assert len(pattern_lo.steps) >= len(pattern_hi.steps)


def test_reaction_diffusion_dropout_reduces_notes () -> None:

	"""dropout > 0 produces fewer notes on average."""

	import random as stdlib_random
	counts = []
	for seed in range(10):
		p, b = _make_builder(length=4)
		b.rng = stdlib_random.Random(seed)
		b.reaction_diffusion(60, threshold=0.3, dropout=0.8, steps=300)
		counts.append(len(p.steps))

	p2, b2 = _make_builder(length=4)
	b2.reaction_diffusion(60, threshold=0.3, dropout=0.0, steps=300)
	no_dropout_count = len(p2.steps)

	assert sum(counts) / len(counts) < no_dropout_count


# --- self_avoiding_walk ---


def test_self_avoiding_walk_places_notes () -> None:

	"""self_avoiding_walk places notes at each step."""

	pattern, builder = _make_builder(length=4)
	builder.self_avoiding_walk([60, 62, 64, 65, 67, 69, 71, 72], spacing=0.25)
	assert len(pattern.steps) > 0


def test_self_avoiding_walk_correct_count () -> None:

	"""Total notes equals int(length / step)."""

	pattern, builder = _make_builder(length=4)
	builder.self_avoiding_walk([60, 62, 64, 65, 67, 69, 71, 72], spacing=0.25)
	assert len(pattern.steps) == 16


def test_self_avoiding_walk_pitches_from_list () -> None:

	"""All placed pitches are from the provided list."""

	pattern, builder = _make_builder(length=4)
	pitches = [60, 62, 64, 65, 67]
	builder.self_avoiding_walk(pitches, spacing=0.25)
	placed = {note.pitch for step in pattern.steps.values() for note in step.notes}
	assert placed.issubset(set(pitches))


def test_self_avoiding_walk_deterministic () -> None:

	"""Same seed produces identical pitch sequence."""

	pattern1, builder1 = _make_builder(length=4)
	builder1.rng = random.Random(42)
	builder1.self_avoiding_walk([60, 62, 64, 65, 67], spacing=0.25)

	pattern2, builder2 = _make_builder(length=4)
	builder2.rng = random.Random(42)
	builder2.self_avoiding_walk([60, 62, 64, 65, 67], spacing=0.25)

	pitches1 = [note.pitch for step in sorted(pattern1.steps) for note in pattern1.steps[step].notes]
	pitches2 = [note.pitch for step in sorted(pattern2.steps) for note in pattern2.steps[step].notes]
	assert pitches1 == pitches2


# ── quantize(strength=) ──────────────────────────────────────────────────────


def _pitches_in_pattern (pattern) -> list:
	return [note.pitch for step in sorted(pattern.steps) for note in pattern.steps[step].notes]


def _place_chromatic_notes (builder, pitches: list, length: float = 4) -> None:
	"""Place a list of pitches at evenly spaced beats."""
	spacing = length / len(pitches)
	for i, p in enumerate(pitches):
		builder.note(p, beat=i * spacing, duration=spacing * 0.9)


def test_quantize_strength_one_snaps_all () -> None:

	"""strength=1.0 (default) must quantize every note — identical to old behaviour."""

	# C major pitch classes: [0, 2, 4, 5, 7, 9, 11]
	# Place C# (61), D# (63), F# (66) — all outside C major
	pattern, builder = _make_builder(length=4)
	_place_chromatic_notes(builder, [61, 63, 66])
	builder.quantize("C", "ionian", strength=1.0)

	pitches = _pitches_in_pattern(pattern)
	# C# → C (60), D# → E (64), F# → G (67)
	assert 61 not in pitches
	assert 63 not in pitches
	assert 66 not in pitches


def test_quantize_strength_zero_leaves_all_unchanged () -> None:

	"""strength=0.0 must leave every note pitch untouched."""

	pattern, builder = _make_builder(length=4)
	_place_chromatic_notes(builder, [61, 63, 66])
	builder.quantize("C", "ionian", strength=0.0)

	pitches = _pitches_in_pattern(pattern)
	assert pitches == [61, 63, 66]


def test_quantize_default_strength_unchanged () -> None:

	"""Omitting strength= must behave identically to strength=1.0."""

	pattern1, builder1 = _make_builder(length=4)
	_place_chromatic_notes(builder1, [61, 63, 66])
	builder1.quantize("C", "ionian")

	pattern2, builder2 = _make_builder(length=4)
	_place_chromatic_notes(builder2, [61, 63, 66])
	builder2.quantize("C", "ionian", strength=1.0)

	assert _pitches_in_pattern(pattern1) == _pitches_in_pattern(pattern2)


def test_quantize_strength_partial_is_reproducible () -> None:

	"""Same RNG seed + same strength must produce the same set of quantized notes."""

	pitches_in = [61, 63, 66, 58, 70, 73, 56, 69]

	pattern1, builder1 = _make_builder(length=4)
	builder1.rng = random.Random(99)
	_place_chromatic_notes(builder1, pitches_in)
	builder1.quantize("C", "ionian", strength=0.5)

	pattern2, builder2 = _make_builder(length=4)
	builder2.rng = random.Random(99)
	_place_chromatic_notes(builder2, pitches_in)
	builder2.quantize("C", "ionian", strength=0.5)

	assert _pitches_in_pattern(pattern1) == _pitches_in_pattern(pattern2)


def test_quantize_strength_partial_quantizes_some_notes () -> None:

	"""strength=0.5 should quantize roughly half the notes (statistical check over many notes)."""

	# Place 200 notes all on C# (61), which is outside C major.
	# quantize_pitch prefers upward, so C# (61) → D (62).
	# With strength=0.5, ~50% should be snapped to D (62), rest stay at C# (61).
	n = 200
	pattern, builder = _make_builder(length=n * 0.25)
	builder.rng = random.Random(7)
	for i in range(n):
		builder.note(61, beat=i * 0.25, duration=0.2)
	builder.quantize("C", "ionian", strength=0.5)

	pitches = _pitches_in_pattern(pattern)
	quantized_count = sum(1 for p in pitches if p == 62)   # snapped up to D
	unquantized_count = sum(1 for p in pitches if p == 61)  # left as C#

	# Allow ±15% tolerance
	assert 0.35 * n <= quantized_count <= 0.65 * n, (
		f"Expected ~{n // 2} quantized, got {quantized_count}/{n}"
	)
	assert quantized_count + unquantized_count == n


# ---------------------------------------------------------------------------
# p.phrase()
# ---------------------------------------------------------------------------

def _make_builder_at_bar (bar: int) -> "subsequence.pattern_builder.PatternBuilder":
	_, builder = _make_builder()
	builder.bar = bar
	return builder

def test_phrase_first ():
	builder = _make_builder_at_bar(0)
	ph = builder.phrase(4)
	assert ph.bar == 0
	assert ph.first is True
	assert ph.last is False

def test_phrase_last ():
	builder = _make_builder_at_bar(3)
	ph = builder.phrase(4)
	assert ph.bar == 3
	assert ph.first is False
	assert ph.last is True

def test_phrase_middle ():
	builder = _make_builder_at_bar(2)
	ph = builder.phrase(4)
	assert ph.bar == 2
	assert ph.first is False
	assert ph.last is False

def test_phrase_progress ():
	assert _make_builder_at_bar(0).phrase(4).progress == pytest.approx(0.0)
	assert _make_builder_at_bar(2).phrase(4).progress == pytest.approx(0.5)
	assert _make_builder_at_bar(3).phrase(4).progress == pytest.approx(0.75)

def test_phrase_wraps_correctly ():
	# bar=5 with phrase(4) → position 1 (5 % 4 == 1)
	ph = _make_builder_at_bar(5).phrase(4)
	assert ph.bar == 1
	assert ph.first is False
	assert ph.last is False

def test_phrase_single_bar ():
	ph = _make_builder_at_bar(0).phrase(1)
	assert ph.bar == 0
	assert ph.first is True
	assert ph.last is True
	assert ph.progress == pytest.approx(0.0)

def test_phrase_length_8 ():
	# bar=2 with phrase(8) → "bar 3 of every 8" in user's example
	ph = _make_builder_at_bar(2).phrase(8)
	assert ph.bar == 2
	assert ph.first is False
	assert ph.last is False

def test_phrase_last_of_16 ():
	# bar=15 with phrase(16) → last bar before every 16th
	assert _make_builder_at_bar(15).phrase(16).last is True

def test_phrase_cycle_through_4_bars ():
	positions = [_make_builder_at_bar(bar).phrase(4).bar for bar in range(8)]
	assert positions == [0, 1, 2, 3, 0, 1, 2, 3]


def test_velocity_ramp_returns_int_list ():
	_, builder = _make_builder(default_grid=4, length=4)
	result = builder.velocity_ramp(0, 100, "linear")
	assert len(result) == 4
	assert all(isinstance(v, int) for v in result)
	assert result[0] == 0
	assert result[-1] == 100


def test_velocity_ramp_clamped ():
	_, builder = _make_builder(default_grid=4, length=4)
	result = builder.velocity_ramp(0, 200, "linear")
	assert all(0 <= v <= 127 for v in result)


def test_velocity_ramp_uses_grid ():
	_, builder = _make_builder(default_grid=8, length=8)
	result = builder.velocity_ramp(50, 100)
	assert len(result) == 8
