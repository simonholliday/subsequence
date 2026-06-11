import asyncio
import random
import typing
import unittest.mock

import pytest

import subsequence
import subsequence.chords
import subsequence.composition
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer
import subsequence.voicings


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

	# Step should work (not stuck) — it returns a usable chord.
	result = composition._harmonic_state.step()
	assert result is not None


def test_pattern_decorator_registers_pending (patch_midi: None) -> None:

	"""The pattern decorator should register a pending pattern without scheduling immediately."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	@composition.pattern(channel=10, beats=4)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert len(composition._pending_patterns) == 1
	assert composition._pending_patterns[0].channel == 9  # 10 - 1, 1-indexed default
	assert composition._pending_patterns[0].length == 4


def test_pattern_decorator_returns_original_function (patch_midi: None) -> None:

	"""The pattern decorator should return the original function unchanged."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_fn (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	decorated = composition.pattern(channel=1, beats=4)(my_fn)

	assert decorated is my_fn


def test_build_pattern_from_pending_calls_builder (patch_midi: None) -> None:

	"""Building a pattern from pending should call the builder function."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	calls = []

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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


def test_drone_raw_events_do_not_accumulate_across_cycles (patch_midi: None) -> None:

	"""An unconditional drone must place exactly one raw note_on per cycle.

	Regression: ``_rebuild()`` clears ``steps``/``cc_events``/``osc_events`` each
	cycle, but ``raw_note_events`` was omitted — so drones (and ``note_on`` /
	``note_off``) accumulated and re-fired on every reschedule instead of once.
	"""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def drone_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		p.drone(60)

	pending = subsequence.composition._PendingPattern(
		builder_fn = drone_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)

	assert len(pattern.raw_note_events) == 1

	# Five reschedules must not grow the buffer — one drone per cycle, not six.
	for _ in range(5):
		pattern.on_reschedule()
		assert len(pattern.raw_note_events) == 1


def test_builder_exception_produces_silent_pattern (patch_midi: None) -> None:

	"""A builder that raises should produce an empty (silent) pattern, not crash."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def bad_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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


def test_injected_chord_tones_truncates_count_under_voice_leading () -> None:

	"""_InjectedChord.tones(count=N) yields exactly N notes even with voice leading.

	Regression: under voice leading, count < chord size returned the full voiced
	chord instead of truncating to count (the non-voice-led path always honoured count).
	"""

	chord = subsequence.chords.Chord(0, "major")           # 3 tones
	vl_state = subsequence.voicings.VoiceLeadingState()
	injected = subsequence.composition._InjectedChord(chord, vl_state)

	assert len(injected.tones(60, count=2)) == 2           # truncates (previously returned 3)
	assert len(injected.tones(60, count=3)) == 3
	assert len(injected.tones(60, count=6)) == 6           # cycles up into octaves


def test_builder_cycle_injection (patch_midi: None) -> None:

	"""The builder should receive the current cycle count."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	received_cycles = []

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder", chord: "subsequence.chords.Chord") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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


def test_p_data_is_composition_data (patch_midi: None) -> None:

	"""p.data inside a pattern builder should be the same object as composition.data."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")
	composition.data["sentinel"] = "hello"
	captured = []

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		captured.append(p.data.get("sentinel"))
		p.data["from_pattern"] = "world"

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	composition._build_pattern_from_pending(pending)

	assert captured == ["hello"]
	assert composition.data.get("from_pattern") == "world"


# --- Seed and RNG ---


def test_composition_seed_constructor (patch_midi: None) -> None:

	"""Composition should store a seed set via the constructor."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=42)

	assert composition._seed == 42


def test_composition_seed_property (patch_midi: None) -> None:

	"""Composition.seed is a readable/assignable property; the old call form raises."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	assert composition.seed is None

	composition.seed = 99

	assert composition.seed == 99
	assert composition._seed == 99

	with pytest.raises(TypeError):
		composition.seed(42)  # type: ignore[operator]  # hard break: formerly a method


def test_builder_receives_rng_from_seed (patch_midi: None) -> None:

	"""When a seed is set, pattern builders should receive a deterministic rng."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=42)
	received_rngs = []

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	# Streams are dealt inside _build_pattern_from_pending, keyed by name.
	pattern = composition._build_pattern_from_pending(pending)

	assert len(received_rngs) == 1
	assert isinstance(received_rngs[0], random.Random)


def test_seed_produces_deterministic_patterns (patch_midi: None) -> None:

	"""Two builds with the same seed should produce identical pattern content."""

	def build_steps (seed: int) -> set:

		composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, seed=seed)

		def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			# Use p.rng to make a stochastic pattern.
			p.repeat(60, spacing=0.25, velocity=100)
			p.dropout(probability=0.4)

		pending = subsequence.composition._PendingPattern(
			builder_fn = my_builder,
			channel = 1,
			length = 4,
			drum_note_map = None,
			reschedule_lookahead = 1,
			default_grid = 16
		)

		# Streams are dealt inside _build_pattern_from_pending, keyed by name.
		pattern = composition._build_pattern_from_pending(pending)

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

	@composition.pattern(channel=1, beats=10.5)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert composition._pending_patterns[0].length == 10.5


def test_build_pattern_float_length (patch_midi: None) -> None:

	"""Building a pattern with float length should produce the correct Pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	calls = []

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	@composition.pattern(channel=1, beats=4)
	def short (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	@composition.pattern(channel=1, beats=9)
	def medium (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	@composition.pattern(channel=2, beats=10.5)
	def long (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert len(composition._pending_patterns) == 3
	assert composition._pending_patterns[0].length == 4
	assert composition._pending_patterns[1].length == 9
	assert composition._pending_patterns[2].length == 10.5


# --- Layer ---


def test_layer_registers_pending (patch_midi: None) -> None:

	"""layer() should register a single pending pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def kick (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	def hats (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	composition.layer(kick, hats, channel=10, beats=4)

	assert len(composition._pending_patterns) == 1
	assert composition._pending_patterns[0].channel == 9  # 10 - 1, 1-indexed default
	assert composition._pending_patterns[0].length == 4


def test_layer_merges_notes (patch_midi: None) -> None:

	"""layer() should merge notes from all builder functions into one pattern."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def kick (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		p.note(36, beat=0, velocity=127)

	def snare (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		p.note(38, beat=1, velocity=100)

	composition.layer(kick, snare, channel=10, beats=4)

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

	def bass (p: "subsequence.pattern_builder.PatternBuilder", chord: "subsequence.chords.Chord") -> None:
		# Just verify chord is received by placing the root.
		root = chord.root_note(36)
		p.note(root, beat=0, velocity=100)

	def rhythm (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		p.note(60, beat=1, velocity=80)

	composition.layer(bass, rhythm, channel=1, beats=4)

	# Build with a harmony state active - chord injection should work.
	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])

	# Both builders should have contributed notes.
	total_notes = sum(len(step.notes) for step in pattern.steps.values())

	assert total_notes == 2


# --- Tweak ---


def test_tweak_updates_running_pattern (patch_midi: None) -> None:

	"""tweak() should store values in the pattern's _tweaks dict."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
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

	"""beats=6, step_duration=SIXTEENTH should produce a pattern with 1.5 beats."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, steps=6, step_duration=dur.SIXTEENTH)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	pending = composition._pending_patterns[0]

	assert pending.length == pytest.approx(1.5)


def test_pattern_unit_sets_default_grid (patch_midi: None) -> None:

	"""beats=6, step_duration=SIXTEENTH should set default_grid to 6."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, steps=6, step_duration=dur.SIXTEENTH)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	pending = composition._pending_patterns[0]

	assert pending.default_grid == 6


def test_pattern_no_unit_defaults_to_sixteenth_grid (patch_midi: None) -> None:

	"""beats=4 without unit should produce default_grid=16 (4 / SIXTEENTH)."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, beats=4)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	pending = composition._pending_patterns[0]

	assert pending.default_grid == 16


def test_pattern_unit_triplet_grid (patch_midi: None) -> None:

	"""beats=4, step_duration=TRIPLET_EIGHTH should produce default_grid=4."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, steps=4, step_duration=dur.TRIPLET_EIGHTH)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	pending = composition._pending_patterns[0]

	assert pending.length == pytest.approx(4 * dur.TRIPLET_EIGHTH)
	assert pending.default_grid == 4


def test_layer_unit_sets_beat_length (patch_midi: None) -> None:

	"""layer() with unit should compute beat_length correctly."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	def kick (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	composition.layer(kick, channel=10, steps=8, step_duration=dur.SIXTEENTH)

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


def test_pattern_lookahead_is_never_clamped (patch_midi: None) -> None:

	"""Patterns keep their own lookahead — the CLOCKS are raised to match instead.

	The old behaviour clamped every pattern to the harmony lookahead
	(punishing a pattern that legitimately needs more); the fix raises the
	form/harmony clocks to the maximum pattern lookahead at _run() time, so
	the harmony window always covers a pattern's next cycle when it rebuilds.
	"""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.harmony(style="diatonic_major", cycle_beats=4, reschedule_lookahead=0.25)

	@composition.pattern(channel=1, beats=4, reschedule_lookahead=2)
	def pad (p: "subsequence.pattern_builder.PatternBuilder", chord: "subsequence.chords.Chord") -> None:
		pass

	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])
	assert pattern.reschedule_lookahead == pytest.approx(2)


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


# ── schedule_harmonic_clock() — the span-walking clock and the harmony window ──


def _progression_of (*names: str, beats: float = 4.0) -> subsequence.progressions.Progression:

	"""A concrete progression from chord names, equal spans."""

	return subsequence.progressions.progression(list(names), beats=beats)


async def _capture_clock (**kwargs: typing.Any) -> typing.Tuple[typing.Callable[[int], typing.Optional[float]], "subsequence.composition._HarmonyHorizon", typing.Optional[float]]:

	"""Schedule the clock against a mock sequencer; return (callback, horizon, first_interval_beats).

	The clock populates the window for beat 0 synchronously at schedule time,
	then registers a callback sequence — we capture it and drive it by hand.
	"""

	captured: typing.Dict[str, typing.Any] = {}

	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture (callback: typing.Callable, start_pulse: int = 0, reschedule_lookahead: float = 1) -> None:
		captured["callback"] = callback
		captured["start_pulse"] = start_pulse

	mock_seq.schedule_callback_sequence = capture

	horizon = kwargs.pop("horizon", None) or subsequence.composition._HarmonyHorizon()

	await subsequence.composition.schedule_harmonic_clock(
		sequencer = mock_seq,
		horizon = horizon,
		bar_beats = 4.0,
		**kwargs,
	)

	first_interval = captured["start_pulse"] / 24 if "callback" in captured else None

	return captured.get("callback"), horizon, first_interval


@pytest.mark.asyncio
async def test_section_progression_walks_spans (patch_midi: None) -> None:

	"""A bound section progression's chords sound span by span, from beat 0."""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	prog = _progression_of("Am", "F", "C")

	cb, horizon, first = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
		get_section_progression = lambda: ("verse", 0, prog),
	)

	# Beat 0 was populated at schedule time: the section's FIRST chord sounds
	# at the section's first beat (no tonic placeholder bar).
	assert hs.current_chord.name() == "Am"
	assert horizon.chord_at(0.0).name() == "Am"
	assert first == 4.0

	assert cb(4 * 24) is not None
	assert hs.current_chord.name() == "F"
	assert horizon.chord_at(4.0).name() == "F"

	cb(8 * 24)
	assert hs.current_chord.name() == "C"


@pytest.mark.asyncio
async def test_section_change_restarts_the_progression (patch_midi: None) -> None:

	"""A new section index restarts the bound progression at that boundary."""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	prog = _progression_of("Am", "F")
	current_section = ["verse", 0]

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
		get_section_progression = lambda: (current_section[0], current_section[1], prog),
	)

	cb(4 * 24)
	assert hs.current_chord.name() == "F"

	# Re-entry (verse → verse) bumps the index — the walk restarts.
	current_section[1] = 1
	cb(8 * 24)
	assert hs.current_chord.name() == "Am"


@pytest.mark.asyncio
async def test_unbound_section_steps_live_with_planned_window (patch_midi: None) -> None:

	"""Sections without a progression step the live engine; the window holds [current, next]."""

	hs = subsequence.harmonic_state.HarmonicState(
		key_name="C", graph_style="functional_major", rng=random.Random(7)
	)
	tonic = hs.current_chord

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
		get_section_progression = lambda: ("bridge", 0, None),
	)

	# Beat 0 sounds the tonic (no step at start), and one step is pre-committed.
	assert hs.current_chord is tonic
	assert horizon.chord_at(0.0) is tonic
	planned = horizon.chord_at(4.0)
	assert planned is not None

	# At the boundary the planned chord commits — the window told the truth.
	cb(4 * 24)
	assert hs.current_chord is planned
	assert len(hs.history) == 1 and hs.history[-1] is tonic


@pytest.mark.asyncio
async def test_section_replay_restores_trailing_history (patch_midi: None) -> None:

	"""Entering a section with trailing_history restores the frozen NIR context."""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	context_chord = subsequence.chords.parse_chord("G")

	prog = subsequence.progressions.Progression(
		spans = (subsequence.progressions.ChordSpan(chord=subsequence.chords.parse_chord("Am"), beats=4.0),),
		trailing_history = (context_chord,),
	)

	cb, _, _ = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
		get_section_progression = lambda: ("verse", 0, prog),
	)

	# The schedule-time beat-0 fire entered the section and restored history
	# before walking, then the replay commit recorded the outgoing chord.
	assert context_chord in hs.history


@pytest.mark.asyncio
async def test_exhausted_section_falls_through_to_live_with_style (patch_midi: None) -> None:

	"""With a live engine configured, an exhausted section progression falls through to stepping."""

	hs = subsequence.harmonic_state.HarmonicState(
		key_name="C", graph_style="functional_major", rng=random.Random(3)
	)
	prog = _progression_of("Am")

	cb, _, _ = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
		get_section_progression = lambda: ("verse", 0, prog),
	)

	assert hs.current_chord.name() == "Am"

	history_before = len(hs.history)
	cb(4 * 24)	# exhausted — the live engine takes over
	assert len(hs.history) > history_before


@pytest.mark.asyncio
async def test_bound_progression_loops_without_a_live_engine (patch_midi: None) -> None:

	"""harmony(progression=) with no style loops on exhaustion — manual harmony forever."""

	prog = _progression_of("Am", "F")

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: None,
		cycle_beats = 4,
		get_bound_progression = lambda: prog,
	)

	assert horizon.chord_at(0.0).name() == "Am"

	cb(4 * 24)
	assert horizon.chord_at(4.0).name() == "F"

	cb(8 * 24)	# wrapped — the loop, not a fall-through (there is nothing to fall to)
	assert horizon.chord_at(8.0).name() == "Am"

	# The future is data: arbitrary beats answer without any fire.
	assert horizon.chord_at(101.0).name() == "F"	# beat 101 → offset 5 in the 8-beat loop


@pytest.mark.asyncio
async def test_no_sources_schedules_nothing (patch_midi: None) -> None:

	"""With no engine and no progressions the clock declines to run."""

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: None,
		cycle_beats = 4,
	)

	assert cb is None
	assert horizon.is_empty


@pytest.mark.asyncio
async def test_variable_spans_fire_at_span_and_bar_boundaries (patch_midi: None) -> None:

	"""The clock fires at min(next span boundary, next bar boundary) — bar-aligned bookkeeping."""

	prog = subsequence.progressions.progression([("Am", 2), ("F", 6)])

	cb, horizon, first = await _capture_clock(
		get_harmonic_state = lambda: None,
		cycle_beats = 4,
		get_bound_progression = lambda: prog,
	)

	# Span Am ends at 2 — before the bar line at 4.
	assert first == 2.0

	# Chord boundary at 2: F begins, lasting to 8; next fire is the BAR at 4.
	assert cb(2 * 24) == 2.0
	assert horizon.chord_at(2.0).name() == "F"

	# Bar fire at 4: no chord change; next fire is the bar at 8 (== span end).
	assert cb(4 * 24) == 4.0
	assert horizon.chord_at(5.0).name() == "F"

	# Boundary at 8 wraps to Am.
	cb(8 * 24)
	assert horizon.chord_at(8.0).name() == "Am"


@pytest.mark.asyncio
async def test_pinned_chord_overrides_the_source (patch_midi: None) -> None:

	"""pin_chord is fiat — whatever the source produced, the pin sounds."""

	prog = _progression_of("Am", "F")
	pinned = subsequence.chords.parse_chord("E7")

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: None,
		cycle_beats = 4,
		get_bound_progression = lambda: prog,
		get_pinned = {2: pinned}.get,	# bar 2 = beats 4..8
	)

	cb(4 * 24)
	assert horizon.chord_at(4.0) is pinned

	# The data future honours pins too (bar 2 of any query window).
	assert horizon.chord_at(0.0).name() == "Am"


@pytest.mark.asyncio
async def test_live_window_clamps_beyond_planned_with_one_warning (patch_midi: None) -> None:

	"""In live mode chord_at beyond [current, next] clamps to the last known chord."""

	hs = subsequence.harmonic_state.HarmonicState(
		key_name="C", graph_style="functional_major", rng=random.Random(1)
	)

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
	)

	planned = horizon.chord_at(4.0)	# the pre-committed step — real data
	beyond = horizon.chord_at(40.0)	# far beyond the window — clamped

	assert planned is not None
	assert beyond is planned


@pytest.mark.asyncio
async def test_decorated_spans_reach_the_window_engine_keeps_bare_triads (patch_midi: None) -> None:

	"""Patterns hear the decorated chord; engine state stays the bare triad (§8.11)."""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="functional_major")
	prog = _progression_of("Am", "F").extend(9, only=[1])

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: hs,
		cycle_beats = 4,
		get_bound_progression = lambda: prog,
	)

	sounding = horizon.chord_at(0.0)

	assert isinstance(sounding, subsequence.progressions.DecoratedChord)
	assert sounding.name() == "Am9"
	assert hs.current_chord == subsequence.chords.parse_chord("Am")	# bare in the engine


# ── zero_indexed_channels ─────────────────────────────────────────────────────


def test_zero_indexed_channels_default_is_false (patch_midi: None) -> None:

	"""Default zero_indexed_channels=False uses 1-based channel numbering."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=10, beats=4)
	def drums (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	# Internal channel should be 9 (10 - 1, converted from 1-indexed)
	assert composition._pending_patterns[0].channel == 9


def test_one_indexed_channels_subtracts_one (patch_midi: None) -> None:

	"""zero_indexed_channels=False converts channel 10 → internal 9."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=False)

	@composition.pattern(channel=10, beats=4)
	def drums (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert composition._pending_patterns[0].channel == 9


def test_one_indexed_channels_channel_1 (patch_midi: None) -> None:

	"""zero_indexed_channels=False converts channel 1 → internal 0."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=False)

	@composition.pattern(channel=1, beats=4)
	def bass (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert composition._pending_patterns[0].channel == 0


def test_one_indexed_channels_rejects_zero (patch_midi: None) -> None:

	"""zero_indexed_channels=False rejects channel=0."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=False)

	with pytest.raises(ValueError, match="1-16"):
		@composition.pattern(channel=0, beats=4)
		def bad (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_one_indexed_channels_rejects_17 (patch_midi: None) -> None:

	"""zero_indexed_channels=False rejects channel=17."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=False)

	with pytest.raises(ValueError, match="1-16"):
		@composition.pattern(channel=17, beats=4)
		def bad (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_zero_indexed_channels_rejects_16 (patch_midi: None) -> None:

	"""zero_indexed_channels=True rejects channel=16."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=True)

	with pytest.raises(ValueError, match="0-15"):
		@composition.pattern(channel=16, beats=4)
		def bad (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_one_indexed_layer (patch_midi: None) -> None:

	"""layer() also resolves channels when 1-indexed."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=False)

	def kick (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	composition.layer(kick, channel=10, beats=4)

	assert composition._pending_patterns[0].channel == 9


def test_live_info_reports_user_convention (patch_midi: None) -> None:

	"""live_info() adds 1 back to channels when 1-indexed."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, zero_indexed_channels=False)

	def my_builder (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 9,  # internally 0-indexed
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	pattern = composition._build_pattern_from_pending(pending)
	composition._running_patterns["my_builder"] = pattern

	info = composition.live_info()

	# Should report channel 10 (9 + 1) to the user
	assert info["patterns"][0]["channel"] == 10


# --- beats= / bars= / length= aliases ---


def test_pattern_beats_alias (patch_midi: None) -> None:

	"""beats= should produce the same beat_length as length=."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, beats=8)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert composition._pending_patterns[0].length == 8


def test_pattern_bars_alias (patch_midi: None) -> None:

	"""bars=2 should produce beat_length=8 (2 bars × 4 beats)."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, bars=2)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert composition._pending_patterns[0].length == 8


def test_pattern_default_is_four_beats (patch_midi: None) -> None:

	"""Omitting beats/bars should default to 4 beats."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	assert composition._pending_patterns[0].length == 4


def test_pattern_multiple_length_params_raises (patch_midi: None) -> None:

	"""Specifying both beats= and bars= should raise ValueError."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	with pytest.raises(ValueError, match="Specify only one"):

		@composition.pattern(channel=1, beats=4, bars=1)
		def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_resolve_length_bars_one (patch_midi: None) -> None:

	"""bars=1 should give beat_length=4 and default_grid=16."""

	beat_length, default_grid = subsequence.Composition._resolve_length(None, 1, None, None)
	assert beat_length == 4
	assert default_grid == 16


def test_resolve_length_beats_eight (patch_midi: None) -> None:

	"""beats=8 should give beat_length=8 and default_grid=32."""

	beat_length, default_grid = subsequence.Composition._resolve_length(8, None, None, None)
	assert beat_length == 8
	assert default_grid == 32


def test_pattern_steps_unit (patch_midi: None) -> None:

	"""steps=6, step_duration=SIXTEENTH should give beat_length=1.5 and default_grid=6."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, steps=6, step_duration=dur.SIXTEENTH)
	def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	pending = composition._pending_patterns[0]
	assert pending.length == pytest.approx(1.5)
	assert pending.default_grid == 6


def test_steps_without_unit_raises (patch_midi: None) -> None:

	"""steps= without step_duration= should raise ValueError."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	with pytest.raises(ValueError, match="steps= requires step_duration="):

		@composition.pattern(channel=1, steps=6)
		def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_unit_without_steps_raises (patch_midi: None) -> None:

	"""step_duration= without steps= should raise ValueError."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	with pytest.raises(ValueError, match="step_duration= requires steps="):

		@composition.pattern(channel=1, beats=4, step_duration=dur.SIXTEENTH)
		def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_steps_with_beats_raises (patch_midi: None) -> None:

	"""steps= combined with beats= should raise ValueError."""

	import subsequence.constants.durations as dur

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	with pytest.raises(ValueError, match="steps= cannot be combined"):

		@composition.pattern(channel=1, steps=6, beats=4, step_duration=dur.SIXTEENTH)
		def my_pattern (p: "subsequence.pattern_builder.PatternBuilder") -> None:
			pass


def test_layer_beats_alias (patch_midi: None) -> None:

	"""layer() should accept beats= and produce correct beat_length."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	def kick (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	composition.layer(kick, channel=1, beats=8)

	assert composition._pending_patterns[0].length == 8


def test_layer_bars_alias (patch_midi: None) -> None:

	"""layer() should accept bars= and convert to beat_length."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	def kick (p: "subsequence.pattern_builder.PatternBuilder") -> None:
		pass

	composition.layer(kick, channel=1, bars=2)

	assert composition._pending_patterns[0].length == 8

def test_section_chords_replay_aligns_with_section_boundaries (tmp_path, patch_midi: None) -> None:

	"""Frozen section chords must start on the section's FIRST bar.

	Regression: the harmonic clock was registered before the form clock, so on
	every section-boundary bar it read the outgoing section and the frozen
	progression played one bar late, bleeding its last chord into the next
	section.
	"""

	composition = subsequence.Composition(bpm=960, key="C", seed=11)
	composition.harmony(style="functional_major", cycle_beats=4)
	composition.form([("verse", 2), ("chorus", 2)], loop=True)

	prog = composition.freeze(bars=2)
	composition.section_chords("chorus", prog)

	observed = []

	@composition.pattern(channel=1, beats=4)
	def watcher (p, chord) -> None:
		if p.section is not None:
			observed.append((p.section.name, chord.name()))

	composition.render(bars=8, filename=str(tmp_path / "align.mid"))

	frozen_names = [c.name() for c in prog.chords]
	chorus_chords = [name for section, name in observed if section == "chorus"]
	verse_chords = [name for section, name in observed if section == "verse"]

	# Every chorus bar must play the frozen chords in order from bar one.
	assert chorus_chords[:2] == frozen_names

	# The frozen progression must not bleed into the verse following a chorus.
	# (Live verse harmony could coincide by chance with seed-dependent chords,
	# so pin the structural property: chorus bars exactly cycle the frozen pair.)
	assert all(
		chorus_chords[i] == frozen_names[i % 2]
		for i in range(len(chorus_chords))
	)
	assert len(verse_chords) >= 2

@pytest.mark.asyncio
async def test_unregistered_pattern_is_not_resurrected_by_later_graduation (patch_midi: None) -> None:

	"""A pattern deleted via unregister() must not come back on a later reload pass.

	Regression: pending declarations were never pruned, so every subsequent
	live-reload graduation re-scheduled patterns that had been deleted.
	"""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	@composition.pattern(channel=1, beats=4)
	def ghost (p) -> None:
		p.note(60, beat=0)

	await composition._activate_new_pending_patterns()

	assert "ghost" in composition._running_patterns
	assert composition._pending_patterns == []

	composition.unregister("ghost")

	assert "ghost" not in composition._running_patterns

	# A later reload's graduation pass must not bring it back.
	await composition._activate_new_pending_patterns()

	assert "ghost" not in composition._running_patterns


def test_schedule_after_play_raises (patch_midi: None) -> None:

	"""schedule() after playback starts must fail loudly, not register silently into the void."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	composition._sequencer.running = True

	with pytest.raises(RuntimeError, match="before play"):
		composition.schedule(lambda: None, cycle_beats=4)


@pytest.mark.asyncio
async def test_pin_inside_a_long_span_forces_its_bar (patch_midi: None) -> None:

	"""A pin on a bar mid-span takes effect at that bar line — fiat is fiat."""

	prog = subsequence.progressions.progression([("Am", 8)])	# one span, two bars
	pinned = subsequence.chords.parse_chord("E7")

	cb, horizon, _ = await _capture_clock(
		get_harmonic_state = lambda: None,
		cycle_beats = 4,
		get_bound_progression = lambda: prog,
		get_pinned = {2: pinned}.get,
	)

	assert horizon.chord_at(0.0).name() == "Am"

	# The bar fire at beat 4 is NOT a chord boundary — the pin still lands.
	cb(4 * 24)
	assert horizon.chord_at(4.0) is pinned
	assert horizon.chord_at(2.0).name() == "Am"		# the first bar is untouched
