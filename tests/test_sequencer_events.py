import pytest

import subsequence.pattern
import subsequence.sequencer


@pytest.mark.asyncio
async def test_reschedule_event_precedes_pattern_rebuild (patch_midi: None) -> None:

	"""The reschedule_pulse event should fire before pattern on_reschedule."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	order: list[str] = []

	def on_reschedule_pulse (pulse: int, patterns: list[subsequence.pattern.Pattern]) -> None:

		"""Record reschedule event order."""

		order.append("event")

	sequencer.on_event("reschedule_pulse", on_reschedule_pulse)

	class TestPattern (subsequence.pattern.Pattern):

		"""Pattern that records reschedule timing."""

		def __init__ (self) -> None:

			"""Initialize a short pattern cycle."""

			super().__init__(channel=0, length=2, reschedule_lookahead=1)


		def on_reschedule (self) -> None:

			"""Record the pattern rebuild order."""

			order.append("pattern")


	pattern = TestPattern()
	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)

	reschedule_pulse = pattern.length * sequencer.pulses_per_beat - pattern.reschedule_lookahead * sequencer.pulses_per_beat
	await sequencer._maybe_reschedule_patterns(reschedule_pulse)

	assert order == ["event", "pattern"]


@pytest.mark.asyncio
async def test_repeating_callback_fires_without_patterns (patch_midi: None) -> None:

	"""Repeating callbacks should fire even when no patterns are scheduled."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	fired: list[int] = []

	def on_tick (pulse: int) -> None:

		"""Record when the callback fires."""

		fired.append(pulse)

	await sequencer.schedule_callback_repeating(on_tick, interval_beats=2, start_pulse=0, reschedule_lookahead=1)

	fire_pulse = (2 - 1) * sequencer.pulses_per_beat
	await sequencer._maybe_reschedule_patterns(fire_pulse)

	assert fired == [fire_pulse]


@pytest.mark.asyncio
async def test_callback_precedes_reschedule_event (patch_midi: None) -> None:

	"""Repeating callbacks should run before reschedule events and pattern rebuilds."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	order: list[str] = []

	def on_tick (pulse: int) -> None:

		"""Record when the repeating callback fires."""

		order.append("callback")

	def on_reschedule_pulse (pulse: int, patterns: list[subsequence.pattern.Pattern]) -> None:

		"""Record reschedule event order."""

		order.append("event")

	sequencer.on_event("reschedule_pulse", on_reschedule_pulse)

	class TestPattern (subsequence.pattern.Pattern):

		"""Pattern that records reschedule timing."""

		def __init__ (self) -> None:

			"""Initialize a short pattern cycle."""

			super().__init__(channel=0, length=2, reschedule_lookahead=1)


		def on_reschedule (self) -> None:

			"""Record the pattern rebuild order."""

			order.append("pattern")

	pattern = TestPattern()
	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)
	await sequencer.schedule_callback_repeating(on_tick, interval_beats=2, start_pulse=0, reschedule_lookahead=1)

	reschedule_pulse = pattern.length * sequencer.pulses_per_beat - pattern.reschedule_lookahead * sequencer.pulses_per_beat
	await sequencer._maybe_reschedule_patterns(reschedule_pulse)

	assert order == ["callback", "event", "pattern"]


@pytest.mark.asyncio
async def test_dynamic_length_change_on_reschedule (patch_midi: None) -> None:

	"""When a pattern changes its length in on_reschedule, the sequencer should use the new length for the next cycle."""

	sequencer = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	class GrowingPattern (subsequence.pattern.Pattern):

		"""Pattern that doubles its length on first reschedule."""

		def __init__ (self) -> None:

			"""Initialize with a 2-beat cycle."""

			super().__init__(channel=0, length=2, reschedule_lookahead=1)
			self.reschedule_count = 0

		def on_reschedule (self) -> None:

			"""Double the length on the first reschedule."""

			self.reschedule_count += 1

			if self.reschedule_count == 1:
				self.length = 4

	pattern = GrowingPattern()
	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)

	# First reschedule fires at: length(2) - lookahead(1) = 1 beat = 24 pulses.
	first_reschedule_pulse = int((2 - 1) * sequencer.pulses_per_beat)
	await sequencer._maybe_reschedule_patterns(first_reschedule_pulse)

	assert pattern.reschedule_count == 1
	assert pattern.length == 4

	# After the first reschedule, the next cycle starts at pulse 2*24=48.
	# With new length=4 and lookahead=1, next reschedule should be at: 48 + (4-1)*24 = 48+72 = 120.
	# The old length would give: 48 + (2-1)*24 = 48+24 = 72.
	# We check the reschedule queue to verify the new timing is used.
	_, _, scheduled = sequencer.reschedule_queue[0]

	expected_next_reschedule = int(2 * sequencer.pulses_per_beat) + int((4 - 1) * sequencer.pulses_per_beat)

	assert scheduled.next_reschedule_pulse == expected_next_reschedule
	assert scheduled.length_pulses == int(4 * sequencer.pulses_per_beat)
