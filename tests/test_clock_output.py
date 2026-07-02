"""Tests for MIDI clock output — 0xF8 ticks and start/stop transport messages.

With ``clock_output=True`` the sequencer sends a Start before the first tick,
one clock tick per pulse (24 PPQN, so 24 per beat), and a Stop at shutdown.
Driven through the real run loop in render mode (fast, no wall clock).
"""

import pytest

import conftest

import subsequence.pattern
import subsequence.sequencer


@pytest.mark.asyncio
async def test_clock_output_sends_ticks_and_transport (patch_midi: None) -> None:

	"""One bar of playback emits start, 96 clock ticks (24 per beat), then stop."""

	sequencer = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI", initial_bpm=120, clock_output=True,
	)
	spy = conftest.SpyMidiOut()
	sequencer.midi_out = spy

	sequencer.render_mode = True
	sequencer.render_bars = 1

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)
	pattern.add_note(position=0, pitch=60, velocity=100, duration=12)
	await sequencer.schedule_pattern(pattern, start_pulse=0)

	await sequencer.start()
	assert sequencer.task is not None
	await sequencer.task
	await sequencer.stop()

	types = [message.type for message in spy.sent]

	# 24 ticks per beat × 4 beats = 96 for the rendered bar.
	assert types.count("clock") == 96
	assert types.count("start") == 1
	assert types.count("stop") == 1

	# Transport framing: start precedes the first tick, stop follows the last.
	assert types.index("start") < types.index("clock")
	assert len(types) - 1 - types[::-1].index("stop") > len(types) - 1 - types[::-1].index("clock")


@pytest.mark.asyncio
async def test_clock_output_disabled_sends_no_realtime_messages (patch_midi: None) -> None:

	"""The default (clock_output=False) emits no clock/start/stop messages."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	spy = conftest.SpyMidiOut()
	sequencer.midi_out = spy

	sequencer.render_mode = True
	sequencer.render_bars = 1

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)
	pattern.add_note(position=0, pitch=60, velocity=100, duration=12)
	await sequencer.schedule_pattern(pattern, start_pulse=0)

	await sequencer.start()
	assert sequencer.task is not None
	await sequencer.task
	await sequencer.stop()

	assert not any(message.type in ("clock", "start", "stop") for message in spy.sent)
