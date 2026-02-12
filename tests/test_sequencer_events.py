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


@pytest.mark.asyncio
async def test_reschedule_event_precedes_pattern_rebuild (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	The reschedule_pulse event should fire before pattern on_reschedule.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	sequencer = subsequence.sequencer.Sequencer(midi_device_name="Dummy MIDI", initial_bpm=120)
	order: list[str] = []

	def on_reschedule_pulse (pulse: int, patterns: list[subsequence.pattern.Pattern]) -> None:

		"""
		Record reschedule event order.
		"""

		order.append("event")

	sequencer.on_event("reschedule_pulse", on_reschedule_pulse)

	class TestPattern (subsequence.pattern.Pattern):

		"""
		Pattern that records reschedule timing.
		"""

		def __init__ (self) -> None:

			"""
			Initialize a short pattern cycle.
			"""

			super().__init__(channel=0, length=2, reschedule_lookahead=1)


		def on_reschedule (self) -> None:

			"""
			Record the pattern rebuild order.
			"""

			order.append("pattern")


	pattern = TestPattern()
	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)

	reschedule_pulse = pattern.length * sequencer.pulses_per_beat - pattern.reschedule_lookahead * sequencer.pulses_per_beat
	await sequencer._maybe_reschedule_patterns(reschedule_pulse)

	assert order == ["event", "pattern"]


@pytest.mark.asyncio
async def test_repeating_callback_fires_without_patterns (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Repeating callbacks should fire even when no patterns are scheduled.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	sequencer = subsequence.sequencer.Sequencer(midi_device_name="Dummy MIDI", initial_bpm=120)
	fired: list[int] = []

	def on_tick (pulse: int) -> None:

		"""
		Record when the callback fires.
		"""

		fired.append(pulse)

	await sequencer.schedule_callback_repeating(on_tick, interval_beats=2, start_pulse=0, reschedule_lookahead=1)

	fire_pulse = (2 - 1) * sequencer.pulses_per_beat
	await sequencer._maybe_reschedule_patterns(fire_pulse)

	assert fired == [fire_pulse]


@pytest.mark.asyncio
async def test_callback_precedes_reschedule_event (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Repeating callbacks should run before reschedule events and pattern rebuilds.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	sequencer = subsequence.sequencer.Sequencer(midi_device_name="Dummy MIDI", initial_bpm=120)
	order: list[str] = []

	def on_tick (pulse: int) -> None:

		"""
		Record when the repeating callback fires.
		"""

		order.append("callback")

	def on_reschedule_pulse (pulse: int, patterns: list[subsequence.pattern.Pattern]) -> None:

		"""
		Record reschedule event order.
		"""

		order.append("event")

	sequencer.on_event("reschedule_pulse", on_reschedule_pulse)

	class TestPattern (subsequence.pattern.Pattern):

		"""
		Pattern that records reschedule timing.
		"""

		def __init__ (self) -> None:

			"""
			Initialize a short pattern cycle.
			"""

			super().__init__(channel=0, length=2, reschedule_lookahead=1)


		def on_reschedule (self) -> None:

			"""
			Record the pattern rebuild order.
			"""

			order.append("pattern")

	pattern = TestPattern()
	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)
	await sequencer.schedule_callback_repeating(on_tick, interval_beats=2, start_pulse=0, reschedule_lookahead=1)

	reschedule_pulse = pattern.length * sequencer.pulses_per_beat - pattern.reschedule_lookahead * sequencer.pulses_per_beat
	await sequencer._maybe_reschedule_patterns(reschedule_pulse)

	assert order == ["callback", "event", "pattern"]
