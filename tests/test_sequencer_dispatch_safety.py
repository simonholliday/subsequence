"""Sequencer event-dispatch must survive a malformed event.

If a single MIDI event in the queue has bad data (e.g. a tuple stored on
``velocity`` by a builder method that didn't validate, or any other shape
mismatch the sequencer wasn't expecting), dispatching it must not crash
the entire ``_process_pulse`` loop and tear down the composition.  This
is the defensive guarantee that catches whatever validation might still
slip through at a higher layer.
"""

import heapq
import typing

import pytest

import subsequence.sequencer


@pytest.mark.asyncio
async def test_process_pulse_survives_malformed_event (patch_midi: None) -> None:

	"""A bad event is logged and skipped; subsequent good events still dispatch."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	# Pulse 0: a malformed note_on whose velocity is a tuple — what would
	# happen if hit_steps(velocity=(25, 75)) silently stored the tuple
	# on Note.velocity, the way it did before the per-method validation.
	bad_event = subsequence.sequencer.MidiEvent(
		pulse = 0,
		message_type = 'note_on',
		channel = 0,
		note = 60,
		velocity = (25, 75),  # type: ignore[arg-type]  # deliberately bad
	)

	# Pulse 0: a well-formed event scheduled right after, which must still
	# fire even though the prior event blew up.
	good_event = subsequence.sequencer.MidiEvent(
		pulse = 0,
		message_type = 'note_on',
		channel = 0,
		note = 64,
		velocity = 90,
	)

	sequencer._push_event(bad_event)
	sequencer._push_event(good_event)

	# Should not raise.
	await sequencer._process_pulse(pulse=0)

	# The event queue must be drained (both events popped).
	assert len(sequencer.event_queue) == 0

	# The good event must have made it into active_notes; the bad one
	# must not have, since its tracking branch raised.
	assert (0, 0, 64) in sequencer.active_notes
	assert (0, 0, 60) not in sequencer.active_notes


@pytest.mark.asyncio
async def test_process_pulse_logs_failed_event_with_context (patch_midi: None, caplog: pytest.LogCaptureFixture) -> None:

	"""The skipped-event log must include enough context to debug — pulse, type, device, channel."""

	import logging
	caplog.set_level(logging.ERROR, logger="subsequence.sequencer")

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	bad_event = subsequence.sequencer.MidiEvent(
		pulse = 17,
		message_type = 'note_on',
		channel = 5,
		note = 60,
		velocity = (25, 75),  # type: ignore[arg-type]
		device = 0,
	)
	sequencer._push_event(bad_event)

	await sequencer._process_pulse(pulse=17)

	# Find the dispatch-failure log
	failure_messages = [r for r in caplog.records if "Failed to dispatch" in r.getMessage()]
	assert len(failure_messages) == 1
	msg = failure_messages[0].getMessage()
	assert "pulse 17" in msg
	assert "note_on" in msg
	assert "channel=5" in msg
