import mido
import pytest

import subsequence.pattern
import subsequence.sequencer


class FakeMidiOut:

	"""
	Minimal MIDI output stub for tests.
	"""

	def send (self, message: mido.Message) -> None:

		"""
		Ignore outgoing MIDI messages.
		"""

		return None


	def close (self) -> None:

		"""
		No-op close for the fake device.
		"""

		return None


	def panic (self) -> None:

		"""
		No-op panic for the fake device.
		"""

		return None


	def reset (self) -> None:

		"""
		No-op reset for the fake device.
		"""

		return None


def _fake_get_output_names () -> list[str]:

	"""
	Return a fixed list of MIDI output names for tests.
	"""

	return ["Dummy MIDI"]


def _fake_open_output (name: str) -> FakeMidiOut:

	"""
	Return a fake MIDI output regardless of the name.
	"""

	return FakeMidiOut()


def _has_note_on_at_pulse (events: list[subsequence.sequencer.MidiEvent], pulse: int, note: int) -> bool:

	"""
	Check whether a note_on event exists at a given pulse.
	"""

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
async def test_reschedule_triggers_and_uses_updated_notes (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Ensure rescheduling triggers at lookahead and uses updated pattern state.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	sequencer = subsequence.sequencer.Sequencer(midi_device_name="Dummy MIDI", initial_bpm=120)

	class TestPattern (subsequence.pattern.Pattern):

		"""
		Pattern that changes its notes when rescheduled.
		"""

		def __init__ (self) -> None:

			"""
			Initialize the test pattern with a short cycle.
			"""

			super().__init__(channel=0, length=4, reschedule_lookahead=1)

			self.reschedule_calls = 0
			self._build(initial=True)


		def _build (self, initial: bool) -> None:

			"""
			Build either the initial or rescheduled note set.
			"""

			self.steps = {}

			if initial:
				self.add_note(position=0, pitch=60, velocity=100, duration=6)

			else:
				self.add_note(position=12, pitch=61, velocity=100, duration=6)


		def on_reschedule (self) -> None:

			"""
			Switch to the rescheduled note layout.
			"""

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
async def test_reschedule_lookahead_validation (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Invalid lookahead values should raise when scheduling repeating patterns.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	sequencer = subsequence.sequencer.Sequencer(midi_device_name="Dummy MIDI", initial_bpm=120)
	pattern = subsequence.pattern.Pattern(channel=0, length=2, reschedule_lookahead=3)

	with pytest.raises(ValueError):
		await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)
