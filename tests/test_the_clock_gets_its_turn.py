"""A thread that is computing cannot keep the clock waiting while a piece plays live (#3552).

Python lets a thread keep the interpreter for its switch interval, 5 ms by default, while another
waits for it, so a synchronous scheduled function computing on its own thread held the clock up to
that long: up to 9.5 ms late, measured, where the README promises no pulse more than 0.1 ms out.  A live
run shortens the interval to 0.2 ms and puts back what it found when it stops.  The timing itself
was measured on the ticket and is not measured here: a stopwatch on a loaded machine makes a flaky
test.
"""

import pathlib
import sys
import typing

import mido
import pytest

import subsequence
import subsequence.composition
import subsequence.sequencer


SHORTENED = 0.0002


@pytest.fixture
def interval () -> typing.Iterator[typing.Callable[[float], float]]:

	"""Set the interval a test starts from, and put the process's own back afterwards.

	Each test installs its own value first: an earlier test can leave a sequencer playing, and
	with it a shortened interval, which a test that only read "before" would compare against.
	"""

	original = sys.getswitchinterval()

	def install (seconds: float) -> float:
		sys.setswitchinterval(seconds)
		return sys.getswitchinterval()

	try:
		yield install
	finally:
		sys.setswitchinterval(original)


def _play_and_stop (while_playing: typing.Callable[[], None]) -> None:

	"""Start a live sequencer, run ``while_playing`` while it plays, and stop it."""

	async def main () -> None:

		sequencer = subsequence.sequencer.Sequencer(output_device_name = "Dummy MIDI", initial_bpm = 120)
		await sequencer.start()

		try:
			assert sequencer.running and not sequencer.render_mode
			while_playing()
		finally:
			await sequencer.stop()

	subsequence.sequencer.run(main())


@pytest.mark.parametrize("found", [0.005, 0.002])
def test_a_live_run_shortens_the_interval_and_stop_puts_back_what_it_found (patch_midi: None, interval: typing.Callable[[float], float], found: float) -> None:

	"""Python's default comes back after the piece, and so does a longer interval somebody set."""

	before = interval(found)
	playing: typing.List[float] = []

	_play_and_stop(lambda: playing.append(sys.getswitchinterval()))

	assert playing == pytest.approx([SHORTENED], abs = 1e-9)
	assert sys.getswitchinterval() == before


def test_a_shorter_interval_somebody_set_is_kept (patch_midi: None, interval: typing.Callable[[float], float]) -> None:

	"""The run never lengthens it: somebody who asked for less already has what the clock needs."""

	before = interval(0.0001)
	playing: typing.List[float] = []

	_play_and_stop(lambda: playing.append(sys.getswitchinterval()))

	assert playing == [before]
	assert sys.getswitchinterval() == before


def test_an_interval_changed_while_playing_is_not_undone_by_stop (patch_midi: None, interval: typing.Callable[[float], float]) -> None:

	"""``stop()`` puts back only what ``start()`` changed: a value set during the piece is somebody's choice."""

	interval(0.005)
	chosen: typing.List[float] = []

	def change_it () -> None:
		assert sys.getswitchinterval() == pytest.approx(SHORTENED, abs = 1e-9), "the run did not shorten the interval"
		sys.setswitchinterval(0.001)
		chosen.append(sys.getswitchinterval())

	_play_and_stop(change_it)

	assert chosen, "the change was never made"
	assert sys.getswitchinterval() == chosen[0]


def test_a_render_leaves_the_interval_alone (patch_midi: None, interval: typing.Callable[[float], float], tmp_path: pathlib.Path) -> None:

	"""A render keeps no time, so it has no clock to protect.  Read by a scheduled function, mid-render."""

	before = interval(0.005)
	seen: typing.List[float] = []

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)

	def note_the_interval () -> None:
		seen.append(sys.getswitchinterval())

	composition.schedule(note_the_interval, cycle_beats = 4)

	@composition.pattern(channel = 1, beats = 4)
	def pad (p: subsequence.PatternBuilder) -> None:
		p.note(60, beat = 0)

	composition.render(bars = 2, filename = str(tmp_path / "render.mid"))

	assert seen, "the scheduled function never ran, so nothing was read mid-render"
	assert seen == [before] * len(seen)
	assert sys.getswitchinterval() == before


def test_a_run_that_refuses_to_start_leaves_the_interval_alone (patch_midi: None, interval: typing.Callable[[float], float], monkeypatch: pytest.MonkeyPatch) -> None:

	"""A refused start never reaches ``stop()``, so it must not have shortened anything.

	``run_until_stopped()`` starts the sequencer before the ``try`` whose ``finally`` stops it, so
	this is the caller a refusal really has: a clock input that will not open (#3556).
	"""

	before = interval(0.005)

	def _will_not_open (name: str, callback: typing.Any = None) -> typing.Any:
		raise OSError(f"{name} is held by another program")

	monkeypatch.setattr(mido, "open_input", _will_not_open)

	sequencer = subsequence.sequencer.Sequencer(
		output_device_name = "Dummy MIDI",
		initial_bpm = 120,
		input_device_name = "Dummy MIDI",
		clock_follow = True,
	)

	with pytest.raises(RuntimeError, match = "did not open"):
		subsequence.sequencer.run(subsequence.composition.run_until_stopped(sequencer))

	assert sys.getswitchinterval() == before
