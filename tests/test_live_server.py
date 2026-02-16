import asyncio
import inspect
import time

import pytest

import subsequence
import subsequence.composition
import subsequence.live_server
import subsequence.pattern


SENTINEL = b"\x04"


async def _send_recv (reader: asyncio.StreamReader, writer: asyncio.StreamWriter, code: str) -> str:

	"""Send code to the live server and return the response string."""

	writer.write(code.encode("utf-8") + SENTINEL)
	await writer.drain()

	chunks: list[bytes] = []

	while True:
		chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)

		if SENTINEL in chunk:
			before, _, _ = chunk.partition(SENTINEL)
			chunks.append(before)
			break

		chunks.append(chunk)

	return b"".join(chunks).decode("utf-8")


@pytest.fixture
def composition (patch_midi: None) -> subsequence.Composition:

	"""Create a composition with a simple pattern for testing."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	return comp


# --- Server eval tests ---


@pytest.mark.asyncio
async def test_eval_expression (composition: subsequence.Composition) -> None:

	"""Sending an expression should return its repr."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "1 + 1")

	assert result == "2"

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_exec_statement (composition: subsequence.Composition) -> None:

	"""Sending a statement should return OK, and its side effects should persist."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "x = 42")
	assert result == "OK"

	result = await _send_recv(reader, writer, "x")
	assert result == "42"

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_syntax_error_rejected (composition: subsequence.Composition) -> None:

	"""Sending invalid Python should return a SyntaxError traceback without executing anything."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "def foo(:")

	assert "SyntaxError" in result

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_runtime_error (composition: subsequence.Composition) -> None:

	"""Sending valid syntax that raises at runtime should return a traceback."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "1 / 0")

	assert "ZeroDivisionError" in result

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_namespace_has_composition (composition: subsequence.Composition) -> None:

	"""The eval namespace should include the composition object."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "composition.bpm")

	assert result == "120"

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_namespace_has_subsequence (composition: subsequence.Composition) -> None:

	"""The eval namespace should include the subsequence package."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "subsequence.__name__")

	assert result == "'subsequence'"

	writer.close()
	await writer.wait_closed()
	await server.stop()


# --- Composition live methods ---


def test_live_creates_server (patch_midi: None) -> None:

	"""Calling live() should create a LiveServer and set _is_live."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	comp.live(port=5556)

	assert comp._live_server is not None
	assert comp._is_live is True


def test_set_bpm (patch_midi: None) -> None:

	"""set_bpm() should update both the sequencer and the composition."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	comp.set_bpm(140)

	assert comp.bpm == 140
	assert comp._sequencer.current_bpm == 140


@pytest.mark.asyncio
async def test_set_bpm_via_server (composition: subsequence.Composition) -> None:

	"""Changing BPM through the live server should update composition.bpm."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "composition.set_bpm(140)")

	assert result == "OK"
	assert composition.bpm == 140
	assert composition._sequencer.current_bpm == 140

	writer.close()
	await writer.wait_closed()
	await server.stop()


def test_live_info (patch_midi: None) -> None:

	"""live_info() should return a dict with the expected keys."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="E")

	info = comp.live_info()

	assert info["bpm"] == 125
	assert info["key"] == "E"
	assert info["bar"] == 0
	assert info["section"] is None
	assert info["chord"] is None
	assert info["patterns"] == []
	assert info["data"] == {}


def test_live_info_with_data (patch_midi: None) -> None:

	"""live_info() should include the composition.data dict."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	comp.data["intensity"] = 0.8

	info = comp.live_info()

	assert info["data"]["intensity"] == 0.8


# --- Mute / Unmute ---


def test_mute_unmute (patch_midi: None) -> None:

	"""Muting a pattern should produce empty steps; unmuting should restore them."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	def my_builder (p):
		p.note(60, beat=0, velocity=100)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = comp._build_pattern_from_pending(pending)

	# Register it as a running pattern.
	comp._running_patterns["my_builder"] = pattern

	assert len(pattern.steps) > 0

	# Mute - next rebuild should produce empty steps.
	comp.mute("my_builder")

	assert pattern._muted is True

	pattern.on_reschedule()

	assert len(pattern.steps) == 0

	# Unmute - next rebuild should restore notes.
	comp.unmute("my_builder")

	assert pattern._muted is False

	pattern.on_reschedule()

	assert len(pattern.steps) > 0


def test_mute_unknown_pattern_raises (patch_midi: None) -> None:

	"""Muting a non-existent pattern should raise ValueError."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	with pytest.raises(ValueError, match="not found"):
		comp.mute("nonexistent")


def test_unmute_unknown_pattern_raises (patch_midi: None) -> None:

	"""Unmuting a non-existent pattern should raise ValueError."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	with pytest.raises(ValueError, match="not found"):
		comp.unmute("nonexistent")


def test_mute_preserves_cycle_count (patch_midi: None) -> None:

	"""Muting should keep advancing the cycle count even though no notes are produced."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	def my_builder (p):
		p.note(60, beat=0, velocity=100)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = comp._build_pattern_from_pending(pending)
	comp._running_patterns["my_builder"] = pattern

	# cycle_count starts at 1 (incremented in first _rebuild).
	initial_cycle = pattern._cycle_count

	comp.mute("my_builder")
	pattern.on_reschedule()  # muted rebuild
	pattern.on_reschedule()  # muted rebuild

	# Cycle count should have advanced by 2.
	assert pattern._cycle_count == initial_cycle + 2


# --- Hot-swap ---


def test_pattern_hot_swap (patch_midi: None) -> None:

	"""During a live session, re-decorating a pattern should replace its builder function."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	def my_pattern (p):
		p.note(60, beat=0, velocity=100)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_pattern,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = comp._build_pattern_from_pending(pending)
	comp._running_patterns["my_pattern"] = pattern
	comp._is_live = True

	# Original builder places a note at beat 0.
	assert 0 in pattern.steps

	# Hot-swap with a new builder that places a note at beat 2.
	@comp.pattern(channel=1, length=4)
	def my_pattern (p):
		p.note(72, beat=2, velocity=80)

	# Trigger rebuild.
	pattern.on_reschedule()

	# New builder should have placed a note at beat 2 (pulse 48).
	pulse_2 = int(2.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	assert pulse_2 in pattern.steps
	assert pattern.steps[pulse_2].notes[0].pitch == 72


def test_hot_swap_updates_wants_chord (patch_midi: None) -> None:

	"""Hot-swapping should update _wants_chord when the new builder's signature differs."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	def my_pattern (p):
		p.note(60, beat=0, velocity=100)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_pattern,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = comp._build_pattern_from_pending(pending)
	comp._running_patterns["my_pattern"] = pattern
	comp._is_live = True

	assert pattern._wants_chord is False

	# Hot-swap with a builder that wants chord.
	@comp.pattern(channel=1, length=4)
	def my_pattern (p, chord):
		pass

	assert pattern._wants_chord is True


# --- Live info with running patterns ---


def test_live_info_includes_patterns (patch_midi: None) -> None:

	"""live_info() should list running patterns with their metadata."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	def drums (p):
		p.note(36, beat=0, velocity=127)

	pending = subsequence.composition._PendingPattern(
		builder_fn = drums,
		channel = 9,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = comp._build_pattern_from_pending(pending)
	comp._running_patterns["drums"] = pattern

	info = comp.live_info()

	assert len(info["patterns"]) == 1
	assert info["patterns"][0]["name"] == "drums"
	assert info["patterns"][0]["channel"] == 9
	assert info["patterns"][0]["length"] == 4
	assert info["patterns"][0]["muted"] is False


# --- Safety ---


@pytest.mark.asyncio
async def test_blocked_builtins (composition: subsequence.Composition) -> None:

	"""Blocked builtins should return RuntimeError, not freeze or kill the process."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	for name in ("help()", "input()", "exit()", "quit()", "breakpoint()"):
		result = await _send_recv(reader, writer, name)
		assert "RuntimeError" in result, f"{name} should raise RuntimeError, got: {result}"
		assert "not available in live mode" in result

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_sys_exit_caught (composition: subsequence.Composition) -> None:

	"""sys.exit() should be caught and return an error, not kill the server."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	reader, writer = await asyncio.open_connection("127.0.0.1", port)

	result = await _send_recv(reader, writer, "import sys; sys.exit()")

	assert "SystemExit" in result

	# Server should still be alive - send another command.
	result = await _send_recv(reader, writer, "1 + 1")
	assert result == "2"

	writer.close()
	await writer.wait_closed()
	await server.stop()


@pytest.mark.asyncio
async def test_eval_does_not_block_event_loop (composition: subsequence.Composition) -> None:

	"""Eval should run in a thread, keeping the event loop responsive."""

	server = subsequence.live_server.LiveServer(composition, port=0)
	await server.start()
	port = server._server.sockets[0].getsockname()[1]

	# Open two connections - one sends a slow eval, the other pings.
	slow_reader, slow_writer = await asyncio.open_connection("127.0.0.1", port)
	fast_reader, fast_writer = await asyncio.open_connection("127.0.0.1", port)

	# Send a slow eval (0.5s sleep) on the first connection.
	slow_writer.write(b"__import__('time').sleep(0.5)\x04")
	await slow_writer.drain()

	# Give the slow eval a moment to start, then send a fast eval on the second connection.
	await asyncio.sleep(0.05)

	start = time.perf_counter()
	fast_result = await _send_recv(fast_reader, fast_writer, "1 + 1")
	fast_duration = time.perf_counter() - start

	assert fast_result == "2"

	# The fast eval should complete well before the 0.5s sleep finishes.
	assert fast_duration < 0.3, f"Fast eval took {fast_duration:.2f}s - event loop was blocked"

	# Wait for the slow eval to finish.
	slow_chunks: list[bytes] = []
	while True:
		chunk = await asyncio.wait_for(slow_reader.read(4096), timeout=5.0)
		if SENTINEL in chunk:
			before, _, _ = chunk.partition(SENTINEL)
			slow_chunks.append(before)
			break
		slow_chunks.append(chunk)

	slow_writer.close()
	await slow_writer.wait_closed()
	fast_writer.close()
	await fast_writer.wait_closed()
	await server.stop()
