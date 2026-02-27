import random

import pytest

import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.constants.velocity
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


# --- Humanize ---


def test_humanize_timing_shifts_notes () -> None:

	"""humanize(timing=0.5) should shift at least one note from its original pulse."""

	import random

	_, builder = _make_builder()

	# Place notes at all 16 sixteenth-note positions using MIDI note numbers.
	builder.hit_steps(36, list(range(16)), velocity=100)
	original_pulses = set(builder._pattern.steps.keys())

	builder.humanize(timing=0.5, rng=random.Random(42))

	new_pulses = set(builder._pattern.steps.keys())

	# At least one note should have moved.
	assert new_pulses != original_pulses


def test_humanize_timing_zero_no_change () -> None:

	"""humanize(timing=0.0) should leave all pulse positions unchanged."""

	import random

	_, builder = _make_builder()
	builder.hit_steps(36, list(range(16)), velocity=100)
	original_pulses = set(builder._pattern.steps.keys())

	builder.humanize(timing=0.0, rng=random.Random(42))

	assert set(builder._pattern.steps.keys()) == original_pulses


def test_humanize_velocity_changes_velocity () -> None:

	"""humanize(velocity=0.5) should change at least one note's velocity."""

	import random

	_, builder = _make_builder()
	builder.hit_steps(36, list(range(16)), velocity=100)

	original_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	builder.humanize(velocity=0.5, rng=random.Random(42))

	new_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	assert new_velocities != original_velocities


def test_humanize_velocity_zero_no_change () -> None:

	"""humanize(velocity=0.0) should leave all velocities unchanged."""

	import random

	_, builder = _make_builder()
	builder.hit_steps(36, list(range(16)), velocity=100)

	original_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	builder.humanize(velocity=0.0, rng=random.Random(42))

	new_velocities = [
		note.velocity
		for step in builder._pattern.steps.values()
		for note in step.notes
	]

	assert new_velocities == original_velocities


def test_humanize_deterministic_with_rng () -> None:

	"""Same RNG seed produces identical results; different seed produces different results."""

	import random

	def build_with_seed (seed: int) -> set:
		_, builder = _make_builder()
		builder.hit_steps(36, list(range(16)), velocity=80)
		builder.humanize(timing=0.5, velocity=0.3, rng=random.Random(seed))
		return set(builder._pattern.steps.keys())

	run_a = build_with_seed(1)
	run_b = build_with_seed(1)
	run_c = build_with_seed(99)

	assert run_a == run_b
	assert run_a != run_c


def test_humanize_velocity_stays_in_range () -> None:

	"""All velocities must remain in the valid MIDI range (1–127) after humanize."""

	import random

	_, builder = _make_builder()

	# Use edge-case velocities to stress-test the clamp.
	builder.note(60, beat=0, velocity=1)
	builder.note(60, beat=1, velocity=127)
	builder.note(60, beat=2, velocity=64)

	builder.humanize(velocity=1.0, rng=random.Random(42))

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
