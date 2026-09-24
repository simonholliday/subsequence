import asyncio
import time
import typing

import mido
import pytest

import subsequence
import subsequence.midi_utils
import subsequence.sequencer
import conftest


# --- Sequencer input device configuration ---


def test_sequencer_accepts_input_device (patch_midi: None) -> None:

	"""Sequencer should store the input device name when provided."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	assert seq.input_device_name == "Dummy MIDI"
	assert seq.clock_follow is True


@pytest.mark.asyncio
async def test_a_clock_input_that_will_not_open_is_refused (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""The input a piece follows would not open, and the loop waited for its ticks for ever (#3556).

	The only sign was one log line; the piece now refuses to start, naming the input.
	"""

	def _will_not_open (name: str, callback: typing.Any = None) -> typing.Any:
		raise OSError(f"{name} is held by another program")

	monkeypatch.setattr(mido, "open_input", _will_not_open)

	sequencer = subsequence.sequencer.Sequencer(
		output_device_name = "Dummy MIDI",
		initial_bpm = 120,
		input_device_name = "Dummy MIDI",
		clock_follow = True,
	)

	try:
		with pytest.raises(RuntimeError, match = "clock_follow: the MIDI input 'Dummy MIDI' did not open"):
			await sequencer.start()
	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_an_additional_clock_input_that_will_not_open_is_refused (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""The same, where the clock is followed from a second input and the first opens (#3556)."""

	open_the_fake = mido.open_input

	def _clock_will_not_open (name: str, callback: typing.Any = None) -> typing.Any:

		if name == "Clock":
			raise OSError("Clock is held by another program")

		return open_the_fake(name, callback = callback)

	monkeypatch.setattr(mido, "get_input_names", lambda: ["Keys", "Clock"])
	monkeypatch.setattr(mido, "open_input", _clock_will_not_open)

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)
	composition.midi_input("Keys")
	composition.midi_input("Clock", clock_follow = True)

	# Unfixed, the run plays on waiting for the clock, so it is given a few seconds.
	with pytest.raises(RuntimeError, match = "clock_follow: the MIDI input 'Clock' did not open"):
		await asyncio.wait_for(composition._run(), timeout = 3)


def test_clock_follow_without_input_raises (patch_midi: None) -> None:

	"""clock_follow=True without an input device should raise ValueError."""

	with pytest.raises(ValueError):
		subsequence.sequencer.Sequencer(
			output_device_name="Dummy MIDI",
			initial_bpm=120,
			clock_follow=True
		)


def test_sequencer_no_input_by_default (patch_midi: None) -> None:

	"""Sequencer should have no MIDI input by default."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120
	)

	assert seq.input_device_name is None
	assert seq.clock_follow is False
	assert seq.midi_in is None


@pytest.mark.asyncio
async def test_sequencer_opens_input_port (patch_midi: None) -> None:

	"""Starting a sequencer with input_device_name should open the MIDI input port."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI"
	)

	await seq.start()

	assert seq.midi_in is not None
	assert isinstance(seq.midi_in, conftest.FakeMidiIn)

	seq.running = False
	await seq.task
	await seq.stop()


# --- Clock follow  - - pulse counting ---


async def _drain (seq: subsequence.sequencer.Sequencer) -> None:

	"""Let the clock loop consume everything injected into its input queue.

	These tests used to end by injecting a MIDI Stop and awaiting the loop
	task.  A Stop holds the position now rather than ending the session
	(#3053), so the task does not complete and that idiom hangs.  Yielding
	until the queue is empty and then settling is the replacement: the loop and
	the test share one thread, so there is nothing else to wait for.
	"""

	for _ in range(5000):
		if seq._midi_input_queue.empty():
			break
		await asyncio.sleep(0)
	else:
		raise AssertionError("the clock loop never drained its input queue")

	for _ in range(200):
		await asyncio.sleep(0)



@pytest.mark.asyncio
async def test_clock_follow_advances_pulses (patch_midi: None) -> None:

	"""Each MIDI clock tick should advance pulse_count by one."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	# Inject a start message to begin counting.
	seq._midi_input_queue.put_nowait((0, mido.Message("start"), time.perf_counter()))

	# Inject 24 clock ticks (= 1 beat).
	for _ in range(24):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	await _drain(seq)

	assert seq.pulse_count == 24

	await seq.stop()


@pytest.mark.asyncio
async def test_clock_follow_waits_for_start (patch_midi: None) -> None:

	"""Clock ticks before a start message should be ignored."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	# Send clock ticks without a start - should be ignored.
	for _ in range(10):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	# Now send start + 5 more ticks.
	seq._midi_input_queue.put_nowait((0, mido.Message("start"), time.perf_counter()))

	for _ in range(5):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	await _drain(seq)

	# Only the 5 ticks after start should have been counted.
	assert seq.pulse_count == 5

	await seq.stop()


# --- Transport messages ---


@pytest.mark.asyncio
async def test_transport_start_resets_position (patch_midi: None) -> None:

	"""MIDI start should reset pulse_count to 0."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	# Start, count some ticks, then start again (resets).
	seq._midi_input_queue.put_nowait((0, mido.Message("start"), time.perf_counter()))

	for _ in range(48):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	# Second start - resets pulse_count.
	seq._midi_input_queue.put_nowait((0, mido.Message("start"), time.perf_counter()))

	for _ in range(10):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	await _drain(seq)

	# Only 10 ticks since the last start.
	assert seq.pulse_count == 10

	await seq.stop()


@pytest.mark.asyncio
async def test_transport_stop_holds_the_position (patch_midi: None) -> None:

	"""MIDI stop pauses: it holds the pulse and leaves the session running.

	It used to set ``running = False``, so a master's Stop button tore the
	session down and the Continue after it had nothing left to resume
	(decision 14 of #2991, measured on #3053).  The session now ends only with
	Ctrl+C or ``stop()``.
	"""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	assert seq.running is True

	seq._midi_input_queue.put_nowait((0, mido.Message("start"), time.perf_counter()))

	for _ in range(48):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	await _drain(seq)

	assert seq.pulse_count == 48, "the clock never advanced, so the hold below proves nothing"

	seq._midi_input_queue.put_nowait((0, mido.Message("stop"), time.perf_counter()))

	await _drain(seq)

	assert seq.running is True, "a MIDI stop ended the session instead of pausing it"
	assert seq.task is not None and not seq.task.done()
	assert seq.pulse_count == 48, "the position was not held across the stop"

	# Ticks keep arriving while the master is stopped; they must not advance us.
	for _ in range(24):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	await _drain(seq)

	assert seq.pulse_count == 48, "clock ticks advanced the piece while the transport was stopped"

	await seq.stop()


@pytest.mark.asyncio
async def test_transport_continue_resumes (patch_midi: None) -> None:

	"""MIDI continue should resume from the current position, not restart at zero."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	# Clocks before any start/continue are ignored (position stays 0).
	for _ in range(8):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	# Drive the sequencer to a non-zero position.
	seq._midi_input_queue.put_nowait((0, mido.Message("start"), time.perf_counter()))

	for _ in range(24):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	# Continue must preserve the position (start resets it — see
	# test_transport_start_resets_position above).
	seq._midi_input_queue.put_nowait((0, mido.Message("continue"), time.perf_counter()))

	for _ in range(12):
		seq._midi_input_queue.put_nowait((0, mido.Message("clock"), time.perf_counter()))

	await _drain(seq)

	# 24 ticks before continue + 12 after: resumed from pulse 24, not 0.
	assert seq.pulse_count == 36

	await seq.stop()


# --- BPM estimation ---


def test_bpm_estimation (patch_midi: None) -> None:

	"""Feeding clock ticks at known intervals should produce a correct BPM estimate."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	# Simulate 120 BPM: 24 ticks per beat, 0.5s per beat → ~0.02083s per tick.
	tick_interval = 0.5 / 24  # 120 BPM

	base_time = 100.0

	for i in range(48):
		seq._estimate_bpm(base_time + i * tick_interval)

	# Should estimate close to 120 BPM.
	assert abs(seq.current_bpm - 120) <= 1


# --- set_bpm in clock_follow mode ---


@pytest.mark.asyncio
async def test_set_bpm_noop_in_clock_follow (patch_midi: None) -> None:

	"""set_bpm() should have no effect when clock_follow is enabled and running."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	# Before start, set_bpm works (needed for initial setup).
	seq.set_bpm(100)
	assert seq.current_bpm == 100

	# Start the sequencer - now set_bpm should be ignored.
	await seq.start()

	seq.set_bpm(200)
	assert seq.current_bpm == 100  # Unchanged

	seq.running = False
	await seq.task
	await seq.stop()


# --- Composition.midi_input() ---


def test_composition_midi_input_method (patch_midi: None) -> None:

	"""midi_input() should store the input device name and clock_follow flag."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	comp.midi_input(device="Dummy MIDI", clock_follow=True)

	assert comp._input_device == "Dummy MIDI"
	assert comp._clock_follow is True


def test_composition_midi_input_default_no_clock (patch_midi: None) -> None:

	"""midi_input() without clock_follow should default to False."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	comp.midi_input(device="Dummy MIDI")

	assert comp._input_device == "Dummy MIDI"
	assert comp._clock_follow is False


def test_live_info_includes_input_fields (patch_midi: None) -> None:

	"""live_info() should include input_device and clock_follow."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	info = comp.live_info()

	assert info["input_device"] is None
	assert info["clock_follow"] is False


def test_live_info_with_midi_input (patch_midi: None) -> None:

	"""live_info() should reflect midi_input() configuration."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	comp.midi_input(device="Dummy MIDI", clock_follow=True)

	info = comp.live_info()

	assert info["input_device"] == "Dummy MIDI"
	assert info["clock_follow"] is True


# --- select_input_device ---


def test_select_input_device_none_returns_none (patch_midi: None) -> None:

	"""No device name means no input — (None, None) without prompting."""

	name, port = subsequence.midi_utils.select_input_device(None)

	assert name is None
	assert port is None


def test_select_input_device_opens_named_device (patch_midi: None) -> None:

	"""A named device that exists is opened directly."""

	name, port = subsequence.midi_utils.select_input_device("Dummy MIDI")

	assert name == "Dummy MIDI"
	assert isinstance(port, conftest.FakeMidiIn)


def test_select_input_device_missing_name_raises (patch_midi: None) -> None:

	"""A named device that is missing raises instead of falling back to another input."""

	with pytest.raises(ValueError, match="not found"):
		subsequence.midi_utils.select_input_device("Nonexistent Device")
