"""A glide that wraps into the next cycle resets on that cycle's first note, wherever a groove puts it (#2927).

A glide from a pattern's last note into its first resets the pitch wheel at the next cycle's
first onset, and ``slide(extend=True)`` lengthens the last note to meet it.  Both took that onset
to be where this cycle's first note was, one cycle on.  A pattern that is not a whole number of
its groove's cycles long starts each time round from a different place in the groove, so under
swing its first note is straight one time and late the next: every reset landed a pulse early or
a pulse late (at 57% swing; three at 75%), bending the start of the note or letting the last one
drop back first, and an extended note left a gap before the first or ran over it.

Read here from a rendered file, which is what a musician hears.
"""

import pathlib
import typing

import mido
import pytest

import subsequence


LOW, HIGH = 48, 55


class _Played (typing.NamedTuple):

	cycle: int								# ticks per cycle
	onsets: typing.List[typing.Tuple[int, int]]	# (tick, note)
	resets: typing.List[int]				# ticks where the pitch wheel returns to 0 from a bend
	ends: typing.List[typing.Tuple[int, int]]	# (tick, note)


def _play (tmp_path: pathlib.Path, beats: float, build: typing.Callable[[subsequence.PatternBuilder], None]) -> _Played:

	"""Render one pattern for at least twelve beats and read back what was played."""

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)

	@composition.pattern(channel = 1, beats = beats, reschedule_lookahead = 0.25)
	def line (p: subsequence.PatternBuilder) -> None:
		build(p)

	path = tmp_path / "line.mid"
	composition.render(bars = max(4, int(beats * 3)), filename = str(path))
	midi = mido.MidiFile(str(path))

	onsets: typing.List[typing.Tuple[int, int]] = []
	resets: typing.List[int] = []
	ends: typing.List[typing.Tuple[int, int]] = []

	for track in midi.tracks:

		now = 0
		wheel = 0

		for message in track:

			now += message.time

			if message.type == "note_on" and message.velocity > 0:
				onsets.append((now, message.note))
			elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
				ends.append((now, message.note))
			elif message.type == "pitchwheel":
				# A ramp opens at 0 too; a reset is a return to 0 from a bend.
				if message.pitch == 0 and wheel != 0:
					resets.append(now)
				wheel = message.pitch

	last = max(tick for tick, _ in onsets)

	return _Played(
		cycle = int(round(beats * midi.ticks_per_beat)),
		onsets = sorted(onsets),
		resets = [tick for tick in resets if tick <= last],
		ends = sorted(ends),
	)


def _first_offsets (played: _Played) -> typing.List[int]:

	"""How far after its cycle's start each cycle's first note played, in ticks."""

	firsts: typing.Dict[int, int] = {}

	for tick, _ in played.onsets:
		firsts.setdefault(tick // played.cycle, tick % played.cycle)

	return [firsts[cycle] for cycle in sorted(firsts)]


GROOVES: typing.Dict[str, typing.Tuple[float, typing.Callable[[subsequence.PatternBuilder], None]]] = {
	"three sixteenths swung": (0.75, lambda p: p.swing(57)),
	"five sixteenths swung hard, at half strength": (1.25, lambda p: p.swing(75, strength = 0.5)),
	"a whole bar under a three-step groove": (4.0, lambda p: p.groove(subsequence.Groove(offsets = [0.0, 0.04, -0.02], grid = 0.25))),
	"swung as sixteenths, then as eighths": (0.75, lambda p: (p.swing(57), p.swing(60, grid = 0.5))),
}

GLIDES: typing.Dict[str, typing.Callable[[subsequence.PatternBuilder], None]] = {
	"slide": lambda p: p.slide(notes = [0], wrap = True, time = 0.5, bend_range = 12),
	"portamento": lambda p: p.portamento(time = 0.5, bend_range = 12, wrap = True),
	"bend": lambda p: p.bend(note = -1, amount = 0.5),
}


@pytest.mark.parametrize("glide", sorted(GLIDES))
@pytest.mark.parametrize("groove", sorted(GROOVES))
def test_a_glide_that_wraps_resets_on_the_note_it_leads_into (patch_midi: None, tmp_path: pathlib.Path, groove: str, glide: str) -> None:

	beats, feel = GROOVES[groove]

	def build (p: subsequence.PatternBuilder) -> None:
		p.note(LOW, beat = 0, duration = 0.25)
		p.note(HIGH, beat = 0.5, duration = 0.25)
		GLIDES[glide](p)
		feel(p)

	played = _play(tmp_path, beats, build)
	onsets = {tick for tick, _ in played.onsets}

	# The premise: the groove moves the first note from one cycle to the next.
	assert len(set(_first_offsets(played))) > 1, f"the first note never moved: {_first_offsets(played)}"
	assert len(played.resets) >= 4

	assert [tick for tick in played.resets if tick not in onsets] == []


def test_an_extended_slide_meets_the_next_cycle_s_first_note (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""303-style: the last note lasts until the first plays again, neither a gap nor an overlap."""

	def build (p: subsequence.PatternBuilder) -> None:
		p.note(LOW, beat = 0, duration = 0.25)
		p.note(HIGH, beat = 0.5, duration = 0.25)
		p.slide(notes = [0], wrap = True, time = 0.5, bend_range = 12, extend = True)
		p.swing(57)

	played = _play(tmp_path, 0.75, build)
	firsts = [tick for tick, note in played.onsets if note == LOW]
	ends = [tick for tick, note in played.ends if note == HIGH and tick <= firsts[-1]]

	assert len(set(_first_offsets(played))) > 1, "the first note never moved"
	assert len(ends) >= 4

	assert [tick for tick in ends if tick not in firsts] == []


def test_a_first_note_placed_after_the_groove_keeps_its_place (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The groove never moved it, so the next cycle plays it where this one did, and the reset stays on it."""

	def build (p: subsequence.PatternBuilder) -> None:
		p.note(HIGH, beat = 0.5, duration = 0.25)
		p.swing(57)
		p.note(LOW, beat = 0, duration = 0.25)
		p.slide(notes = [0], wrap = True, time = 0.5, bend_range = 12)

	played = _play(tmp_path, 0.75, build)
	onsets = {tick for tick, _ in played.onsets}

	assert set(_first_offsets(played)) == {0}, "the premise is a first note no groove moved"
	assert len(played.resets) >= 4

	assert [tick for tick in played.resets if tick not in onsets] == []


def _keeps_the_old_rule (played: _Played) -> None:

	"""Each cycle's wrap reset lands one cycle after that cycle's own first note, as before #2927.

	The slide goes into note 0 only, so every reset is a wrap: cycle k's lands in cycle k + 1.
	"""

	offsets = _first_offsets(played)
	old_rule = [(cycle + 1) * played.cycle + offset for cycle, offset in enumerate(offsets[:-1])]

	# The premise: the first note moves between cycles, so the old rule and the groove disagree.
	assert len(set(offsets)) > 1, f"the first note never moved: {offsets}"
	assert len(played.resets) >= 4

	assert played.resets == old_rule[:len(played.resets)]


def test_notes_moved_since_the_groove_keep_the_old_rule (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""After ``rotate()`` the first note was placed somewhere the groove alone cannot say (#2927).

	Evenly spaced notes rotate onto each other's pulses, so only the notes themselves show the
	move: foreseeing from the pulses alone put some resets a groove step away from their note.
	"""

	def build (p: subsequence.PatternBuilder) -> None:
		p.note(LOW, beat = 0, duration = 0.25)
		p.note(50, beat = 0.25, duration = 0.25)
		p.note(HIGH, beat = 0.5, duration = 0.25)
		p.slide(notes = [0], wrap = True, time = 0.5, bend_range = 12, extend = True)
		p.swing(60, grid = 0.5)
		p.rotate(1)

	_keeps_the_old_rule(_play(tmp_path, 0.75, build))


def test_a_groove_after_the_notes_moved_does_not_vouch_for_them (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""An accent groove after ``rotate()`` moves nothing, so the notes are where it left them; the swing before it does not explain them."""

	def build (p: subsequence.PatternBuilder) -> None:
		p.note(LOW, beat = 0, duration = 0.25)
		p.note(50, beat = 0.25, duration = 0.25)
		p.note(HIGH, beat = 0.5, duration = 0.25)
		p.slide(notes = [0], wrap = True, time = 0.5, bend_range = 12, extend = True)
		p.swing(60, grid = 0.5)
		p.rotate(1)
		p.groove(subsequence.Groove(offsets = [0.0], grid = 0.25, velocities = [1.1]))

	_keeps_the_old_rule(_play(tmp_path, 0.75, build))
