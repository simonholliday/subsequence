"""A scheduled function that never returns cannot keep the piece from ending (#3553).

A plain function given to ``schedule()`` ran on the loop's default executor, whose threads the
loop joins when it closes and the interpreter joins again at exit.  One that never returned held
the process open after the piece had stopped, and Ctrl+C and SIGTERM reached a loop that had
nothing left to stop.  In a render, which awaits each call, it held ``stop()`` itself.  Such a
function now runs on one of the sequencer's daemon threads: ``stop()`` gives it a moment to finish
and then leaves it behind, naming it, and a loop still waiting on it is cancelled.
"""

import asyncio
import pathlib
import threading
import time
import typing

import pytest

import subsequence
import subsequence.composition
import subsequence.sequencer


def _waits_for (event: threading.Event, what: str, seconds: float = 5.0) -> None:

	"""Fail rather than hang when something the test waits for never happens."""

	assert event.wait(seconds), f"{what} never happened"


def test_a_scheduled_function_runs_on_a_daemon_thread (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The default executor's threads are joined at exit; the sequencer's are daemons, which are not."""

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)
	daemon: typing.List[bool] = []

	def note_the_thread () -> None:
		daemon.append(threading.current_thread().daemon)

	composition.schedule(note_the_thread, cycle_beats = 4)

	@composition.pattern(channel = 1, beats = 4)
	def pad (p: subsequence.PatternBuilder) -> None:
		p.note(60, beat = 0)

	composition.render(bars = 2, filename = str(tmp_path / "daemon.mid"))

	assert daemon, "the scheduled function never ran"
	assert all(daemon)


def test_the_run_ends_while_a_scheduled_function_is_still_running (patch_midi: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:

	"""A playing run stops and returns, where it waited for the function (up to its 10 s here) at the loop's close."""

	monkeypatch.setattr(subsequence.sequencer, "_SCHEDULED_CALL_GRACE_SECONDS", 0.2, raising = False)
	started, release = threading.Event(), threading.Event()

	def stuck () -> None:
		started.set()
		release.wait(timeout = 10)

	async def main () -> None:

		sequencer = subsequence.sequencer.Sequencer(output_device_name = "Dummy MIDI", initial_bpm = 240)
		await subsequence.composition.schedule_task(sequencer, stuck, cycle_beats = 1)
		await sequencer.start()
		await asyncio.to_thread(_waits_for, started, "the scheduled function")
		await sequencer.stop()

	began = time.monotonic()

	try:
		subsequence.sequencer.run(main())
		took = time.monotonic() - began
	finally:
		release.set()

	assert took < 5, f"the run waited {took:.1f} s for a scheduled function that had not returned"
	assert "'stuck' was still running" in caplog.text


@pytest.mark.asyncio
async def test_stop_ends_a_render_waiting_on_a_scheduled_function_that_never_returns (patch_midi: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:

	"""A render awaits each scheduled call, and stop() awaited the render: it now cancels the wait."""

	monkeypatch.setattr(subsequence.sequencer, "_LOOP_STOP_GRACE_SECONDS", 0.2, raising = False)
	monkeypatch.setattr(subsequence.sequencer, "_SCHEDULED_CALL_GRACE_SECONDS", 0.2, raising = False)
	started, release = threading.Event(), threading.Event()

	def stuck () -> None:
		started.set()
		release.wait(timeout = 10)

	sequencer = subsequence.sequencer.Sequencer(output_device_name = "Dummy MIDI", initial_bpm = 120)
	sequencer.render_mode = True
	sequencer.render_bars = 4
	await subsequence.composition.schedule_task(sequencer, stuck, cycle_beats = 1)

	try:
		await sequencer.start()
		await asyncio.to_thread(_waits_for, started, "the scheduled function")
		began = time.monotonic()
		await asyncio.wait_for(sequencer.stop(), timeout = 5)
		took = time.monotonic() - began
	finally:
		release.set()

	# Unfixed, only the test's own timeout ended it: stop() takes that cancellation for the loop's.
	assert took < 3, f"stop() took {took:.1f} s, waiting on the render's scheduled call"
	assert "did not end within" in caplog.text
	assert "'stuck' was still running" in caplog.text


def test_a_scheduled_function_that_finishes_soon_is_let_finish (patch_midi: None) -> None:

	"""A guard: stop() waits a moment for a call in flight, as the default executor's join did, so one
	that is nearly done is not cut off."""

	started, finished = threading.Event(), threading.Event()

	def brief () -> None:
		started.set()
		time.sleep(0.3)
		finished.set()

	async def main () -> None:

		sequencer = subsequence.sequencer.Sequencer(output_device_name = "Dummy MIDI", initial_bpm = 240)
		await subsequence.composition.schedule_task(sequencer, brief, cycle_beats = 16)
		await sequencer.start()
		await asyncio.to_thread(_waits_for, started, "the scheduled function")
		await sequencer.stop()

	subsequence.sequencer.run(main())

	assert finished.is_set(), "the run ended before a function that was nearly done could finish"
