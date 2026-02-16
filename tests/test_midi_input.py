import asyncio
import time

import mido
import pytest

import subsequence
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
	seq._midi_input_queue.put_nowait(mido.Message("start"))

	# Inject 24 clock ticks (= 1 beat).
	for _ in range(24):
		seq._midi_input_queue.put_nowait(mido.Message("clock"))

	# Inject stop to end the loop.
	seq._midi_input_queue.put_nowait(mido.Message("stop"))

	await seq.task

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
		seq._midi_input_queue.put_nowait(mido.Message("clock"))

	# Now send start + 5 more ticks.
	seq._midi_input_queue.put_nowait(mido.Message("start"))

	for _ in range(5):
		seq._midi_input_queue.put_nowait(mido.Message("clock"))

	seq._midi_input_queue.put_nowait(mido.Message("stop"))

	await seq.task

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
	seq._midi_input_queue.put_nowait(mido.Message("start"))

	for _ in range(48):
		seq._midi_input_queue.put_nowait(mido.Message("clock"))

	# Second start - resets pulse_count.
	seq._midi_input_queue.put_nowait(mido.Message("start"))

	for _ in range(10):
		seq._midi_input_queue.put_nowait(mido.Message("clock"))

	seq._midi_input_queue.put_nowait(mido.Message("stop"))

	await seq.task

	# Only 10 ticks since the last start.
	assert seq.pulse_count == 10

	await seq.stop()


@pytest.mark.asyncio
async def test_transport_stop_halts_sequencer (patch_midi: None) -> None:

	"""MIDI stop should set running to False."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	assert seq.running is True

	seq._midi_input_queue.put_nowait(mido.Message("stop"))

	await seq.task

	assert seq.running is False

	await seq.stop()


@pytest.mark.asyncio
async def test_transport_continue_resumes (patch_midi: None) -> None:

	"""MIDI continue should resume counting from the current position."""

	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Dummy MIDI",
		clock_follow=True
	)

	await seq.start()

	# The sequencer starts waiting for a start/continue.
	# Send continue instead of start - should resume from pulse 0 (initial position).
	seq._midi_input_queue.put_nowait(mido.Message("continue"))

	for _ in range(12):
		seq._midi_input_queue.put_nowait(mido.Message("clock"))

	seq._midi_input_queue.put_nowait(mido.Message("stop"))

	await seq.task

	assert seq.pulse_count == 12

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
