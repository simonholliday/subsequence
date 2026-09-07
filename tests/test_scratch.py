"""Tests for `p.scratch()` — an empty builder sharing this pattern's context.

Two properties carry the whole design.  A scratch must see everything a
generator reads, or a node behaves differently inside a patch than on a
pattern.  And it must **not** draw from the parent's random stream: doing so
would advance it, so the parent's later draws would depend on how many
scratches were made — invisible, and it would quietly break `lock()`'s promise
that a locked pattern realises identically each cycle.
"""

import random
import typing

import subsequence.pattern
import subsequence.pattern_builder


def _builder (
	stream_seed: typing.Optional[int] = 12345,
	rng: typing.Optional[random.Random] = None,
	**context: typing.Any,
) -> subsequence.pattern_builder.PatternBuilder:

	"""A PatternBuilder over a bare 4-beat pattern (no MIDI required)."""

	pattern = subsequence.pattern.Pattern(channel=3, length=4, device=2)

	return subsequence.pattern_builder.PatternBuilder(
		pattern, cycle=0, rng=rng or random.Random(7), stream_seed=stream_seed, **context,
	)


# ---------------------------------------------------------------------------
# The stream — the part that would be silently wrong if guessed
# ---------------------------------------------------------------------------

def test_making_scratches_does_not_change_the_parents_draws () -> None:

	"""The property the whole design exists for.

	If a scratch drew from the parent's stream, this pattern's notes would move
	according to how many nodes a patch happened to contain — and `lock()`
	promises identical realisation every cycle, which would then hold only for
	a fixed number of them.
	"""

	def parent_after (scratches: int) -> typing.List[int]:

		builder = _builder()

		for index in range(scratches):
			builder.scratch(f"node_{index}").ghost_fill(42, density=0.6)

		builder.ghost_fill(60, density=0.5)

		return sorted(note.position for note in builder.placed())

	assert parent_after(0) == parent_after(3) == parent_after(10)


def test_the_same_name_draws_the_same_numbers () -> None:

	"""Reproducible: set a seed once at the top and a scratch under it repeats."""

	first = _builder().scratch("hats").ghost_fill(42, density=0.5)
	again = _builder().scratch("hats").ghost_fill(42, density=0.5)

	assert [n.position for n in first.placed()] == [n.position for n in again.placed()]


def test_different_names_draw_differently () -> None:

	"""Two nodes in one patch are two streams, not one shared by accident."""

	builder = _builder()

	hats = builder.scratch("hats").ghost_fill(42, density=0.5)
	perc = builder.scratch("perc").ghost_fill(42, density=0.5)

	assert [n.position for n in hats.placed()] != [n.position for n in perc.placed()]


def test_a_different_composition_seed_gives_a_different_scratch () -> None:

	"""The child hangs off the composition seed, so re-seeding reaches it."""

	one = _builder(stream_seed=12345).scratch("hats").ghost_fill(42, density=0.5)
	two = _builder(stream_seed=999).scratch("hats").ghost_fill(42, density=0.5)

	assert [n.position for n in one.placed()] != [n.position for n in two.placed()]


def test_an_unseeded_composition_gives_an_unseeded_scratch () -> None:

	"""No seed means no reproducibility, here as everywhere else — not a crash."""

	scratch = _builder(stream_seed=None).scratch("hats")

	assert isinstance(scratch.rng, random.Random)
	assert scratch._stream_seed is None


# ---------------------------------------------------------------------------
# The context — everything a generator reads
# ---------------------------------------------------------------------------

def test_a_scratch_carries_the_musical_context () -> None:

	"""A generator must behave the same on a scratch as on the pattern itself."""

	builder = _builder(
		key = "F",
		scale = "dorian",
		bar = 5,
		energy = 0.75,
		time_signature = (7, 8),
		drum_note_map = {"kick": 36},
		data = {"shared": 1},
	)

	scratch = builder.scratch()

	assert scratch.key == "F"
	assert scratch.scale == "dorian"
	assert scratch.bar == 5
	assert scratch.energy == 0.75
	assert scratch.time_signature == (7, 8)
	assert scratch.cycle == builder.cycle
	assert scratch._drum_note_map == {"kick": 36}
	assert scratch.data is builder.data		# the same dict, not a copy


def test_a_scratch_sits_at_the_same_place_in_the_bar () -> None:

	"""Harmony is anchored on the absolute beat axis.

	A scratch starting elsewhere would resolve a degree against a different
	chord than the pattern it is standing in for.
	"""

	builder = _builder()
	builder._pattern._cycle_start_pulse = 384

	assert builder.scratch()._pattern._cycle_start_pulse == 384


def test_a_scratch_matches_the_pattern_it_came_from () -> None:

	"""Same length, channel and device — and empty."""

	builder = _builder()
	scratch = builder.scratch()

	assert scratch._pattern.length == builder._pattern.length
	assert scratch._pattern.channel == builder._pattern.channel
	assert scratch._pattern.device == builder._pattern.device
	assert scratch.placed() == []


def test_what_a_scratch_places_does_not_sound () -> None:

	"""It has its own pattern, so the parent is untouched."""

	builder = _builder()
	builder.hit(36, [0.0, 2.0])

	builder.scratch("hats").euclidean(42, 7)

	assert len(builder.placed()) == 2


def test_a_scratch_can_be_read_back_and_placed () -> None:

	"""The round trip the method exists for: generate, capture, place."""

	builder = _builder()

	layer = builder.scratch("hats").euclidean(42, 5)
	builder.motif(layer.capture(0.0, 4.0))

	assert len(builder.placed()) == 5


def test_a_scratch_of_a_scratch_keeps_deriving () -> None:

	"""Nesting works, and a nested stream is still its own."""

	builder = _builder()
	inner = builder.scratch("outer").scratch("inner")

	assert inner._stream_seed is not None
	assert inner._stream_seed != builder._stream_seed
