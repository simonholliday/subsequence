"""API-consistency overhaul: the ``seed=``/``rng=`` idiom, the behaviour-preserving
(R1) draw-count invariant for the ``dropout``→``probability`` rename, and the
cellular_2d ``initial_state=``/``seed=`` split.

The renames are hard breaks — there are no deprecation aliases — so the old keywords
(``dropout=``, ``offset=``, ``amount=``, ``unit=``, ``steps=`` on evolve/fibonacci, and a
grid/int ``seed=`` on cellular_2d) are plain ``TypeError``s now.  ``probability`` means the
chance a note PLAYS, and the inverted generators must consume zero RNG draws at their
default (1.0) so existing seeded compositions reproduce bit-for-bit.
"""

import random
import typing

import pytest

import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.constants.velocity
import subsequence.pattern
import subsequence.pattern_builder


def _make_builder (
	length: float = 4,
	cycle: int = 0,
) -> typing.Tuple[subsequence.pattern.Pattern, subsequence.pattern_builder.PatternBuilder]:

	"""Create a Pattern and PatternBuilder pair for testing (no MIDI required)."""

	default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
	pattern = subsequence.pattern.Pattern(channel=0, length=length)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern,
		cycle=cycle,
		default_grid=default_grid,
		data={},
	)
	return pattern, builder


def _placements (pattern: subsequence.pattern.Pattern) -> typing.List[typing.Tuple[int, int, int]]:

	"""Flatten placed notes into a comparable, order-stable list of ``(pulse, pitch, velocity)``."""

	out: typing.List[typing.Tuple[int, int, int]] = []
	for pulse in sorted(pattern.steps.keys()):
		for note in pattern.steps[pulse].notes:
			out.append((pulse, note.pitch, note.velocity))
	return out


# ── R1: the inverted generators draw ZERO times at the default probability=1.0 ──
#
# The dropout→probability guard is ``if probability < 1.0 and rng.random() < …``.
# At the default (1.0) the short-circuit means NO rng draw happens, so existing
# seeded compositions reproduce bit-for-bit.  A fixed int velocity rules out any
# velocity-tuple draw, isolating the placement guard.

@pytest.mark.parametrize("place", [
	lambda b, rng: b.euclidean(36, pulses=5, velocity=100, rng=rng),
	lambda b, rng: b.cellular_1d(36, velocity=100, rng=rng),
	lambda b, rng: b.thue_morse(36, velocity=100, rng=rng),
	lambda b, rng: b.reaction_diffusion(36, velocity=100, rng=rng),
	lambda b, rng: b.cellular_2d([36, 38, 42], velocity=100, generation=0, rng=rng),
])
def test_inverted_generator_draws_nothing_at_default_probability (place: typing.Callable) -> None:

	_, builder = _make_builder()
	rng = random.Random(0)
	state_before = rng.getstate()
	place(builder, rng)
	assert rng.getstate() == state_before


def test_euclidean_draws_when_probability_below_one () -> None:

	_, builder = _make_builder()
	rng = random.Random(0)
	state_before = rng.getstate()
	builder.euclidean(36, pulses=8, velocity=100, probability=0.5, rng=rng)
	assert rng.getstate() != state_before


# ── The renames are hard breaks: the old keywords are gone, not aliased. ──

def test_removed_alias_keywords_now_raise () -> None:

	chord = subsequence.chords.Chord(root_pc=0, quality="major")
	_, builder = _make_builder()

	with pytest.raises(TypeError):
		builder.euclidean(36, pulses=5, dropout=0.3)        # dropout= → probability=

	with pytest.raises(TypeError):
		builder.strum(chord, root=60, offset=0.1)           # offset= → spacing=

	with pytest.raises(TypeError):
		builder.swing(amount=60)                            # amount= → percent=

	with pytest.raises(TypeError):
		builder.fibonacci(36, steps=5)                      # steps= → count=

	with pytest.raises(TypeError):
		builder.evolve([60, 64], steps=4)                   # steps= → length=


# ── The shared _rng_from resolver: precedence rng > seed > self.rng, and a warning
#    when both seed= and rng= are supplied. ──

def test_rng_from_precedence_and_double_warning () -> None:

	_, builder = _make_builder()

	explicit = random.Random(123)

	# rng= wins over seed=, and warns about the redundancy.
	with pytest.warns(UserWarning, match="both"):
		assert builder._rng_from(5, explicit) is explicit

	# seed= alone → a fresh Random(seed), independent of the pattern's own RNG.
	resolved = builder._rng_from(5, None)
	assert resolved is not builder.rng
	assert resolved.random() == random.Random(5).random()

	# Neither → the pattern's own RNG.
	assert builder._rng_from(None, None) is builder.rng


# ── cellular_2d: the seed/grid split — initial_state= ("center"/"random"/grid) plus an
#    integer seed= for a reproducible random fill. ──

def test_cellular_2d_center_is_the_default () -> None:

	p_default, b_default = _make_builder()
	p_explicit, b_explicit = _make_builder()

	b_default.cellular_2d([36, 38, 42], velocity=100, generation=0)
	b_explicit.cellular_2d([36, 38, 42], velocity=100, generation=0, initial_state="center")

	assert _placements(p_default) == _placements(p_explicit)


def test_cellular_2d_random_is_reproducible_with_seed () -> None:

	p1, b1 = _make_builder()
	p2, b2 = _make_builder()

	b1.cellular_2d([36, 38, 42], velocity=100, generation=3, initial_state="random", seed=7)
	b2.cellular_2d([36, 38, 42], velocity=100, generation=3, initial_state="random", seed=7)

	assert _placements(p1) == _placements(p2)
	assert _placements(p1)  # a random fill placed at least one note


def test_cellular_2d_grid_via_initial_state () -> None:

	# Row 0 (pitch 36) all live, the other rows empty; generation=0 keeps it as-is.
	grid = [[1] * 16, [0] * 16, [0] * 16]
	pattern, builder = _make_builder()

	builder.cellular_2d([36, 38, 42], velocity=100, generation=0, initial_state=grid)

	pitches = {pitch for _, pitch, _ in _placements(pattern)}
	assert pitches == {36}


# ── P2: the one approved sound change — broken_chord is a chord voice, so its
#    default velocity is the softer chord bucket (90), matching chord()/strum(). ──

def test_broken_chord_defaults_to_chord_velocity () -> None:

	chord = subsequence.chords.Chord(root_pc=0, quality="major")
	pattern, builder = _make_builder()

	builder.broken_chord(chord, root=60, order=[0, 1, 2])

	velocities = {velocity for _, _, velocity in _placements(pattern)}
	assert velocities == {subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY}
	assert subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY == 90
