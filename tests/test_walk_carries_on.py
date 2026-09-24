"""self_avoiding_walk goes on from bar to bar as one line (#3500).

Every call started on the middle of its list, so however the walk wandered it jumped back to
the same note at each bar line: with the docstring's C major list, every bar of every seed
opened on F.  Simon's call (2026-09-24), matching lorenz's (#3472): each bar picks up where the
last one ended, still keeping clear of what it heard, and a changed list goes on from its note
nearest the one the walk ended on.
"""

import pathlib
import random
import typing

import mido

import subsequence
import subsequence.sequence_utils


SCALE = [60, 62, 64, 65, 67, 69, 71, 72]
BLACK = [61, 63, 66, 68, 70]


def _render (tmp_path: pathlib.Path, bars: int, lists: typing.Callable[[int], typing.List[int]], seed: int = 5) -> typing.List[typing.List[int]]:

	"""Render *bars* bars of one walk, over ``lists(cycle)`` each bar, and read back each bar's pitches in order."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, seed=seed)

	@composition.pattern(channel=1, beats=4)
	def walk (p: typing.Any) -> None:
		p.self_avoiding_walk(lists(p.cycle), spacing=0.25)

	path = tmp_path / f"walk_{len(list(tmp_path.iterdir()))}.mid"
	composition.render(bars=bars, filename=str(path))

	midi = mido.MidiFile(str(path))
	per_bar = 4 * midi.ticks_per_beat
	notes: typing.List[typing.Tuple[int, int]] = []

	for track in midi.tracks:
		tick = 0
		for message in track:
			tick += message.time
			if message.type == "note_on" and message.velocity > 0:
				notes.append((tick, message.note))

	notes.sort()
	played = [[pitch for tick, pitch in notes if tick // per_bar == bar] for bar in range(bars)]

	assert all(len(bar) == 16 for bar in played), [len(bar) for bar in played]

	return played


def test_each_bar_goes_on_from_where_the_last_ended (tmp_path: pathlib.Path) -> None:

	"""The first bar starts on the middle (F); every bar after it opens a step or a skip from the last note before it."""

	bars = _render(tmp_path, 8, lambda cycle: SCALE)

	assert bars[0][0] == 65

	for before, after in zip(bars, bars[1:]):
		assert abs(SCALE.index(after[0]) - SCALE.index(before[-1])) in (1, 2), f"{before[-1]} then {after[0]}"


def test_no_note_comes_back_sooner_than_three_notes_later_across_the_bar_line (tmp_path: pathlib.Path) -> None:

	"""The walk's short memory carries over, so its rule holds over the whole line, not a bar at a time."""

	line = sum(_render(tmp_path, 16, lambda cycle: SCALE), [])

	for i, pitch in enumerate(line):
		assert pitch not in line[i + 1:i + 3], f"{pitch} at note {i} came back at once: {line[max(0, i - 4):i + 4]}"


def test_a_changed_list_goes_on_from_its_note_nearest_the_last (tmp_path: pathlib.Path) -> None:

	"""A list that follows the chord changes under the walk: it goes on from the nearest note, the lower of two as near."""

	lists = lambda cycle: BLACK if cycle % 2 else SCALE
	bars = _render(tmp_path, 8, lists)

	for cycle in range(1, 8):
		pool = lists(cycle)
		ended = bars[cycle - 1][-1]
		nearest = min(range(len(pool)), key = lambda index: (abs(pool[index] - ended), pool[index]))

		assert abs(pool.index(bars[cycle][0]) - nearest) in (1, 2), f"bar {cycle}: ended on {ended}, opened on {bars[cycle][0]}"


def test_the_kernel_keeps_clear_of_what_it_heard () -> None:

	"""Told what was heard before it, a walk from 3 never steps back to 1 or 2, which it heard lately."""

	firsts = {
		subsequence.sequence_utils.self_avoiding_walk(2, 0, 7, random.Random(seed), start=3, heard=[1, 2, 3])[1]
		for seed in range(200)
	}

	assert firsts == {4, 5}


def test_a_seeded_walk_plays_the_same_on_every_run (tmp_path: pathlib.Path) -> None:

	"""A guard: the carried line is as reproducible as the bar it replaced.  This held before as well."""

	first = _render(tmp_path, 6, lambda cycle: SCALE, seed=9)
	again = _render(tmp_path, 6, lambda cycle: SCALE, seed=9)

	assert first == again
