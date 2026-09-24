"""A run that ends by SystemExit still stops the sequencer (#3551).

`sys.exit()` from a pattern or a scheduled function is still the end of the piece, as it is in any
Python program, but it goes out through `Sequencer.stop()`: the panic, the closing of every held
note, the recording.  It used to leave the event loop with the run cancelled before the stop that
followed the wait, so a held note kept sounding and a render wrote no file.
"""

import pathlib
import sys
import typing

import mido
import pytest

import subsequence


def _notes (path: pathlib.Path) -> typing.List[typing.Tuple[str, int]]:

	"""Every note message in a file, as (on or off, pitch), a velocity-0 note_on counting as off."""

	found = []

	for track in mido.MidiFile(str(path)).tracks:
		for message in track:
			if message.type == "note_on" and message.velocity > 0:
				found.append(("on", message.note))
			elif message.type in ("note_on", "note_off"):
				found.append(("off", message.note))

	return found


def test_a_pattern_that_exits_still_stops_the_render (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The third build exits while the first two bars' note is held: the file is written, and the note released."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=1)
	builds: typing.List[int] = []

	@composition.pattern(channel=1, beats=4)
	def pad (p: subsequence.PatternBuilder) -> None:

		builds.append(p.cycle)

		if len(builds) == 3:
			sys.exit(0)

		p.note(60, beat=0, duration=4)

	filename = tmp_path / "exit.mid"

	with pytest.raises(SystemExit):
		composition.render(bars=8, filename=str(filename))

	assert len(builds) == 3, "the pattern never reached the build that exits"
	assert filename.exists(), "the render wrote no file: Sequencer.stop() never ran"

	notes = _notes(filename)

	assert ("on", 60) in notes
	assert notes.count(("on", 60)) == notes.count(("off", 60))
