"""A list shorter than the steps it is laid over starts again from its beginning, everywhere (#3537).

Simon's calls (2026-09-24, from #3521).  sequence() held a short ``pitches=``,
``velocities=`` or ``durations=`` list's last value and warned, and the
sequence_utils helpers that combine per-step lists held theirs too, while
ghost_fill(), cellular_2d() and the Direct Pattern API's add_sequence() started
one again.  Now every one of them starts it again, so three pitches over eight
steps make a figure that drifts against the rhythm, and a one-beat gate gates
every beat.  A motif is a fixed figure, and still refuses a list that does not
match its notes.

Each case checks the short list against the same list written out in full, and
first that the written-out list is not what holding the last value gives, so a
case cannot pass by reading both the same way.  ghost_fill, cellular_2d and
add_sequence already started a list again: those three cases and the motif's
refusal are guards, and held before as well.
"""

import typing

import pytest

import subsequence
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequence_utils


def _builder () -> subsequence.pattern_builder.PatternBuilder:

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	return subsequence.pattern_builder.PatternBuilder(pattern=pattern, cycle=0, default_grid=16)


def _placed (p: subsequence.pattern_builder.PatternBuilder, field: str) -> typing.List[typing.Any]:

	"""Each placed note's *field*, in the order they play; something must have played."""

	p._finish_build()

	values = [getattr(note, field) for pulse in sorted(p._pattern.steps) for note in p._pattern.steps[pulse].notes]

	assert values, "nothing was placed"

	return values


def _rows (velocities: typing.List[int]) -> typing.List[typing.Tuple[int, int]]:

	"""Each cellular_2d row's pitch and velocity; all three rows must have played."""

	p = _builder()
	p.cellular_2d([60, 62, 64], velocities=velocities, seed=2)
	p._finish_build()

	rows = sorted({(note.pitch, note.velocity) for step in p._pattern.steps.values() for note in step.notes})

	assert [pitch for pitch, _ in rows] == [60, 62, 64], rows

	return rows


def _added (velocity: typing.List[int]) -> typing.List[int]:

	"""The velocities the Direct Pattern API's add_sequence() gives four hits."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	pattern.add_sequence([1, 1, 1, 1], spacing_pulses=24, pitch=60, velocity=velocity)

	return [note.velocity for pulse in sorted(pattern.steps) for note in pattern.steps[pulse].notes]


EVERY_OTHER_STEP = [0, 2, 4, 6, 8, 10, 12, 14]
FOUR = [0, 4, 8, 12]
SU = subsequence.sequence_utils

# Each: what it plays or returns given the list, the short list, and how many steps it is laid over.
CASES: typing.Dict[str, typing.Tuple[typing.Callable[[typing.List[typing.Any]], typing.Any], typing.List[typing.Any], int]] = {
	"sequence pitches": (lambda values: _placed(_builder().sequence(steps=EVERY_OTHER_STEP, pitches=values), "pitch"), [60, 63, 67], 8),
	"sequence velocities": (lambda values: _placed(_builder().sequence(steps=FOUR, pitches=60, velocities=values), "velocity"), [100, 60], 4),
	"sequence durations": (lambda values: _placed(_builder().sequence(steps=FOUR, pitches=60, durations=values), "duration"), [0.25, 0.5], 4),
	"ghost_fill": (lambda values: _placed(_builder().ghost_fill(60, density=1.0, velocities=values, seed=1), "velocity"), [40, 60, 80], 16),
	"cellular_2d": (_rows, [40, 60], 3),
	"add_sequence": (_added, [100, 60], 4),
	"mask": (lambda values: SU.mask(list(range(1, 9)), against=values), [1, 0], 8),
	"choke": (lambda values: SU.choke(list(range(1, 9)), against=values), [1, 0], 8),
	"combine_densities": (lambda values: SU.combine_densities([[0.5] * 8, values], "min"), [1.0, 0.0], 8),
	"density_warp": (lambda values: SU.density_warp([0.5] * 8, values), [0.9, 0.1], 8),
	"density_spread": (lambda values: SU.density_spread([0.7] * 8, values), [1.0, 0.5], 8),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_short_list_starts_again_from_its_beginning (name: str) -> None:

	play, short, steps = CASES[name]

	written_out = [short[i % len(short)] for i in range(steps)]
	held = short + [short[-1]] * (steps - len(short))

	assert play(written_out) != play(held), "the fixture cannot tell starting again from holding the last value"
	assert play(short) == play(written_out)


def test_a_motif_still_refuses_a_list_that_does_not_match_its_notes () -> None:

	"""A guard: a motif is a fixed figure, one value per note.  This held before as well."""

	with pytest.raises(ValueError, match=r"velocities has 2 values for 4 events"):
		subsequence.Motif.notes([60, 62, 64, 65], velocities=[40, 60])
