import random

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


def test_hit_steps_custom_step_count () -> None:

	"""A custom step_count of 8 on a 4-beat pattern should place steps at half-beat intervals."""

	pattern, builder = _make_builder(length=4)

	builder.hit_steps(60, steps=[0, 2, 4, 6], velocity=100, step_count=8)

	# step_duration = 4 / 8 = 0.5 beats per step
	expected_pulses = [
		int(0.0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(2.0 * subsequence.constants.MIDI_QUARTER_NOTE),
		int(3.0 * subsequence.constants.MIDI_QUARTER_NOTE),
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

		builder.fill(60, step=0.25, velocity=100)
		builder.dropout(probability=0.5)

		return sum(len(step.notes) for step in pattern.steps.values())

	run_1 = build_with_seed(42)
	run_2 = build_with_seed(42)

	assert run_1 == run_2


# --- Float length and set_length ---


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

	# step=0.5 over 3.5 beats = 7 notes (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
	builder.fill(60, step=0.5, velocity=100)

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
	builder.fill(60, step=0.5, velocity=100)

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


def test_sequence_custom_step_count () -> None:

	"""step_count=8 should map steps to correct beat positions."""

	pattern, builder = _make_builder(length=4)

	# step_count=8 over 4 beats = 0.5 beats per step.
	builder.sequence([0, 2, 4, 6], pitches=60, step_count=8)

	ppq = subsequence.constants.MIDI_QUARTER_NOTE
	expected_pulses = [0, ppq, ppq * 2, ppq * 3]

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
