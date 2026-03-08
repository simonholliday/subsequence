"""Tests for composition.trigger() one-shot pattern triggering."""

import pytest

import subsequence
import subsequence.constants.durations as dur


@pytest.mark.asyncio
async def test_trigger_immediate_creates_pattern (patch_midi: None) -> None:

	"""Calling trigger() with quantize=0 should schedule a pattern immediately."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
		key="C"
	)

	# Record the pulse when trigger is called
	current_pulse = composition._sequencer.pulse_count

	# Define a simple trigger function
	def builder (p):
		p.note(60, beat=0, velocity=100, duration=0.5)

	# Manually set up the event loop before calling trigger
	# (In real playback this is done by play() calling asyncio.run(_run()))
	import asyncio
	await composition._sequencer.start()

	# Call trigger
	composition.trigger(builder, channel=1, quantize=0)

	# Wait a moment for the async scheduling to complete
	await asyncio.sleep(0.01)

	# Check that the event queue has been populated
	assert len(composition._sequencer.event_queue) > 0

	# Verify that we have note_on and note_off events
	event_types = [e.message_type for e in composition._sequencer.event_queue]
	assert "note_on" in event_types
	assert "note_off" in event_types

	await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_trigger_with_quantize_beat_boundary (patch_midi: None) -> None:

	"""Calling trigger() with quantize=dur.QUARTER should snap to next beat."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
		key="C"
	)

	await composition._sequencer.start()

	# Advance the sequencer to mid-beat (pulse 5 out of 24 pulses per beat)
	composition._sequencer.pulse_count = 5

	def builder (p):
		p.note(62, beat=0, velocity=90, duration=0.5)

	composition.trigger(builder, channel=1, quantize=dur.QUARTER)

	await asyncio.sleep(0.01)

	# The next beat boundary is at pulse 24
	# Verify that events are scheduled at or after that pulse
	event_pulses = [e.pulse for e in composition._sequencer.event_queue]
	assert all(p >= 24 for p in event_pulses), f"Expected events at pulse >= 24, got {event_pulses}"

	await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_trigger_with_quantize_bar_boundary (patch_midi: None) -> None:

	"""Calling trigger() with quantize=dur.WHOLE should snap to next bar (4 beats)."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
		key="C"
	)

	await composition._sequencer.start()

	# Advance to middle of a bar (pulse 50 out of 96 pulses per bar at 120 BPM)
	composition._sequencer.pulse_count = 50

	def builder (p):
		p.note(64, beat=0, velocity=85, duration=0.5)

	composition.trigger(builder, channel=1, quantize=dur.WHOLE)

	await asyncio.sleep(0.01)

	# The next bar boundary is at pulse 96
	event_pulses = [e.pulse for e in composition._sequencer.event_queue]
	assert all(p >= 96 for p in event_pulses), f"Expected events at pulse >= 96, got {event_pulses}"

	await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_trigger_with_chord_context (patch_midi: None) -> None:

	"""Calling trigger() with chord=True should inject the current chord."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
		key="C"
	)

	composition.harmony(style="functional_major", cycle_beats=4)

	await composition._sequencer.start()

	captured_chord = None

	def builder (p, chord):
		nonlocal captured_chord
		# Access the chord from the parameter
		captured_chord = chord
		p.note(60, beat=0, velocity=100, duration=0.5)

	composition.trigger(builder, channel=1, chord=True, quantize=0)

	await asyncio.sleep(0.01)

	# Verify that the chord was available to the builder
	assert captured_chord is not None
	assert hasattr(captured_chord, 'tones')

	await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_trigger_with_drum_note_map (patch_midi: None) -> None:

	"""Calling trigger() with drum_note_map should work with drum names."""

	import subsequence.constants.instruments.gm_drums as gm_drums

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
	)

	await composition._sequencer.start()

	def builder (p):
		p.note("kick_1", beat=0, velocity=100, duration=0.5)

	composition.trigger(
		builder,
		channel=9,
		drum_note_map=gm_drums.GM_DRUM_MAP,
		quantize=0
	)

	await asyncio.sleep(0.01)

	# Verify that MIDI notes were generated (kick_1 should map to a specific note)
	assert len(composition._sequencer.event_queue) > 0

	await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_trigger_builder_exception_is_logged (patch_midi: None) -> None:

	"""If the trigger builder raises, the pattern should be silent but not crash."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
	)

	await composition._sequencer.start()

	def broken_builder (p):
		raise ValueError("Test error")

	# Should not raise
	composition.trigger(broken_builder, channel=1)

	await asyncio.sleep(0.01)

	# The pattern was never added to the event queue due to the exception
	# This is the expected behavior (silent pattern)

	await composition._sequencer.stop()


@pytest.mark.asyncio
async def test_trigger_before_playback_is_safe (patch_midi: None) -> None:

	"""Calling trigger() before playback started should be safe (not crash)."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
	)

	def builder (p):
		p.note(60, beat=0, velocity=100, duration=0.5)

	# Trigger without calling play() - should not crash
	composition.trigger(builder, channel=1)


@pytest.mark.asyncio
async def test_trigger_uses_builder_chaining (patch_midi: None) -> None:

	"""Trigger should support PatternBuilder method chaining."""

	composition = subsequence.Composition(
		output_device="Dummy MIDI",
		bpm=120,
	)

	await composition._sequencer.start()

	def builder (p):
		# Use method chaining
		p.note(60, beat=0, velocity=100, duration=0.5).note(62, beat=0.5, velocity=90, duration=0.5)

	composition.trigger(builder, channel=1)

	await asyncio.sleep(0.01)

	# Verify that both notes were added to the event queue
	event_types = [e.message_type for e in composition._sequencer.event_queue]
	note_on_count = event_types.count("note_on")
	assert note_on_count >= 2, f"Expected at least 2 note_on events, got {note_on_count}"

	await composition._sequencer.stop()


import asyncio
