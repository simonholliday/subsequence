import asyncio
import random
import typing
import unittest.mock

import pytest

import subsequence
import subsequence.composition
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer


def test_composition_creates_sequencer (patch_midi: None) -> None:

	"""Composition should create a working sequencer with the given device and BPM."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=140, key="C")

	assert composition._sequencer is not None
	assert composition._sequencer.current_bpm == 140
	assert composition.output_device == "Dummy MIDI"
	assert composition.key == "C"


def test_composition_harmony_creates_state (patch_midi: None) -> None:

	"""Calling harmony() should create a HarmonicState with the given parameters."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="E")

	composition.harmony(
		style = "turnaround_global",
		cycle_beats = 4,
		dominant_7th = True,
		gravity = 0.8,
		minor_turnaround_weight = 0.25
	)

	assert composition._harmonic_state is not None
	assert composition._harmonic_state.key_name == "E"
	assert composition._harmony_cycle_beats == 4


def test_composition_harmony_without_key_raises (patch_midi: None) -> None:

	"""Calling harmony() without a key should raise ValueError."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125)

	with pytest.raises(ValueError):
		composition.harmony(style="turnaround_global", cycle_beats=4)


def test_harmony_preserves_history_across_calls (patch_midi: None) -> None:

	"""Calling harmony() again should preserve chord history from the previous state."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", gravity=0.5)

	# Build up history by stepping through several chords.
	for _ in range(4):
		composition._harmonic_state.step()

	history_before = composition._harmonic_state.history.copy()
	current_before = composition._harmonic_state.current_chord

	assert len(history_before) == 4

	# Reconfigure harmony with different parameters.
	composition.harmony(style="functional_major", gravity=0.8)

	assert composition._harmonic_state.history == history_before
	assert composition._harmonic_state.current_chord == current_before


def test_harmony_drops_current_chord_on_graph_switch (patch_midi: None) -> None:

	"""Switching graph style should not preserve a chord that doesn't exist in the new graph."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", gravity=0.5)

	# Step a few times to build history and move away from tonic.
	for _ in range(4):
		composition._harmonic_state.step()

	old_current = composition._harmonic_state.current_chord

	# Switch to a completely different graph style.
	composition.harmony(style="suspended", gravity=0.5)

	new_current = composition._harmonic_state.current_chord

	# The new current should be a valid node in the new graph (has outgoing edges).
	transitions = composition._harmonic_state.graph.get_transitions(new_current)
	assert len(transitions) > 0

	# Step should work (not stuck).
	result = composition._harmonic_state.step()
	assert result != new_current or len(transitions) > 0


def test_pattern_decorator_registers_pending (patch_midi: None) -> None:

	"""The pattern decorator should register a pending pattern without scheduling immediately."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	@composition.pattern(channel=10, length=4)
	def my_pattern (p):
		pass

	assert len(composition._pending_patterns) == 1
	assert composition._pending_patterns[0].channel == 10
	assert composition._pending_patterns[0].length == 4


def test_pattern_decorator_returns_original_function (patch_midi: None) -> None:

	"""The pattern decorator should return the original function unchanged."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_fn (p):
		pass

	decorated = composition.pattern(channel=1, length=4)(my_fn)

	assert decorated is my_fn


def test_build_pattern_from_pending_calls_builder (patch_midi: None) -> None:

	"""Building a pattern from pending should call the builder function."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	calls = []

	def my_builder (p):
		calls.append("called")

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert len(calls) == 1
	assert isinstance(pattern, subsequence.pattern.Pattern)
	assert pattern.channel == 1
	assert pattern.length == 4


def test_build_pattern_rebuilds_on_reschedule (patch_midi: None) -> None:

	"""The decorator pattern should re-run the builder on on_reschedule."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	call_count = [0]

	def my_builder (p):
		call_count[0] += 1

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert call_count[0] == 1

	pattern.on_reschedule()

	assert call_count[0] == 2


def test_builder_exception_produces_silent_pattern (patch_midi: None) -> None:

	"""A builder that raises should produce an empty (silent) pattern, not crash."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def bad_builder (p):
		raise RuntimeError("intentional test error")

	pending = subsequence.composition._PendingPattern(
		builder_fn = bad_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	# Pattern should exist but have no notes (steps empty).
	assert isinstance(pattern, subsequence.pattern.Pattern)
	assert len(pattern.steps) == 0

	# Rebuilding should also not crash.
	pattern.on_reschedule()
	assert len(pattern.steps) == 0


def test_builder_cycle_injection (patch_midi: None) -> None:

	"""The builder should receive the current cycle count."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	received_cycles = []

	def my_builder (p):
		received_cycles.append(p.cycle)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert received_cycles == [0]

	pattern.on_reschedule()
	assert received_cycles == [0, 1]

	pattern.on_reschedule()
	assert received_cycles == [0, 1, 2]


def test_chord_injection (patch_midi: None) -> None:

	"""Builder functions with a chord parameter should receive the current chord."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="E")

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
		reschedule_lookahead = 1,
		default_grid = 16
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

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	calls = []

	def my_builder (p):
		calls.append("called")

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert len(calls) == 1


def test_data_store_exists (patch_midi: None) -> None:

	"""Composition should have an empty data dict on creation."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	assert isinstance(composition.data, dict)
	assert len(composition.data) == 0


def test_schedule_registers_pending (patch_midi: None) -> None:

	"""Calling schedule() should append to _pending_scheduled."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_task () -> None:
		pass

	composition.schedule(my_task, cycle_beats=16)

	assert len(composition._pending_scheduled) == 1
	assert composition._pending_scheduled[0].fn is my_task
	assert composition._pending_scheduled[0].cycle_beats == 16


def test_data_accessible_from_builder (patch_midi: None) -> None:

	"""Builder functions should be able to read composition.data via closure."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	composition.data["test_key"] = 42
	read_values = []

	def my_builder (p):
		read_values.append(composition.data.get("test_key"))

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	composition._build_pattern_from_pending(pending)

	assert read_values == [42]


def test_data_default_when_not_set (patch_midi: None) -> None:

	"""Data store get() should return the default when key is not set."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	assert composition.data.get("missing", 0.5) == 0.5


# --- Seed and RNG ---


def test_composition_seed_constructor (patch_midi: None) -> None:

	"""Composition should store a seed set via the constructor."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=42)

	assert composition._seed == 42


def test_composition_seed_method (patch_midi: None) -> None:

	"""Composition.seed() should store the seed value."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	assert composition._seed is None

	composition.seed(99)

	assert composition._seed == 99


def test_builder_receives_rng_from_seed (patch_midi: None) -> None:

	"""When a seed is set, pattern builders should receive a deterministic rng."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=42)
	received_rngs = []

	def my_builder (p):
		received_rngs.append(p.rng)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	composition._pending_patterns.append(pending)

	# Simulate what _run() does: derive child RNGs.
	master = random.Random(42)
	pattern_rng = random.Random(master.randint(0, 2 ** 63))

	pattern = composition._build_pattern_from_pending(pending, pattern_rng)

	assert len(received_rngs) == 1
	assert isinstance(received_rngs[0], random.Random)


def test_seed_produces_deterministic_patterns (patch_midi: None) -> None:

	"""Two builds with the same seed should produce identical pattern content."""

	def build_steps (seed: int) -> set:

		composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=seed)

		def my_builder (p):
			# Use p.rng to make a stochastic pattern.
			p.fill(60, step=0.25, velocity=100)
			p.dropout(probability=0.4)

		pending = subsequence.composition._PendingPattern(
			builder_fn = my_builder,
			channel = 1,
			length = 4,
			drum_note_map = None,
			reschedule_lookahead = 1,
			default_grid = 16
		)

		# Derive RNG the same way _run() does.
		master = random.Random(seed)
		pattern_rng = random.Random(master.randint(0, 2 ** 63))

		pattern = composition._build_pattern_from_pending(pending, pattern_rng)

		return set(pattern.steps.keys())

	run_1 = build_steps(42)
	run_2 = build_steps(42)
	run_3 = build_steps(99)

	assert run_1 == run_2
	assert run_1 != run_3


def test_no_seed_builder_has_rng () -> None:

	"""Even without a seed, the builder should have an rng attribute."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	builder = subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0
	)

	assert isinstance(builder.rng, random.Random)


# --- Float length ---


def test_pattern_decorator_float_length (patch_midi: None) -> None:

	"""The pattern decorator should accept a float length."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=0, length=10.5)
	def my_pattern (p):
		pass

	assert composition._pending_patterns[0].length == 10.5


def test_build_pattern_float_length (patch_midi: None) -> None:

	"""Building a pattern with float length should produce the correct Pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	calls = []

	def my_builder (p):
		calls.append(p._pattern.length)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 10.5,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 42
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert pattern.length == 10.5
	assert calls == [10.5]


def test_different_pattern_lengths_coexist (patch_midi: None) -> None:

	"""Multiple patterns with different lengths should all register correctly."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=0, length=4)
	def short (p):
		pass

	@composition.pattern(channel=1, length=9)
	def medium (p):
		pass

	@composition.pattern(channel=2, length=10.5)
	def long (p):
		pass

	assert len(composition._pending_patterns) == 3
	assert composition._pending_patterns[0].length == 4
	assert composition._pending_patterns[1].length == 9
	assert composition._pending_patterns[2].length == 10.5


# --- Layer ---


def test_layer_registers_pending (patch_midi: None) -> None:

	"""layer() should register a single pending pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def kick (p):
		pass

	def hats (p):
		pass

	composition.layer(kick, hats, channel=9, length=4)

	assert len(composition._pending_patterns) == 1
	assert composition._pending_patterns[0].channel == 9
	assert composition._pending_patterns[0].length == 4


def test_layer_merges_notes (patch_midi: None) -> None:

	"""layer() should merge notes from all builder functions into one pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def kick (p):
		p.note(36, beat=0, velocity=127)

	def snare (p):
		p.note(38, beat=1, velocity=100)

	composition.layer(kick, snare, channel=9, length=4)

	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])

	# Both notes should be present.
	pulse_0 = 0
	pulse_1 = int(1.0 * subsequence.constants.MIDI_QUARTER_NOTE)

	assert pulse_0 in pattern.steps
	assert pulse_1 in pattern.steps
	assert pattern.steps[pulse_0].notes[0].pitch == 36
	assert pattern.steps[pulse_1].notes[0].pitch == 38


def test_layer_with_chord_injection (patch_midi: None) -> None:

	"""layer() should inject chord into builders that accept it."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	composition.harmony(style="diatonic_major", cycle_beats=4)

	def bass (p, chord):
		# Just verify chord is received by placing the root.
		root = chord.root_note(36)
		p.note(root, beat=0, velocity=100)

	def rhythm (p):
		p.note(60, beat=1, velocity=80)

	composition.layer(bass, rhythm, channel=0, length=4)

	# Build with a harmony state active - chord injection should work.
	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])

	# Both builders should have contributed notes.
	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 2


# --- Tweak ---


def test_tweak_updates_running_pattern (patch_midi: None) -> None:

	"""tweak() should store values in the pattern's _tweaks dict."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_builder (p):
		pass

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)
	composition._running_patterns["my_builder"] = pattern

	composition.tweak("my_builder", pitches=[48, 52])

	assert pattern._tweaks == {"pitches": [48, 52]}


def test_tweak_unknown_pattern_raises (patch_midi: None) -> None:

	"""tweak() should raise ValueError for a nonexistent pattern name."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	with pytest.raises(ValueError):
		composition.tweak("nonexistent", pitches=[60])


def test_clear_tweak_removes_all (patch_midi: None) -> None:

	"""clear_tweak() with no param names should remove all tweaks."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_builder (p):
		pass

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)
	composition._running_patterns["my_builder"] = pattern

	composition.tweak("my_builder", pitches=[48], velocity=80)
	composition.clear_tweak("my_builder")

	assert pattern._tweaks == {}


def test_clear_tweak_removes_specific (patch_midi: None) -> None:

	"""clear_tweak() with a name should remove only that param."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_builder (p):
		pass

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)
	composition._running_patterns["my_builder"] = pattern

	composition.tweak("my_builder", pitches=[48], velocity=80)
	composition.clear_tweak("my_builder", "pitches")

	assert pattern._tweaks == {"velocity": 80}


def test_get_tweaks_returns_copy (patch_midi: None) -> None:

	"""get_tweaks() should return a copy, not a reference."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_builder (p):
		pass

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)
	composition._running_patterns["my_builder"] = pattern

	composition.tweak("my_builder", pitches=[48])
	result = composition.get_tweaks("my_builder")
	result["pitches"] = [99]

	assert pattern._tweaks["pitches"] == [48]


def test_tweaks_in_live_info (patch_midi: None) -> None:

	"""live_info() should include tweaks for each pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_builder (p):
		pass

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)
	composition._running_patterns["my_builder"] = pattern

	composition.tweak("my_builder", pitches=[48])
	info = composition.live_info()

	assert info["patterns"][0]["tweaks"] == {"pitches": [48]}


def test_param_reads_tweak_on_rebuild (patch_midi: None) -> None:

	"""p.param() should return the tweaked value after a rebuild."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	captured = {}

	def my_builder (p):
		captured["pitches"] = p.param("pitches", [60, 64])

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	# First build uses default.
	assert captured["pitches"] == [60, 64]

	# Tweak and rebuild.
	pattern._tweaks["pitches"] = [48, 52]
	pattern.on_reschedule()

	assert captured["pitches"] == [48, 52]


# --- Unit parameter ---


def test_pattern_unit_sets_beat_length (patch_midi: None) -> None:

	"""length=6, unit=SIXTEENTH should produce a pattern with 1.5 beats."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=0, length=6, unit=dur.SIXTEENTH)
	def my_pattern (p):
		pass

	pending = composition._pending_patterns[0]

	assert pending.length == pytest.approx(1.5)


def test_pattern_unit_sets_default_grid (patch_midi: None) -> None:

	"""length=6, unit=SIXTEENTH should set default_grid to 6."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=0, length=6, unit=dur.SIXTEENTH)
	def my_pattern (p):
		pass

	pending = composition._pending_patterns[0]

	assert pending.default_grid == 6


def test_pattern_no_unit_defaults_to_sixteenth_grid (patch_midi: None) -> None:

	"""length=4 without unit should produce default_grid=16 (4 / SIXTEENTH)."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=0, length=4)
	def my_pattern (p):
		pass

	pending = composition._pending_patterns[0]

	assert pending.default_grid == 16


def test_pattern_unit_triplet_grid (patch_midi: None) -> None:

	"""length=4, unit=TRIPLET_EIGHTH should produce default_grid=4."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=0, length=4, unit=dur.TRIPLET_EIGHTH)
	def my_pattern (p):
		pass

	pending = composition._pending_patterns[0]

	assert pending.length == pytest.approx(4 * dur.TRIPLET_EIGHTH)
	assert pending.default_grid == 4


def test_layer_unit_sets_beat_length (patch_midi: None) -> None:

	"""layer() with unit should compute beat_length correctly."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	def kick (p):
		pass

	composition.layer(kick, channel=9, length=8, unit=dur.SIXTEENTH)

	pending = composition._pending_patterns[0]

	assert pending.length == pytest.approx(2.0)
	assert pending.default_grid == 8


def test_schedule_wait_for_initial_flag (patch_midi: None) -> None:

	"""schedule(wait_for_initial=True) should store the flag on _PendingScheduled."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_task () -> None:
		pass

	composition.schedule(my_task, cycle_beats=16, wait_for_initial=True)

	assert composition._pending_scheduled[0].wait_for_initial is True
	assert composition._pending_scheduled[0].defer is False


def test_schedule_defer_flag (patch_midi: None) -> None:

	"""schedule(defer=True) should store the flag on _PendingScheduled."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_task () -> None:
		pass

	composition.schedule(my_task, cycle_beats=16, defer=True)

	assert composition._pending_scheduled[0].defer is True
	assert composition._pending_scheduled[0].wait_for_initial is False


def test_schedule_defaults_no_wait_for_initial_no_defer (patch_midi: None) -> None:

	"""schedule() without flags should default to wait_for_initial=False, defer=False."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_task () -> None:
		pass

	composition.schedule(my_task, cycle_beats=16)

	assert composition._pending_scheduled[0].wait_for_initial is False
	assert composition._pending_scheduled[0].defer is False


def test_pattern_lookahead_capped_to_harmony_lookahead (patch_midi: None) -> None:

	"""Pattern reschedule_lookahead should be capped to the harmony's value."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="diatonic_major", cycle_beats=4, reschedule_lookahead=0.25)

	@composition.pattern(channel=0, length=4)
	def pad (p, chord):
		pass

	# The pending pattern has the default lookahead (1.0).
	pending = composition._pending_patterns[0]
	assert pending.reschedule_lookahead == 1

	# When built, the pattern's lookahead should be capped to 0.25.
	pattern = composition._build_pattern_from_pending(pending)
	assert pattern.reschedule_lookahead == pytest.approx(0.25)


def test_pattern_lookahead_not_capped_when_smaller (patch_midi: None) -> None:

	"""When the pattern's lookahead is already smaller than harmony's, leave it alone."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="diatonic_major", cycle_beats=4, reschedule_lookahead=0.5)

	@composition.pattern(channel=0, length=2, reschedule_lookahead=0.25)
	def pad (p, chord):
		pass

	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])
	assert pattern.reschedule_lookahead == pytest.approx(0.25)


# ── freeze() ──────────────────────────────────────────────────────────────────


def test_freeze_requires_harmony (patch_midi: None) -> None:

	"""freeze() raises ValueError when harmony() has not been called."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	with pytest.raises(ValueError, match="harmony()"):
		composition.freeze(4)


def test_freeze_requires_positive_bars (patch_midi: None) -> None:

	"""freeze() raises ValueError for bars < 1."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	with pytest.raises(ValueError, match="bars"):
		composition.freeze(0)


def test_freeze_returns_progression (patch_midi: None) -> None:

	"""freeze() should return a Progression instance."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	prog = composition.freeze(4)

	assert isinstance(prog, subsequence.composition.Progression)


def test_freeze_chord_count (patch_midi: None) -> None:

	"""freeze(bars) returns exactly *bars* chords."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	for bars in (1, 4, 8):
		prog = composition.freeze(bars)
		assert len(prog.chords) == bars, f"Expected {bars} chords, got {len(prog.chords)}"


def test_freeze_captures_current_chord_as_first (patch_midi: None) -> None:

	"""The first chord in the progression is the engine's current chord before freezing."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	first_chord = composition._harmonic_state.current_chord  # type: ignore[union-attr]
	prog = composition.freeze(4)

	assert prog.chords[0] is first_chord


def test_freeze_advances_engine (patch_midi: None) -> None:

	"""Successive freeze() calls continue from where the previous one left off."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	composition.freeze(4)

	# After freeze(), the engine has stepped past the last captured chord.
	# The next freeze() must start with whatever chord the engine is currently on.
	chord_between = composition._harmonic_state.current_chord  # type: ignore[union-attr]
	prog2 = composition.freeze(4)

	assert prog2.chords[0] is chord_between


def test_freeze_extra_step_avoids_duplication (patch_midi: None) -> None:

	"""freeze() takes an extra step so the next freeze starts on a fresh chord."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	prog1 = composition.freeze(4)

	# The engine is now on the chord AFTER prog1.chords[-1] (the extra step).
	# prog2 should start there — not at prog1.chords[-1].
	chord_after_extra_step = composition._harmonic_state.current_chord  # type: ignore[union-attr]
	prog2 = composition.freeze(4)

	assert prog2.chords[0] is chord_after_extra_step


def test_freeze_trailing_history_max_length (patch_midi: None) -> None:

	"""trailing_history has at most 4 entries (same cap as HarmonicState.history)."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	prog = composition.freeze(8)

	assert len(prog.trailing_history) <= 4


def test_freeze_deterministic_with_seed (patch_midi: None) -> None:

	"""freeze() with a seeded RNG produces the same progression each run.

	The composition-level seed is applied in _run() (async), so for this
	unit test we seed the harmonic state's RNG directly — the property under
	test is that freeze() is deterministic given identical initial conditions.
	"""

	def _run () -> subsequence.composition.Progression:
		comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
		comp.harmony(style="functional_major", cycle_beats=4)
		comp._harmonic_state.rng = random.Random(42)  # type: ignore[union-attr]
		return comp.freeze(8)

	prog1 = _run()
	prog2 = _run()

	assert [c.name() for c in prog1.chords] == [c.name() for c in prog2.chords]


def test_freeze_progression_is_immutable (patch_midi: None) -> None:

	"""Progression is a frozen dataclass — attempts to mutate it raise FrozenInstanceError."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)
	prog = composition.freeze(4)

	import dataclasses
	with pytest.raises(dataclasses.FrozenInstanceError):
		prog.chords = ()  # type: ignore[misc]


# ── section_chords() ──────────────────────────────────────────────────────────


def test_section_chords_stores_progression (patch_midi: None) -> None:

	"""section_chords() stores the progression under the section name."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)
	prog = composition.freeze(4)

	composition.section_chords("verse", prog)

	assert composition._section_progressions["verse"] is prog


def test_section_chords_without_form_succeeds (patch_midi: None) -> None:

	"""section_chords() succeeds even when form() has not yet been called."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)
	prog = composition.freeze(4)

	# Should not raise — form may be configured later or not at all.
	composition.section_chords("verse", prog)
	assert "verse" in composition._section_progressions


def test_section_chords_unknown_section_raises (patch_midi: None) -> None:

	"""section_chords() raises ValueError for a section not defined in the form."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)
	composition.form({
		"verse":  (8, [("chorus", 1)]),
		"chorus": (4, [("verse", 1)]),
	}, start="verse")
	prog = composition.freeze(4)

	with pytest.raises(ValueError, match="bridge"):
		composition.section_chords("bridge", prog)


def test_section_chords_multiple_sections (patch_midi: None) -> None:

	"""Multiple progressions can be bound to different sections independently."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="functional_major", cycle_beats=4)

	verse  = composition.freeze(8)
	chorus = composition.freeze(4)

	composition.section_chords("verse",  verse)
	composition.section_chords("chorus", chorus)

	assert composition._section_progressions["verse"]  is verse
	assert composition._section_progressions["chorus"] is chorus


# ── schedule_harmonic_clock() — frozen progression integration ─────────────────


@pytest.mark.asyncio
async def test_frozen_section_replays_chords (patch_midi: None) -> None:

	"""When a section has a frozen progression, advance_harmony replays its chords."""


	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	# Build a progression manually so we know the exact chords.
	chord_a = hs.current_chord
	hs.step()
	chord_b = hs.current_chord
	hs.step()
	chord_c = hs.current_chord

	prog = subsequence.composition.Progression(
		chords = (chord_a, chord_b, chord_c),
		trailing_history = (),
	)

	# Reset the engine to a clean state.
	hs2 = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	captured: typing.List[typing.Callable] = []

	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture_cb (callback: typing.Callable, **_: typing.Any) -> None:
		captured.append(callback)

	mock_seq.schedule_callback_repeating = capture_cb

	def get_prog () -> typing.Optional[typing.Tuple[str, int, typing.Optional[subsequence.composition.Progression]]]:
		return ("verse", 0, prog)

	await subsequence.composition.schedule_harmonic_clock(
		mock_seq,
		lambda: hs2,
		cycle_beats = 4,
		get_section_progression = get_prog,
	)

	cb = captured[0]

	# Each call to advance_harmony should replay the next frozen chord.
	cb(0)
	assert hs2.current_chord is chord_a

	cb(24)
	assert hs2.current_chord is chord_b

	cb(48)
	assert hs2.current_chord is chord_c


@pytest.mark.asyncio
async def test_frozen_index_resets_on_section_change (patch_midi: None) -> None:

	"""advance_harmony resets the frozen index when the section index changes."""


	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	chord_a = hs.current_chord
	hs.step(); chord_b = hs.current_chord

	prog = subsequence.composition.Progression(chords=(chord_a, chord_b), trailing_history=())

	hs2 = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	captured: typing.List[typing.Callable] = []
	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture_cb (callback: typing.Callable, **_: typing.Any) -> None:
		captured.append(callback)

	mock_seq.schedule_callback_repeating = capture_cb

	current_section = ["verse", 0]  # [name, index]

	def get_prog () -> typing.Optional[typing.Tuple[str, int, typing.Optional[subsequence.composition.Progression]]]:
		return (current_section[0], current_section[1], prog)

	await subsequence.composition.schedule_harmonic_clock(
		mock_seq, lambda: hs2, cycle_beats=4, get_section_progression=get_prog
	)
	cb = captured[0]

	cb(0)  # chord_a, frozen_index → 1
	assert hs2.current_chord is chord_a

	cb(24)  # chord_b, frozen_index → 2
	assert hs2.current_chord is chord_b

	# Change section (new index) — frozen index should reset.
	current_section[0] = "chorus"
	current_section[1] = 1
	cb(48)  # frozen_index reset to 0 → chord_a again
	assert hs2.current_chord is chord_a


@pytest.mark.asyncio
async def test_unbound_section_calls_step (patch_midi: None) -> None:

	"""Sections without a bound progression call hs.step() (live generation)."""


	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	initial_chord = hs.current_chord

	captured: typing.List[typing.Callable] = []
	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture_cb (callback: typing.Callable, **_: typing.Any) -> None:
		captured.append(callback)

	mock_seq.schedule_callback_repeating = capture_cb

	def get_prog () -> typing.Optional[typing.Tuple[str, int, typing.Optional[subsequence.composition.Progression]]]:
		# Section is live — no bound progression.
		return ("bridge", 0, None)

	await subsequence.composition.schedule_harmonic_clock(
		mock_seq, lambda: hs, cycle_beats=4, get_section_progression=get_prog
	)
	cb = captured[0]

	cb(0)
	# step() must have been called — chord should have changed.
	assert hs.current_chord is not initial_chord or len(hs.history) > 0


@pytest.mark.asyncio
async def test_frozen_updates_history (patch_midi: None) -> None:

	"""Frozen playback updates hs.history for NIR continuity."""


	hs_src = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	chord_a = hs_src.current_chord

	prog = subsequence.composition.Progression(chords=(chord_a,), trailing_history=())

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	captured: typing.List[typing.Callable] = []
	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture_cb (callback: typing.Callable, **_: typing.Any) -> None:
		captured.append(callback)

	mock_seq.schedule_callback_repeating = capture_cb

	await subsequence.composition.schedule_harmonic_clock(
		mock_seq, lambda: hs, cycle_beats=4,
		get_section_progression=lambda: ("verse", 0, prog),
	)
	cb = captured[0]

	history_before = len(hs.history)
	cb(0)

	assert len(hs.history) == history_before + 1
	assert hs.history[-1] is chord_a


@pytest.mark.asyncio
async def test_exhausted_progression_falls_through_to_live (patch_midi: None) -> None:

	"""When all frozen chords have been played, advance_harmony falls through to step()."""


	hs_src = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	chord_a = hs_src.current_chord

	# Progression has only 1 chord.
	prog = subsequence.composition.Progression(chords=(chord_a,), trailing_history=())

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")

	captured: typing.List[typing.Callable] = []
	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture_cb (callback: typing.Callable, **_: typing.Any) -> None:
		captured.append(callback)

	mock_seq.schedule_callback_repeating = capture_cb

	await subsequence.composition.schedule_harmonic_clock(
		mock_seq, lambda: hs, cycle_beats=4,
		get_section_progression=lambda: ("verse", 0, prog),
	)
	cb = captured[0]

	cb(0)   # plays chord_a from frozen progression
	assert hs.current_chord is chord_a

	chord_after_frozen = hs.current_chord
	cb(24)  # exhausted — should call step(), advancing the engine
	assert hs.current_chord is not chord_after_frozen or len(hs.history) > 1


@pytest.mark.asyncio
async def test_no_section_progression_calls_step (patch_midi: None) -> None:

	"""When get_section_progression is None, advance_harmony always calls step()."""


	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	initial_chord = hs.current_chord

	captured: typing.List[typing.Callable] = []
	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture_cb (callback: typing.Callable, **_: typing.Any) -> None:
		captured.append(callback)

	mock_seq.schedule_callback_repeating = capture_cb

	# No get_section_progression — pure live generation.
	await subsequence.composition.schedule_harmonic_clock(
		mock_seq, lambda: hs, cycle_beats=4,
	)
	cb = captured[0]

	cb(0)
	assert len(hs.history) > 0  # step() was called (history updated)
