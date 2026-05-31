"""Tests for the unified velocity API: every note-placement method must
accept either an ``int`` or a ``(low, high)`` tuple."""

import random
import typing

import pytest

import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.constants.velocity
import subsequence.pattern
import subsequence.pattern_builder


def _make_builder (channel: int = 0, length: float = 4, drum_note_map: dict = None, default_grid: int = None, seed: int = 0) -> tuple:

	"""Mirror of the fixture in tests/test_pattern_builder.py."""

	if default_grid is None:
		default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
	pat = subsequence.pattern.Pattern(channel=channel, length=length)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pat,
		cycle=0,
		drum_note_map=drum_note_map,
		default_grid=default_grid,
		rng=random.Random(seed),
	)
	return pat, builder


# --- _resolve_velocity helper itself ---


def test_resolve_velocity_int_returns_unchanged () -> None:

	_, builder = _make_builder()
	assert builder._resolve_velocity(90) == 90


def test_resolve_velocity_float_coerces_to_int () -> None:

	_, builder = _make_builder()
	assert builder._resolve_velocity(90.7) == 90


def test_resolve_velocity_tuple_draws_from_range () -> None:

	_, builder = _make_builder(seed=42)
	for _ in range(20):
		v = builder._resolve_velocity((60, 90))
		assert 60 <= v <= 90


def test_resolve_velocity_tuple_uses_explicit_rng () -> None:

	_, builder = _make_builder()
	rng_a = random.Random(123)
	rng_b = random.Random(123)
	a = builder._resolve_velocity((40, 100), rng=rng_a)
	b = builder._resolve_velocity((40, 100), rng=rng_b)
	assert a == b  # same seed, same draw


def test_resolve_velocity_wrong_tuple_length_raises () -> None:

	_, builder = _make_builder()
	with pytest.raises(ValueError, match="velocity tuple must be"):
		builder._resolve_velocity((60, 70, 80))


def test_resolve_velocity_string_raises () -> None:

	_, builder = _make_builder()
	with pytest.raises(TypeError, match="velocity must be int or"):
		builder._resolve_velocity("loud")


def test_resolve_velocity_bool_raises () -> None:

	"""bool is a subclass of int; reject it explicitly so True/False don't sneak through."""
	_, builder = _make_builder()
	with pytest.raises(TypeError, match="bool"):
		builder._resolve_velocity(True)


# --- Note-placement methods accept tuple velocity without crashing ---


def test_note_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.note(pitch=60, beat=0.0, velocity=(50, 70))
	notes = next(iter(pattern.steps.values())).notes
	assert 50 <= notes[0].velocity <= 70


def test_hit_steps_accepts_tuple_velocity_per_step () -> None:

	"""Each step should get a fresh random draw."""
	pattern, builder = _make_builder(seed=1)
	builder.hit_steps(pitch=60, steps=list(range(16)), velocity=(40, 90))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	# 16 steps; with a healthy range we expect at least a few distinct values.
	assert len({v for v in velocities}) >= 4
	assert all(40 <= v <= 90 for v in velocities)


def test_hit_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.hit(pitch=60, beats=[0.0, 1.0, 2.0, 3.0], velocity=(60, 100))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(60 <= v <= 100 for v in velocities)


def test_fill_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.fill(pitch=60, spacing=0.5, velocity=(70, 95))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(70 <= v <= 95 for v in velocities)


def test_chord_accepts_tuple_velocity_per_voice () -> None:

	"""Each chord voice should get an independent random velocity."""
	pattern, builder = _make_builder(seed=1)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")
	builder.chord(chord, root=60, velocity=(50, 100), count=5)
	# All chord notes at pulse 0
	notes = pattern.steps[0].notes
	velocities = [n.velocity for n in notes]
	assert all(50 <= v <= 100 for v in velocities)
	# 5 voices; with a 50-unit range we'd expect multiple distinct values.
	assert len(set(velocities)) >= 2


def test_strum_accepts_tuple_velocity_per_voice () -> None:

	pattern, builder = _make_builder(seed=1)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")
	builder.strum(chord, root=60, velocity=(60, 100), offset=0.1, count=4)
	all_notes = [n for step in pattern.steps.values() for n in step.notes]
	velocities = [n.velocity for n in all_notes]
	assert all(60 <= v <= 100 for v in velocities)


def test_sequence_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.sequence(steps=[0, 4, 8, 12], pitches=60, velocities=(55, 85))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(55 <= v <= 85 for v in velocities)


def test_sequence_list_velocity_still_works () -> None:

	"""Regression: list of velocities still works after the tuple branch."""
	pattern, builder = _make_builder()
	builder.sequence(steps=[0, 4, 8, 12], pitches=60, velocities=[60, 70, 80, 90])
	assert [step.notes[0].velocity for step in pattern.steps.values()] == [60, 70, 80, 90]


def test_arpeggio_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1, length=4)
	builder.arpeggio(notes=[60, 64, 67], spacing=0.5, velocity=(70, 100))
	all_notes = [n for step in pattern.steps.values() for n in step.notes]
	velocities = [n.velocity for n in all_notes]
	assert all(70 <= v <= 100 for v in velocities)


def test_arpeggio_chord_form_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1, length=4)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")
	builder.arpeggio(chord, root=60, spacing=0.5, velocity=(70, 100))
	all_notes = [n for step in pattern.steps.values() for n in step.notes]
	velocities = [n.velocity for n in all_notes]
	assert all(70 <= v <= 100 for v in velocities)
	assert len(set(velocities)) > 1


def test_euclidean_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.euclidean(pitch=60, pulses=4, velocity=(50, 80))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(50 <= v <= 80 for v in velocities)


def test_bresenham_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.bresenham(pitch=60, pulses=4, velocity=(40, 70))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(40 <= v <= 70 for v in velocities)


def test_cellular_1d_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.cellular_1d(pitch=60, rule=30, velocity=(45, 75))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(45 <= v <= 75 for v in velocities)


def test_markov_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.markov(
		transitions={"a": [("b", 1)], "b": [("a", 1)]},
		pitch_map={"a": 60, "b": 64},
		velocity=(50, 90),
		spacing=0.5,
	)
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(50 <= v <= 90 for v in velocities)


def test_thue_morse_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.thue_morse(pitch=60, velocity=(40, 80))
	velocities = [step.notes[0].velocity for step in pattern.steps.values()]
	assert all(40 <= v <= 80 for v in velocities)


def test_broken_chord_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1, length=4)
	chord = subsequence.chords.Chord(root_pc=0, quality="major")
	builder.broken_chord(chord, root=60, order=[0, 1, 2, 0], spacing=0.25, velocity=(60, 95))
	all_notes = [n for step in pattern.steps.values() for n in step.notes]
	velocities = [n.velocity for n in all_notes]
	assert all(60 <= v <= 95 for v in velocities)


# --- Bad inputs surface at the builder, not later in the sequencer ---


def test_invalid_velocity_raises_at_builder () -> None:

	"""Issue 1's root cause: a bad velocity must raise at the builder call site
	(where the per-pattern try/except in Composition._rebuild catches it),
	not later in the sequencer dispatch loop where it would crash everything."""

	_, builder = _make_builder()

	with pytest.raises(TypeError):
		builder.hit_steps(pitch=60, steps=[0, 4, 8, 12], velocity="loud")

	with pytest.raises(ValueError, match="velocity tuple must be"):
		builder.hit_steps(pitch=60, steps=[0, 4, 8, 12], velocity=(60, 80, 100))
