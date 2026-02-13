import pytest

import subsequence
import subsequence.composition
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer


def test_composition_creates_sequencer (patch_midi: None) -> None:

	"""Composition should create a working sequencer with the given device and BPM."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=140, key="C")

	assert composition._sequencer is not None
	assert composition._sequencer.current_bpm == 140
	assert composition.device == "Dummy MIDI"
	assert composition.key == "C"


def test_composition_harmony_creates_state (patch_midi: None) -> None:

	"""Calling harmony() should create a HarmonicState with the given parameters."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="E")

	composition.harmony(
		style = "turnaround_global",
		cycle_beats = 4,
		dominant_7th = True,
		gravity = 0.8,
		minor_weight = 0.25
	)

	assert composition._harmonic_state is not None
	assert composition._harmonic_state.key_name == "E"
	assert composition._harmony_cycle_beats == 4


def test_composition_harmony_without_key_raises (patch_midi: None) -> None:

	"""Calling harmony() without a key should raise ValueError."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125)

	with pytest.raises(ValueError):
		composition.harmony(style="turnaround_global", cycle_beats=4)


def test_pattern_decorator_registers_pending (patch_midi: None) -> None:

	"""The pattern decorator should register a pending pattern without scheduling immediately."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	@composition.pattern(channel=10, length=4)
	def my_pattern (p):
		pass

	assert len(composition._pending_patterns) == 1
	assert composition._pending_patterns[0].channel == 10
	assert composition._pending_patterns[0].length == 4


def test_pattern_decorator_returns_original_function (patch_midi: None) -> None:

	"""The pattern decorator should return the original function unchanged."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	def my_fn (p):
		pass

	decorated = composition.pattern(channel=1, length=4)(my_fn)

	assert decorated is my_fn


def test_build_pattern_from_pending_calls_builder (patch_midi: None) -> None:

	"""Building a pattern from pending should call the builder function."""

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


def test_build_pattern_rebuilds_on_reschedule (patch_midi: None) -> None:

	"""The decorator pattern should re-run the builder on on_reschedule."""

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


def test_builder_cycle_injection (patch_midi: None) -> None:

	"""The builder should receive the current cycle count."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")
	received_cycles = []

	def my_builder (p):
		received_cycles.append(p.cycle)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert received_cycles == [0]

	pattern.on_reschedule()
	assert received_cycles == [0, 1]

	pattern.on_reschedule()
	assert received_cycles == [0, 1, 2]


def test_chord_injection (patch_midi: None) -> None:

	"""Builder functions with a chord parameter should receive the current chord."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="E")

	composition.harmony(
		style = "turnaround_global",
		cycle_beats = 4,
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


def test_chord_not_injected_without_parameter (patch_midi: None) -> None:

	"""Builder functions without a chord parameter should work without harmony."""

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


def test_data_store_exists (patch_midi: None) -> None:

	"""Composition should have an empty data dict on creation."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	assert isinstance(composition.data, dict)
	assert len(composition.data) == 0


def test_schedule_registers_pending (patch_midi: None) -> None:

	"""Calling schedule() should append to _pending_scheduled."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	def my_task () -> None:
		pass

	composition.schedule(my_task, cycle_beats=16)

	assert len(composition._pending_scheduled) == 1
	assert composition._pending_scheduled[0].fn is my_task
	assert composition._pending_scheduled[0].cycle_beats == 16


def test_data_accessible_from_builder (patch_midi: None) -> None:

	"""Builder functions should be able to read composition.data via closure."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")
	composition.data["test_key"] = 42
	read_values = []

	def my_builder (p):
		read_values.append(composition.data.get("test_key"))

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1
	)

	composition._build_pattern_from_pending(pending)

	assert read_values == [42]


def test_data_default_when_not_set (patch_midi: None) -> None:

	"""Data store get() should return the default when key is not set."""

	composition = subsequence.Composition(device="Dummy MIDI", bpm=125, key="C")

	assert composition.data.get("missing", 0.5) == 0.5
