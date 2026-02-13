import mido
import pytest

import subsequence
import subsequence.composition
import subsequence.harmonic_state
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


def test_composition_creates_sequencer (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Composition should create a working sequencer with the given device and BPM.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=140, key="C")

	assert composition._sequencer is not None
	assert composition._sequencer.current_bpm == 140
	assert composition.device == "Dummy MIDI"
	assert composition.key == "C"


def test_composition_harmony_creates_state (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Calling harmony() should create a HarmonicState with the given parameters.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="E")

	composition.harmony(
		style = "turnaround_global",
		cycle = 4,
		dominant_7th = True,
		gravity = 0.8,
		minor_weight = 0.25
	)

	assert composition._harmonic_state is not None
	assert composition._harmonic_state.key_name == "E"
	assert composition._harmony_cycle_beats == 4


def test_composition_harmony_without_key_raises (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Calling harmony() without a key should raise ValueError.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125)

	with pytest.raises(ValueError):
		composition.harmony(style="turnaround_global", cycle=4)


def test_pattern_decorator_registers_pending (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	The pattern decorator should register a pending pattern without scheduling immediately.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	@composition.pattern(channel=10, length=4)
	def my_pattern (p):
		pass

	assert len(composition._pending_patterns) == 1
	assert composition._pending_patterns[0].channel == 10
	assert composition._pending_patterns[0].length == 4


def test_pattern_decorator_returns_original_function (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	The pattern decorator should return the original function unchanged.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	def my_fn (p):
		pass

	decorated = composition.pattern(channel=1, length=4)(my_fn)

	assert decorated is my_fn


def test_build_pattern_from_pending_calls_builder (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Building a pattern from pending should call the builder function.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")
	calls = []

	def my_builder (p):
		calls.append("called")

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert len(calls) == 1
	assert isinstance(pattern, subsequence.pattern.Pattern)
	assert pattern.channel == 1
	assert pattern.length == 4


def test_build_pattern_rebuilds_on_reschedule (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	The decorator pattern should re-run the builder on on_reschedule.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")
	call_count = [0]

	def my_builder (p):
		call_count[0] += 1

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert call_count[0] == 1

	pattern.on_reschedule()

	assert call_count[0] == 2


def test_chord_injection (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Builder functions with a chord parameter should receive the current chord.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="E")

	composition.harmony(
		style = "turnaround_global",
		cycle = 4,
		dominant_7th = True
	)

	received_chords = []

	def my_builder (p, chord):
		received_chords.append(chord)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert len(received_chords) == 1
	assert received_chords[0] is not None

	injected = received_chords[0]
	raw_chord = composition._harmonic_state.get_current_chord()

	# Injected chord should report the same name as the raw chord.
	assert injected.name() == raw_chord.name()

	# Injected chord should correctly transpose relative to the key of E (pc=4).
	# For the initial E major chord: offset = (4-4)%12 = 0, so root_midi(40) = 40.
	assert injected.root_midi(40) == 40


def test_chord_not_injected_without_parameter (monkeypatch: pytest.MonkeyPatch) -> None:

	"""
	Builder functions without a chord parameter should work without harmony.
	"""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")
	calls = []

	def my_builder (p):
		calls.append("called")

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert len(calls) == 1
