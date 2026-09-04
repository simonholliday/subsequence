"""Tests for transport pause and resume — Sequencer.pause()/resume() and the Composition mirror.

Pause holds the clock where it is and resume continues from the same pulse, unlike
stop() which discards the position.  These run against the real wall clock rather
than render mode: pause deliberately refuses in render mode, where the clock is
simulated and there is nothing to hold.

The burst test is the one that matters.  The clock loop catches up every overdue
pulse in a single pass, so a pause that did not rebase its deadline would deliver
the entire held span at once on resume.
"""

import asyncio
import time
import typing

import pytest

import conftest

import subsequence.pattern
import subsequence.sequencer


# 600 BPM at 24 PPQN is a 4.17 ms pulse, so a fifth of a second of pause spans
# roughly 48 of them — plenty to tell a burst from a clean resume without making
# the suite wait.
_TEST_BPM = 600
_PULSE_SECONDS = 60.0 / _TEST_BPM / 24
_PAUSE_SECONDS = 0.2


def _running_sequencer (**kwargs: typing.Any) -> subsequence.sequencer.Sequencer:

	"""A sequencer that keeps its clock running with nothing scheduled.

	Setting ``_jitter_log`` skips the loop's "sequence complete" check, which
	would otherwise stop the clock as soon as the queues drained — the same
	hook the benchmarks use.
	"""

	sequencer = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI", initial_bpm=_TEST_BPM, **kwargs,
	)
	sequencer._jitter_log = []

	return sequencer


@pytest.mark.asyncio
async def test_resume_after_a_pause_does_not_burst (patch_midi: None) -> None:

	"""The held span is not delivered all at once when the clock restarts.

	This is the failure the feature exists to avoid: the loop's inner
	``while current_time >= next_pulse_time`` processes every overdue pulse in
	one pass without yielding, so leaving the deadline behind would fire ~48
	pulses of MIDI as fast as the loop could run.
	"""

	sequencer = _running_sequencer()
	await sequencer.start()

	try:
		await asyncio.sleep(0.05)

		sequencer.pause()
		await asyncio.sleep(0.05)		# let the loop notice and settle into the hold
		at_pause = sequencer.pulse_count

		await asyncio.sleep(_PAUSE_SECONDS)

		# Nothing advances while held.
		assert sequencer.pulse_count == at_pause

		sequencer.resume()
		await asyncio.sleep(0.03)

		advanced = sequencer.pulse_count - at_pause

		# Real elapsed time since resume allows ~7 pulses; the burst this guards
		# against would be the whole held span, ~48.  The bound is loose enough
		# for a busy machine and still an order of magnitude below a burst.
		assert advanced <= 20, f"resumed with a burst of {advanced} pulses"

	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_counters_continue_across_a_pause (patch_midi: None) -> None:

	"""Pulse, bar and beat carry across the hold instead of resetting."""

	sequencer = _running_sequencer()
	await sequencer.start()

	try:
		await asyncio.sleep(0.1)

		sequencer.pause()
		await asyncio.sleep(0.05)

		held = (sequencer.pulse_count, sequencer.current_bar, sequencer.current_beat)
		assert held[0] > 0, "expected the clock to have advanced before pausing"

		await asyncio.sleep(_PAUSE_SECONDS)
		assert (sequencer.pulse_count, sequencer.current_bar, sequencer.current_beat) == held

		sequencer.resume()
		await asyncio.sleep(0.05)

		assert sequencer.pulse_count > held[0], "clock did not resume"

	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_no_note_is_left_sounding_across_a_pause (patch_midi: None) -> None:

	"""A note held when the transport stops is released, not left ringing."""

	sequencer = _running_sequencer()

	# A long note guarantees something is sounding when the pause lands.
	pattern = subsequence.pattern.Pattern(channel=0, length=64, device=0)
	pattern.add_note(position=0, pitch=60, velocity=100, duration=1536)
	await sequencer.schedule_pattern(pattern, start_pulse=0)

	await sequencer.start()

	try:
		await asyncio.sleep(0.05)
		assert sequencer.active_notes, "expected a sounding note before the pause"

		sequencer.pause()
		await asyncio.sleep(0.05)

		assert not sequencer.active_notes, "a note was left sounding across the pause"

	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_clock_output_sends_stop_and_continue_never_start (patch_midi: None) -> None:

	"""Pause sends Stop and resume sends Continue.

	Start (0xFA) would reset downstream hardware to the top of its own pattern,
	which is exactly what a pause must not do.  Ticks stop while held.
	"""

	sequencer = _running_sequencer(clock_output=True)
	spy = conftest.SpyMidiOut()
	sequencer.midi_out = spy

	await sequencer.start()

	try:
		await asyncio.sleep(0.05)

		sequencer.pause()
		await asyncio.sleep(0.05)

		after_pause = [message.type for message in spy.sent]
		assert after_pause.count("stop") == 1
		ticks_at_pause = after_pause.count("clock")

		await asyncio.sleep(_PAUSE_SECONDS)

		# No ticks go out while the transport is held.
		assert [m.type for m in spy.sent].count("clock") == ticks_at_pause

		sequencer.resume()
		await asyncio.sleep(0.05)

		types = [message.type for message in spy.sent]
		assert types.count("continue") == 1
		assert types.index("stop") < types.index("continue")

		# Exactly one Start, from the initial start() — never from a resume.
		assert types.count("start") == 1

	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_pause_and_resume_emit_events (patch_midi: None) -> None:

	"""The events fire when the transport actually changes, not when asked.

	A panel follows these rather than assuming its own button worked, so they
	are emitted from the clock loop once the hold is in effect.
	"""

	sequencer = _running_sequencer()
	seen: typing.List[str] = []

	sequencer.events.on("pause", lambda *a: seen.append("pause"))
	sequencer.events.on("resume", lambda *a: seen.append("resume"))

	await sequencer.start()

	try:
		await asyncio.sleep(0.05)

		sequencer.pause()
		await asyncio.sleep(0.05)
		assert seen == ["pause"]

		sequencer.resume()
		await asyncio.sleep(0.05)
		assert seen == ["pause", "resume"]

	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_pause_and_resume_are_idempotent (patch_midi: None) -> None:

	"""Pausing a paused transport, or resuming a running one, does nothing."""

	sequencer = _running_sequencer()
	seen: typing.List[str] = []

	sequencer.events.on("pause", lambda *a: seen.append("pause"))
	sequencer.events.on("resume", lambda *a: seen.append("resume"))

	await sequencer.start()

	try:
		await asyncio.sleep(0.05)

		sequencer.resume()			# already running
		await asyncio.sleep(0.02)
		assert seen == []

		sequencer.pause()
		sequencer.pause()			# second pause is a no-op
		await asyncio.sleep(0.05)
		assert seen == ["pause"]
		assert sequencer.paused

		sequencer.resume()
		sequencer.resume()			# second resume is a no-op
		await asyncio.sleep(0.05)
		assert seen == ["pause", "resume"]
		assert not sequencer.paused

	finally:
		await sequencer.stop()


@pytest.mark.asyncio
async def test_stop_while_paused_tears_down_cleanly (patch_midi: None) -> None:

	"""stop() from a paused transport completes rather than hanging in the hold."""

	sequencer = _running_sequencer()
	await sequencer.start()

	await asyncio.sleep(0.05)
	sequencer.pause()
	await asyncio.sleep(0.05)

	await asyncio.wait_for(sequencer.stop(), timeout=2.0)

	assert not sequencer.running
	assert not sequencer.paused, "stop() must clear the paused flag"


@pytest.mark.asyncio
async def test_pause_is_refused_when_the_clock_is_not_ours (patch_midi: None) -> None:

	"""Render mode, external clock and Link all decline rather than half-working.

	Silently doing nothing would leave a transport UI showing a paused state
	that never happened; each of these logs and leaves the flag clear.
	"""

	render = _running_sequencer()
	render.running = True
	render.render_mode = True
	render.pause()
	assert not render.paused

	following = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI", input_device_name="Dummy MIDI", clock_follow=True,
	)
	following.running = True
	following.pause()
	assert not following.paused

	linked = _running_sequencer()
	linked.running = True
	linked._link_clock = object()
	linked.pause()
	assert not linked.paused


@pytest.mark.asyncio
async def test_pause_before_playback_does_nothing (patch_midi: None) -> None:

	"""A transport that was never started has no pulse to hold."""

	sequencer = _running_sequencer()

	sequencer.pause()

	assert not sequencer.paused


@pytest.mark.asyncio
async def test_composition_mirrors_the_transport (patch_midi: None) -> None:

	"""Composition.pause()/resume()/is_paused delegate to the sequencer."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=_TEST_BPM)
	composition._sequencer._jitter_log = []

	await composition._sequencer.start()

	try:
		await asyncio.sleep(0.05)

		assert not composition.is_paused

		composition.pause()
		await asyncio.sleep(0.05)
		assert composition.is_paused

		composition.resume()
		await asyncio.sleep(0.05)
		assert not composition.is_paused

	finally:
		await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_held_time_is_accumulated_not_charged_to_the_music (patch_midi: None) -> None:

	"""The paused span is recorded separately and start_time is left alone.

	start_time seeds the clock deadline and nothing else reads it, so the hold
	is bookkept as an offset rather than by rewriting when playback began.
	"""

	sequencer = _running_sequencer()
	await sequencer.start()

	try:
		await asyncio.sleep(0.05)
		started_at = sequencer.start_time

		sequencer.pause()
		await asyncio.sleep(_PAUSE_SECONDS)
		sequencer.resume()
		await asyncio.sleep(0.05)

		assert sequencer.start_time == started_at, "start_time must not be shifted"
		assert sequencer._paused_seconds >= _PAUSE_SECONDS * 0.8

	finally:
		await sequencer.stop()
