import pytest

import subsequence.pattern
import subsequence.sequencer


def _has_note_on_at_pulse (events: list[subsequence.sequencer.MidiEvent], pulse: int, note: int) -> bool:

	"""Check whether a note_on event exists at a given pulse."""

	for event in events:

		if event.pulse != pulse:
			continue

		if event.message_type != 'note_on':
			continue

		if event.note != note:
			continue

		return True

	return False


@pytest.mark.asyncio
async def test_reschedule_triggers_and_uses_updated_notes (patch_midi: None) -> None:

	"""Ensure rescheduling triggers at lookahead and uses updated pattern state."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	class TestPattern (subsequence.pattern.Pattern):

		"""Pattern that changes its notes when rescheduled."""

		def __init__ (self) -> None:

			"""Initialize the test pattern with a short cycle."""

			super().__init__(channel=0, length=4, reschedule_lookahead=1)

			self.reschedule_calls = 0
			self._build(initial=True)


		def _build (self, initial: bool) -> None:

			"""Build either the initial or rescheduled note set."""

			self.steps = {}

			if initial:
				self.add_note(position=0, pitch=60, velocity=100, duration=6)

			else:
				self.add_note(position=12, pitch=61, velocity=100, duration=6)


		def on_reschedule (self) -> None:

			"""Switch to the rescheduled note layout."""

			self.reschedule_calls += 1
			self._build(initial=False)


	pattern = TestPattern()
	length_pulses = pattern.length * sequencer.pulses_per_beat
	lookahead_pulses = pattern.reschedule_lookahead * sequencer.pulses_per_beat
	reschedule_pulse = length_pulses - lookahead_pulses

	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)

	await sequencer._maybe_reschedule_patterns(reschedule_pulse - 1)
	assert pattern.reschedule_calls == 0

	await sequencer._maybe_reschedule_patterns(reschedule_pulse)
	assert pattern.reschedule_calls == 1

	next_start = length_pulses
	expected_note_pulse = next_start + 12

	events = list(sequencer.event_queue)
	assert _has_note_on_at_pulse(events, expected_note_pulse, 61)


@pytest.mark.asyncio
async def test_reschedule_lookahead_validation (patch_midi: None) -> None:

	"""Invalid lookahead values should raise when scheduling repeating patterns."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	pattern = subsequence.pattern.Pattern(channel=0, length=2, reschedule_lookahead=3)

	with pytest.raises(ValueError):
		await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)

@pytest.mark.asyncio
async def test_failing_reschedule_is_contained (patch_midi: None) -> None:

	"""A pattern whose rebuild raises must lose its cycle, not kill the clock.

	Regression: the reschedule loop had no containment, so a raising
	on_reschedule() (or a set_length() below the lookahead) propagated up and
	stopped every pattern.
	"""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	class BadPattern (subsequence.pattern.Pattern):

		"""Pattern that shrinks itself below the reschedule lookahead."""

		def __init__ (self) -> None:
			super().__init__(channel=0, length=4, reschedule_lookahead=1)
			self.add_note(position=0, pitch=60, velocity=100, duration=6)

		def on_reschedule (self) -> None:
			# Below the 1-beat lookahead - _get_pattern_timing raises.
			self.length = 0.5

	class GoodPattern (subsequence.pattern.Pattern):

		"""Healthy sibling that must keep rescheduling."""

		def __init__ (self) -> None:
			super().__init__(channel=0, length=4, reschedule_lookahead=1)
			self.reschedule_calls = 0
			self.add_note(position=0, pitch=62, velocity=100, duration=6)

		def on_reschedule (self) -> None:
			self.reschedule_calls += 1

	bad = BadPattern()
	good = GoodPattern()

	await sequencer.schedule_pattern_repeating(bad, start_pulse=0)
	await sequencer.schedule_pattern_repeating(good, start_pulse=0)

	reschedule_pulse = 4 * sequencer.pulses_per_beat - 1 * sequencer.pulses_per_beat

	# Must not raise, and the healthy pattern must still rebuild.
	await sequencer._maybe_reschedule_patterns(reschedule_pulse)

	assert good.reschedule_calls == 1

	# The failing pattern keeps its previous timing and stays in rotation.
	queued = [entry[2].pattern for entry in sequencer.reschedule_queue]
	assert bad in queued


@pytest.mark.asyncio
async def test_stop_survives_crashed_loop_task (patch_midi: None) -> None:

	"""stop() must run its cleanup even when the loop task died with an exception.

	Regression: stop() awaited the task unguarded, so a crashed loop aborted
	shutdown before panic / port close / recording save.
	"""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	async def _doomed () -> None:
		raise RuntimeError("loop died")

	sequencer.task = __import__("asyncio").get_event_loop().create_task(_doomed())

	# Must not raise.
	await sequencer.stop()
