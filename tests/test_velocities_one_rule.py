"""velocities= means one thing on every verb that takes it (#3525).

Simon's call (2026-09-24, from #3521): velocities= is one value per step, row or note, and
everywhere it is offered it also takes what velocity= takes, one value or a (low, high) range drawn
per note.  sequence() and the motif functions already did.  ghost_fill() and cellular_2d() raised
TypeError on one value, and read (40, 60) as one value per step or row, alternating, so the same
argument meant three different things across four verbs.  A tuple, because a two-element list is
one value per step here, where on velocity= it is the range a control surface sends.
"""

import typing

import pytest

import subsequence
import subsequence.pattern
import subsequence.pattern_builder


def _builder () -> subsequence.pattern_builder.PatternBuilder:

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	return subsequence.pattern_builder.PatternBuilder(pattern=pattern, cycle=0, default_grid=16)


def _motif (p: subsequence.pattern_builder.PatternBuilder, velocities: typing.Any) -> None:

	# A motif's list is one per note, and must match its notes.
	given = velocities * 4 if isinstance(velocities, list) else velocities
	p.motif(subsequence.Motif.notes(list(range(60, 68)), beats=[i / 2 for i in range(8)], velocities=given), beat=0)


VERBS: typing.Dict[str, typing.Callable[[subsequence.pattern_builder.PatternBuilder, typing.Any], typing.Any]] = {
	"cellular_2d": lambda p, v: p.cellular_2d([60, 62, 64], velocities=v, seed=2),
	"ghost_fill": lambda p, v: p.ghost_fill(60, density=1.0, velocities=v, seed=1),
	"motif": _motif,
	"sequence": lambda p, v: p.sequence(steps=list(range(16)), pitches=60, velocities=v, seed=1),
}


def _velocities (verb: str, velocities: typing.Any) -> typing.Set[int]:

	"""The velocities *verb* plays, given *velocities*; it must play something."""

	p = _builder()
	VERBS[verb](p, velocities)
	p._finish_build()

	played = {note.velocity for step in p._pattern.steps.values() for note in step.notes}

	assert played, f"{verb} placed nothing"

	return played


@pytest.mark.parametrize("verb", sorted(VERBS))
def test_one_value_is_every_note (verb: str) -> None:

	assert _velocities(verb, 50) == {50}


@pytest.mark.parametrize("verb", sorted(VERBS))
def test_a_tuple_is_a_range_drawn_per_note (verb: str) -> None:

	"""More than the two ends, so it is a draw and not the pair taken in turn."""

	drawn = _velocities(verb, (40, 60))

	assert drawn <= set(range(40, 61)) and len(drawn) > 2, sorted(drawn)


@pytest.mark.parametrize("verb", sorted(VERBS))
def test_a_list_is_one_value_per_step (verb: str) -> None:

	"""A guard: a list plays only its own values, one per step, row or note.  This held before as well."""

	assert _velocities(verb, [40, 60]) == {40, 60}


def test_ghost_fill_still_takes_a_function_of_the_step () -> None:

	"""A guard: the function form, for a curve such as Perlin noise, is untouched.  This held before as well.

	Every step's own value, and well clear of the ghost default of 35, which a range below 36 let pass.
	"""

	p = _builder()
	p.ghost_fill(60, density=1.0, velocities=lambda i: 90 + i, seed=1)
	p._finish_build()

	assert {note.velocity for step in p._pattern.steps.values() for note in step.notes} == set(range(90, 106))


def test_a_tuple_that_is_not_a_pair_is_refused_naming_both_forms () -> None:

	with pytest.raises(ValueError, match=r"velocities= takes a list, one value per step or row, or what velocity= takes"):
		_builder().ghost_fill(60, density=1.0, velocities=(40, 50, 60), seed=1)
