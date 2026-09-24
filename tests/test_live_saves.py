"""What a save to a watched file does to a playing composition.

Driven through `_reload_async` directly, as `tests/test_live_reloader.py` does, so each save
lands exactly when the test says.
"""

import asyncio
import os
import pathlib
import signal
import sys
import threading
import time
import typing

import pytest

import subsequence


def _part (name: str) -> str:

	"""One part, as a watched file declares it."""

	return f"@composition.pattern(channel=1, beats=4)\ndef {name} (p):\n\tpass\n\n"


async def _watching (tmp_path: pathlib.Path, source: str) -> typing.Tuple[subsequence.Composition, pathlib.Path]:

	"""A composition watching a file that holds `source`, its parts already playing."""

	live_file = tmp_path / "parts.py"
	live_file.write_text(source)

	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
	composition._sequencer._event_loop = asyncio.get_running_loop()
	composition.watch(live_file)

	# What _run() does with the parts the first load declared.
	await composition._activate_new_pending_patterns()

	# From here on a save lands only when the test says: the polling thread would
	# otherwise notice each rewrite too, and apply it a second time.
	assert composition._live_reloader is not None
	composition._live_reloader.stop()

	return composition, live_file


@pytest.mark.asyncio
async def test_a_save_that_calls_sys_exit_is_that_save_s_failure (patch_midi: None, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:

	"""A watched file's sys.exit() left the loop and ended the performance with notes sounding (#3551).

	It is the save's failure, as SystemExit is at the REPL: logged, and the parts left as they were.
	"""

	composition, live_file = await _watching(tmp_path, _part("keeper"))
	assert composition._live_reloader is not None

	live_file.write_text("import sys\nsys.exit(0)\n")

	try:
		await composition._live_reloader._reload_async()
	except SystemExit:
		pytest.fail("the save's sys.exit() escaped the watcher, and would have ended the performance")

	assert "keeper" in composition._running_patterns
	assert "called sys.exit()" in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="sends a signal to its own process")
@pytest.mark.asyncio
@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
async def test_a_stopping_signal_stops_a_save_that_holds_the_loop (patch_midi: None, tmp_path: pathlib.Path, number: signal.Signals) -> None:

	"""A save whose top level never finished held the music, and the signal waited for it (#3378).

	The performance's handler is installed as `run_until_stopped` installs it, so its callback
	runs on the loop the save was holding: it must still hear the signal, once, after the save
	has been stopped.
	"""

	loop = asyncio.get_running_loop()
	heard: typing.List[float] = []
	loop.add_signal_handler(number, lambda: heard.append(time.monotonic()))
	composition, live_file = await _watching(tmp_path, _part("drums"))
	timer = threading.Timer(0.3, os.kill, (os.getpid(), number))

	try:
		# Bounded, so a tree without the guard finishes late instead of hanging.
		live_file.write_text(_part("drums") + "import time\nuntil = time.monotonic() + 6\nwhile time.monotonic() < until: pass\n")

		started = time.monotonic()
		timer.start()

		try:
			await composition._live_reloader._reload_async()
			escaped: typing.Optional[BaseException] = None
		except BaseException as error:
			escaped = error

		took = time.monotonic() - started
		await asyncio.sleep(0.1)

		# A stopped save is the performance ending, not the file's error, and
		# must not escape the watcher's coroutine.
		assert escaped is None
		assert took < 3.0
		assert len(heard) == 1

	finally:
		timer.cancel()
		loop.remove_signal_handler(number)
		composition._live_reloader.stop()


def _pending_names (composition: subsequence.Composition) -> typing.List[str]:

	"""The parts waiting to start, by name."""

	return [pending.builder_fn.__name__ for pending in composition._pending_patterns]


@pytest.mark.asyncio
async def test_a_save_that_raises_starts_none_of_its_new_parts_now_or_later (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The failed save's new part used to wait, and the next good save - which never declared it - started it (#3377).

	Nothing owned it then, so no later save could take it out again.
	"""

	composition, live_file = await _watching(tmp_path, _part("drums"))
	assert composition._live_reloader is not None

	live_file.write_text(_part("drums") + _part("fill") + "raise RuntimeError('half way')\n")
	await composition._live_reloader._reload_async()

	assert "fill" not in composition._running_patterns
	assert "fill" not in _pending_names(composition)

	live_file.write_text(_part("drums"))
	await composition._live_reloader._reload_async()

	assert sorted(composition._running_patterns) == ["drums"]


@pytest.mark.asyncio
async def test_a_typed_line_that_raises_starts_none_of_its_new_parts_now_or_later (patch_midi: None) -> None:

	"""The line was answered with its traceback and started nothing; the next line started its part (#3377)."""

	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
	composition.live(port=0)
	loop = asyncio.get_running_loop()
	composition._event_loop = loop
	composition._sequencer._event_loop = loop
	composition._open_output_devices()
	server = composition._live_server
	assert server is not None
	await server.start()
	assert server._server is not None
	port = server._server.sockets[0].getsockname()[1]
	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	async def _typed (code: str) -> str:
		writer.write(code.encode() + subsequence.live_server.SENTINEL)
		await writer.drain()
		answer = await asyncio.wait_for(reader.readuntil(subsequence.live_server.SENTINEL), timeout=5.0)
		return answer[:-1].decode().strip().splitlines()[-1]

	try:
		assert await _typed(_part("lead") + "raise RuntimeError('half way')") == "RuntimeError: half way"
		assert "lead" not in composition._running_patterns

		assert await _typed("1 + 1") == "2"
		assert "lead" not in composition._running_patterns
		assert "lead" not in _pending_names(composition)

	finally:
		writer.close()
		await server.stop()


def test_a_load_that_raises_before_play_leaves_only_what_was_pending_before_it (patch_midi: None) -> None:

	"""play() would have started the failed load's part; a part declared before the load still waits, as it should."""

	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

	@composition.pattern(channel=1, beats=4)
	def keep (p: subsequence.PatternBuilder) -> None:
		pass

	with pytest.raises(RuntimeError, match="half way"):
		composition.load_patterns(_part("extra") + "raise RuntimeError('half way')\n", "extra")

	assert _pending_names(composition) == ["keep"]


def test_a_first_load_that_raises_leaves_nothing_of_its_own_pending (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""watch() still raises, so a broken entry point is loud; its parts do not wait for play()."""

	live_file = tmp_path / "parts.py"
	live_file.write_text(_part("drums") + "raise RuntimeError('half way')\n")
	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

	with pytest.raises(RuntimeError, match="half way"):
		composition.watch(live_file)

	assert _pending_names(composition) == []


def _run_as_a_script (composition: subsequence.Composition, live_file: pathlib.Path) -> None:

	"""What `python session.py` does to a file laid out as examples/live_single_file.py is."""

	namespace = {"__name__": "__main__", "__file__": str(live_file), "composition": composition}
	exec(compile(live_file.read_text(), str(live_file), "exec"), namespace)

	# The layout under test: the file watches itself, so its own run declared its parts.
	assert composition._live_reloader is not None and composition._live_reloader._skip_initial_exec


def _session (*names: str) -> str:

	"""A single-file session: it watches itself once, then declares its parts at the top level."""

	return "if __name__ == '__main__':\n\tcomposition.watch(__file__)\n\n" + "".join(_part(name) for name in names)


def test_starting_the_performance_records_what_a_self_watching_file_declared (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""play() is where the record is made - through the same start-up render shares - so it is tested there."""

	live_file = tmp_path / "session.py"
	live_file.write_text(_session("drums", "bass"))
	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
	_run_as_a_script(composition, live_file)
	assert composition._live_reloader is not None
	composition._live_reloader.stop()

	assert str(live_file) not in composition._source_declared

	composition.render(bars=1, filename=str(tmp_path / "out.mid"))

	assert composition._source_declared.get(str(live_file)) == {"drums", "bass"}


@pytest.mark.asyncio
async def test_a_self_watching_file_can_delete_a_part_in_its_first_save (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The first save found nothing recorded to compare with, so a part it deleted played on (#3376).

	A name another source owns is not the file's to take out, even here.
	"""

	live_file = tmp_path / "session.py"
	live_file.write_text(_session("drums", "bass"))
	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
	composition._sequencer._event_loop = asyncio.get_running_loop()
	_run_as_a_script(composition, live_file)
	assert composition._live_reloader is not None
	composition._live_reloader.stop()
	composition._source_declared["<extra>"] = {"pad"}

	@composition.pattern(channel=2, beats=4)
	def pad (p: subsequence.PatternBuilder) -> None:
		pass

	await composition._activate_new_pending_patterns()
	composition._live_reloader.claim_what_the_script_declared()

	live_file.write_text(_session("drums"))
	await composition._live_reloader._reload_async()

	assert sorted(composition._running_patterns) == ["drums", "pad"]


def test_a_change_is_applied_only_once_the_file_has_held_still_for_a_poll (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""A save caught half-written was applied at first sight, restarting every part it had not reached yet (#3375).

	Each call to `_due()` is one poll.  The half-written file is seen by one poll and changed by
	the next, so it is never due; the whole file, seen twice the same, is.
	"""

	live_file = tmp_path / "parts.py"
	live_file.write_text(_part("drums") + _part("bass"))
	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
	composition.watch(live_file)
	reloader = composition._live_reloader
	assert reloader is not None
	reloader.stop()

	assert reloader._due() is None

	live_file.write_text(_part("drums"))
	half = reloader._due()

	live_file.write_text(_part("drums") + _part("bass") + _part("fill"))
	moved = reloader._due()
	due = reloader._due()

	assert (half, moved) == (None, None)
	assert due is not None and due == reloader._signature()

	reloader._applied = due
	assert reloader._due() is None


@pytest.mark.asyncio
async def test_a_file_that_changes_while_it_is_read_is_left_for_the_watcher (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""What was read may be half of one save and half of the next, so it is dropped until the file settles."""

	composition, live_file = await _watching(tmp_path, _part("drums"))
	reloader = composition._live_reloader
	assert reloader is not None

	live_file.write_text(_part("drums") + _part("fill"))
	await reloader._reload_async((0, 0))

	assert "fill" not in composition._running_patterns
	assert reloader._applied is None

	await reloader._reload_async(reloader._signature())

	assert "fill" in composition._running_patterns


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_read_is_tried_again_at_the_next_poll (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The docstring promised a retry, but what was applied had already moved on, so nothing retried until the next save."""

	composition, live_file = await _watching(tmp_path, _part("drums"))
	reloader = composition._live_reloader
	assert reloader is not None

	# A directory where the file was: it can be looked at, and not read, on any system.
	live_file.unlink()
	live_file.mkdir()
	reloader._applied = reloader._signature()
	await reloader._reload_async()

	assert reloader._applied is None

	live_file.rmdir()
	live_file.write_text(_part("drums"))

	assert reloader._due() is None
	assert reloader._due() == reloader._signature()


def test_a_watched_file_that_failed_to_load_claims_none_of_the_script_s_parts (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""Only a file that watches itself is the whole script; a two-file watch that failed to load is not.

	Its first load raised, and a script that caught that and played anyway would otherwise have
	the wrapper's own parts claimed as the watched file's - for its first save to delete.
	"""

	live_file = tmp_path / "parts.py"
	live_file.write_text("raise RuntimeError('half way')\n")
	composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

	@composition.pattern(channel=1, beats=4)
	def wrapper_part (p: subsequence.PatternBuilder) -> None:
		pass

	with pytest.raises(RuntimeError, match="half way"):
		composition.watch(live_file)

	assert composition._live_reloader is not None
	composition._live_reloader.stop()
	composition._live_reloader.claim_what_the_script_declared()

	assert str(live_file) not in composition._source_declared


@pytest.mark.asyncio
async def test_the_watcher_hands_its_reload_what_it_settled_on (patch_midi: None, tmp_path: pathlib.Path) -> None:

	"""The re-check after reading only works if the watcher passes on what it settled on; two polls, as its thread makes them."""

	composition, live_file = await _watching(tmp_path, _part("drums"))
	reloader = composition._live_reloader
	assert reloader is not None
	handed: typing.List[typing.Any] = []
	reload = reloader._reload_async

	async def _recording (expected: typing.Any = None) -> None:
		handed.append(expected)
		await reload(expected)

	reloader._reload_async = _recording  # type: ignore[method-assign]
	live_file.write_text(_part("drums") + _part("fill"))

	await asyncio.to_thread(reloader._poll)
	await asyncio.to_thread(reloader._poll)
	await asyncio.sleep(0.1)

	assert handed == [reloader._signature()]
	assert "fill" in composition._running_patterns
