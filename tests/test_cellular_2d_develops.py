"""A random cellular_2d grid is drawn once, evolves by its rule, and is redrawn when it dies (#3072, #3498).

Three things were wrong.  The default start was one cell at the centre, which dies at once
under every rule the docstring names, so ``p.cellular_2d(pitches)`` played one note and then
silence.  An unseeded random start was drawn afresh on every rebuild, so each bar was an
unrelated random fill and the automaton never ran.  And a grid left to evolve mostly dies or
loops within tens of bars: drawn once, 52 of 100 random 4x16 grids died out under the default
rule, and every one of them died or looped.

Simon's calls: the default is a random grid, drawn once per pattern and evolved a generation per
bar; when it dies out or stops changing, a fresh grid is drawn and the part carries on.  A loop
of two bars counts as stopping: it swaps between the same two bars for ever.
"""

import pathlib
import random
import typing

import mido
import pytest

import subsequence
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequence_utils


Grid = typing.List[typing.List[int]]

FOUR = [60, 62, 64, 65]
EIGHT = [60, 62, 64, 65, 67, 69, 71, 72]
STEPS = 16


def _rule (rule: str) -> typing.Tuple[typing.Set[int], typing.Set[int]]:

	birth, survival = rule.split("/")

	return {int(n) for n in birth[1:]}, {int(n) for n in survival[1:]}


def _successor (grid: Grid, rule: str) -> Grid:

	"""The next generation, worked out here rather than by the code under test (a toroidal Moore neighbourhood)."""

	birth, survival = _rule(rule)
	rows, cols = len(grid), len(grid[0])

	def neighbours (r: int, c: int) -> int:
		return sum(grid[(r + dr) % rows][(c + dc) % cols] for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc)

	return [
		[1 if (neighbours(r, c) in (survival if grid[r][c] else birth)) else 0 for c in range(cols)]
		for r in range(rows)
	]


def _dead (grid: Grid) -> bool:

	return not any(any(row) for row in grid)


def _render (tmp_path: pathlib.Path, bars: int, pitches: typing.List[int], composition_seed: typing.Optional[int] = None, **kwargs: typing.Any) -> typing.List[Grid]:

	"""Render *bars* bars of one cellular_2d part and read back the grid each bar played.

	*kwargs* go to cellular_2d(), ``seed=`` among them; the composition's own seed is *composition_seed*.
	"""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, seed=composition_seed)

	@composition.pattern(channel=1, beats=4)
	def cells (p: typing.Any) -> None:
		p.cellular_2d(pitches, **kwargs)

	path = tmp_path / f"cells_{len(list(tmp_path.iterdir()))}.mid"
	composition.render(bars=bars, filename=str(path))

	midi = mido.MidiFile(str(path))
	per_step = midi.ticks_per_beat // 4
	grids = [[[0] * STEPS for _ in pitches] for _ in range(bars)]

	for track in midi.tracks:
		tick = 0
		for message in track:
			tick += message.time
			if message.type == "note_on" and message.velocity > 0:
				assert tick % per_step == 0, f"a cell played off the grid, at tick {tick}"
				bar, step = divmod(tick // per_step, STEPS)
				grids[bar][pitches.index(message.note)][step] = 1

	return grids


def _plain (rows: int, rule: str, seed: int, generations: int) -> typing.List[Grid]:

	"""The automaton from *seed* left alone, as the kernel runs it: nothing is redrawn."""

	return [
		subsequence.sequence_utils.generate_cellular_automaton_2d(rows=rows, cols=STEPS, rule=rule, generation=g, seed=seed, density=0.5)
		for g in range(generations)
	]


def _first_seed (rows: int, rule: str, fate: typing.Callable[[typing.List[Grid], int], bool], within: int) -> typing.Tuple[int, int]:

	"""The first seed whose plain run meets *fate* at some generation before *within*, and that generation."""

	for seed in range(2, 500):
		run = _plain(rows, rule, seed, within)
		for g in range(2, within):
			if fate(run, g):
				return seed, g

	raise AssertionError("no seed found - the fixture's premise has gone")


def test_the_default_start_plays_every_bar (tmp_path: pathlib.Path) -> None:

	"""#3498: with no initial_state it played one note in the first bar and nothing after."""

	grids = _render(tmp_path, 8, FOUR)

	assert [sum(map(sum, grid)) > 0 for grid in grids] == [True] * 8


def test_an_unseeded_random_grid_evolves_by_its_rule (tmp_path: pathlib.Path) -> None:

	"""#3072: each bar is the rule's successor of the bar before, unless that successor was dead or a loop.

	It used to draw a fresh random fill every bar, so almost no bar followed from the one before.
	"""

	rule = "B368/S245"
	grids = _render(tmp_path, 16, FOUR, initial_state="random")
	lawful = 0

	for n in range(1, len(grids)):
		expected = _successor(grids[n - 1], rule)
		stopped = _dead(expected) or expected == grids[n - 1] or (n >= 2 and expected == grids[n - 2])

		if stopped:
			assert grids[n] != expected, f"bar {n} kept a grid that had died or looped"
		else:
			assert grids[n] == expected, f"bar {n} is not the successor of bar {n - 1}"
			lawful += 1

	assert lawful >= 8, f"only {lawful} of 15 bars followed from the one before - too few to show anything"


def test_a_grid_that_dies_is_redrawn_and_the_part_plays_on (tmp_path: pathlib.Path) -> None:

	rule = "B3/S23"
	seed, died = _first_seed(4, rule, lambda run, g: _dead(run[g]), 12)

	assert _dead(_plain(4, rule, seed, died + 1)[died])

	grids = _render(tmp_path, died + 8, FOUR, rule=rule, initial_state="random", seed=seed)

	assert grids[:died] == _plain(4, rule, seed, died), "the part did not play that start - the premise has gone"
	assert [bar for bar, grid in enumerate(grids) if _dead(grid)] == []


def test_a_grid_that_stops_changing_is_redrawn (tmp_path: pathlib.Path) -> None:

	rule = "B3/S23"
	seed, frozen = _first_seed(8, rule, lambda run, g: not _dead(run[g]) and run[g] == run[g - 1], 40)

	grids = _render(tmp_path, frozen + 8, EIGHT, rule=rule, initial_state="random", seed=seed)

	assert grids[:frozen] == _plain(8, rule, seed, frozen), "the part did not play that start - the premise has gone"

	assert [bar for bar in range(1, len(grids)) if grids[bar] == grids[bar - 1]] == []


def test_a_grid_that_swaps_between_two_bars_is_redrawn (tmp_path: pathlib.Path) -> None:

	rule = "B3/S23"

	def swapping (run: typing.List[Grid], g: int) -> bool:
		return not _dead(run[g]) and run[g] == run[g - 2] and run[g] != run[g - 1]

	seed, swapped = _first_seed(8, rule, swapping, 40)

	grids = _render(tmp_path, swapped + 8, EIGHT, rule=rule, initial_state="random", seed=seed)

	assert grids[:swapped] == _plain(8, rule, seed, swapped), "the part did not play that start - the premise has gone"

	assert [bar for bar in range(2, len(grids)) if grids[bar] == grids[bar - 2]] == []


def test_the_fresh_grids_are_the_same_on_every_run (tmp_path: pathlib.Path) -> None:

	"""A seeded start redraws in a fixed order, so the piece plays the same twice, redraws included."""

	rule = "B3/S23"
	seed, died = _first_seed(4, rule, lambda run, g: _dead(run[g]), 12)

	first = _render(tmp_path, died + 8, FOUR, rule=rule, initial_state="random", seed=seed)
	again = _render(tmp_path, died + 8, FOUR, rule=rule, initial_state="random", seed=seed)

	assert first == again
	assert first[died] != _plain(4, rule, seed, died + 1)[died], "no redraw happened, so this proves nothing"


def test_a_seeded_composition_draws_the_same_grid_on_every_run (tmp_path: pathlib.Path) -> None:

	first = _render(tmp_path, 6, FOUR, composition_seed=11)
	again = _render(tmp_path, 6, FOUR, composition_seed=11)
	other = _render(tmp_path, 6, FOUR, composition_seed=12)

	assert first == again
	assert first != other


def _drawn (pattern: subsequence.pattern.Pattern, rng: random.Random) -> typing.List[typing.Tuple[int, int]]:

	"""What one build of a random start at generation 0 places, on a pattern built by hand."""

	pattern.steps = {}
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pattern, cycle=0, default_grid=STEPS, data={}, rng=rng)
	builder.cellular_2d(FOUR, generation=0, initial_state="random")

	return sorted((pulse, note.pitch) for pulse, step in pattern.steps.items() for note in step.notes)


def test_the_same_stream_keeps_its_grid_and_a_new_one_draws_again () -> None:

	"""A pattern keeps the seed it drew; reroll() deals a new stream, which draws a new grid.

	lock() re-deals the same stream every bar, so a fresh stream from the same seed draws the same grid.
	"""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	pattern._rng = random.Random(1)		# type: ignore[attr-defined]

	first = _drawn(pattern, pattern._rng)		# type: ignore[attr-defined]
	kept = _drawn(pattern, pattern._rng)		# type: ignore[attr-defined]

	pattern._rng = random.Random(2)		# type: ignore[attr-defined]
	rerolled = _drawn(pattern, pattern._rng)		# type: ignore[attr-defined]

	pattern._rng = random.Random(1)		# type: ignore[attr-defined]
	relocked = _drawn(pattern, pattern._rng)		# type: ignore[attr-defined]

	assert first
	assert kept == first
	assert rerolled != first
	assert relocked == first


def test_an_unseeded_random_grid_costs_one_step_a_bar (tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Counted, not timed: a fresh seed every bar replayed the whole history, 0 + 1 + ... + 31 steps."""

	stepped = 0
	step = subsequence.sequence_utils._ca_2d_step

	def counted (*args: typing.Any) -> Grid:
		nonlocal stepped
		stepped += 1
		return step(*args)

	monkeypatch.setattr(subsequence.sequence_utils, "_ca_2d_step", counted)

	_render(tmp_path, 32, FOUR, initial_state="random")

	assert 31 <= stepped <= 40


def test_the_catalogue_opens_the_start_at_random () -> None:

	"""Superconductor opens the control at the published default, and could never choose a rule that grows one cell."""

	entry = subsequence.describe_generator("cellular_2d")
	start = next(parameter for parameter in entry["parameters"] if parameter["name"] == "initial_state")

	assert start["default"] == "random"
	assert "rule" in entry["dropped"]


def test_center_still_lights_one_cell (tmp_path: pathlib.Path) -> None:

	"""A guard: "center" is kept as it was, one cell that the default rule lets die.  This passed before as well."""

	grids = _render(tmp_path, 3, FOUR, initial_state="center")

	assert [sum(map(sum, grid)) for grid in grids] == [1, 0, 0]
