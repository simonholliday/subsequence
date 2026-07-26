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


def _make_builder (channel: int = 0, length: float = 4, drum_note_map: typing.Optional[dict] = None, default_grid: typing.Optional[int] = None, seed: int = 0) -> tuple:

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


def _velocities (pattern: subsequence.pattern.Pattern) -> typing.List[int]:

	"""Every placed velocity, in time order."""

	return [note.velocity for step in sorted(pattern.steps) for note in pattern.steps[step].notes]


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


def test_resolve_velocity_rejects_reversed_range () -> None:

	"""A swapped (high, low) tuple fails at the call site, not deep in randint."""

	_, builder = _make_builder()

	with pytest.raises(ValueError, match="low <= high"):
		builder._resolve_velocity((110, 80))


def test_resolve_velocity_tuple_consumes_exactly_one_draw () -> None:

	"""A (low, high) range advances the RNG by exactly one ``randint`` draw.

	This is the load-bearing reproducibility invariant — if it ever drew twice (or
	differently), every seeded composition downstream would shift bit-for-bit.  A
	range-membership check alone would not catch a two-draw regression.
	"""

	_, builder = _make_builder()

	rng_resolve = random.Random(12345)
	rng_direct = random.Random(12345)

	result = builder._resolve_velocity((40, 80), rng_resolve)
	expected = rng_direct.randint(40, 80)

	assert result == expected                                # same value as a single randint
	assert rng_resolve.getstate() == rng_direct.getstate()   # …and exactly one draw of it


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


def test_repeat_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.repeat(pitch=60, spacing=0.5, velocity=(70, 95))
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
	builder.strum(chord, root=60, velocity=(60, 100), spacing=0.1, count=4)
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


def test_golden_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.golden(60, count=8, velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_de_bruijn_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.de_bruijn([60, 62], window=2, velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_lsystem_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.lsystem(pitch_map={"A": 60, "B": 62}, axiom="A", rules={"A": "AB", "B": "A"}, generations=3, velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_self_avoiding_walk_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.self_avoiding_walk([60, 62, 64, 65, 67], velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_evolve_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.evolve([60, 62, 64], velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_branch_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.branch([60, 62, 64], velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_reaction_diffusion_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.reaction_diffusion(60, velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


def test_lorenz_accepts_tuple_velocity () -> None:

	pattern, builder = _make_builder(seed=1)
	builder.lorenz([60, 62, 64], velocity=(40, 80))
	assert all(40 <= v <= 80 for v in _velocities(pattern))


# --- A (low, high) draw is reproducible under seed=, whatever the pattern's own RNG ---


# Every generator that RANDOMISES velocity from a (low, high) range.  lorenz and
# reaction_diffusion are deliberately absent: they map the range across their own
# field rather than drawing from it, so they are covered separately below.
_SEEDED_VELOCITY_VERBS = [
	("euclidean",         lambda b: b.euclidean(36, pulses=5, velocity=(60, 100), seed=7)),
	("bresenham",         lambda b: b.bresenham(36, pulses=5, velocity=(60, 100), seed=7)),
	("cellular_1d",       lambda b: b.cellular_1d(36, velocity=(60, 100), seed=7)),
	# cellular_2d is deliberately absent — its seed= names the initial grid, not the
	# velocity stream (it takes rng= for that).  Covered separately below.
	("thue_morse",        lambda b: b.thue_morse(36, velocity=(60, 100), seed=7)),
	("golden",            lambda b: b.golden(60, count=8, velocity=(60, 100), seed=7)),
	("de_bruijn",         lambda b: b.de_bruijn([60, 62], window=2, velocity=(60, 100), seed=7)),
	("self_avoiding_walk", lambda b: b.self_avoiding_walk([60, 62, 64, 65, 67], velocity=(60, 100), seed=7)),
	("evolve",            lambda b: b.evolve([60, 62, 64], velocity=(60, 100), seed=7)),
	("branch",            lambda b: b.branch([60, 62, 64], velocity=(60, 100), seed=7)),
]


@pytest.mark.parametrize("name,place", _SEEDED_VELOCITY_VERBS, ids=[n for n, _ in _SEEDED_VELOCITY_VERBS])
def test_velocity_tuple_is_reproducible_under_seed (name: str, place: typing.Callable) -> None:

	"""``seed=`` fixes the velocity draws for the call, whatever ``self.rng`` holds.

	This is what every generator's ``seed:`` docstring promises.  It was false for
	the verbs routed through ``_place_gated_sequence``, which handed the raw tuple
	to ``note()`` and so drew from the pattern's RNG instead of the caller's.
	"""

	pattern_a, builder_a = _make_builder(seed=111)
	place(builder_a)

	pattern_b, builder_b = _make_builder(seed=999)
	place(builder_b)

	assert _velocities(pattern_a) == _velocities(pattern_b)


def test_cellular_2d_velocity_follows_rng_not_seed () -> None:

	"""cellular_2d is the exception: ``seed=`` picks the grid, ``rng=`` the velocities.

	Its ``seed:`` is documented as the RNG seed for the ``"random"`` initial grid —
	it never governs the velocity draw — so the reproducibility contract above is
	expressed through ``rng=`` here instead.
	"""

	pattern_a, builder_a = _make_builder(seed=111)
	builder_a.cellular_2d([36, 38, 42], velocity=(60, 100), rng=random.Random(7))

	pattern_b, builder_b = _make_builder(seed=999)
	builder_b.cellular_2d([36, 38, 42], velocity=(60, 100), rng=random.Random(7))

	assert _velocities(pattern_a) == _velocities(pattern_b)


def test_field_mapped_velocity_is_deterministic () -> None:

	"""lorenz and reaction_diffusion map the range across their field, never draw from it.

	A ``(low, high)`` here is a scale, not a randomisation — so the same call gives
	the same velocities with no seed involved at all.
	"""

	pattern_a, builder_a = _make_builder(seed=111)
	builder_a.lorenz([60, 62, 64], velocity=(60, 100))

	pattern_b, builder_b = _make_builder(seed=999)
	builder_b.lorenz([60, 62, 64], velocity=(60, 100))

	assert _velocities(pattern_a) == _velocities(pattern_b)

	pattern_c, builder_c = _make_builder(seed=111)
	builder_c.reaction_diffusion(60, velocity=(60, 100))

	pattern_d, builder_d = _make_builder(seed=999)
	builder_d.reaction_diffusion(60, velocity=(60, 100))

	assert _velocities(pattern_c) == _velocities(pattern_d)


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
