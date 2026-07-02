"""Regression tests for the 2026-07 Low-severity fix wave.

Covers the opaque-crash-to-musical-error fixes (Batch 1), the behaviour
changes shipped with the doc corrections (chord_weight range, slide()
honesty — Batch 3), the consolidation refactors (Batch 4), and the
scale_velocities() last-half-step wrap fix.
"""

import typing

import pytest

import subsequence.melodic_state
import subsequence.motifs
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.progressions
import subsequence.sequence_utils


def make_builder (cycle: int = 0, length: float = 4.0) -> typing.Tuple[subsequence.pattern_builder.PatternBuilder, subsequence.pattern.Pattern]:

	"""Build a standalone PatternBuilder over a fresh pattern for testing."""

	pat = subsequence.pattern.Pattern(channel=0, length=length)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=cycle)

	return builder, pat


# ── Batch 1: opaque crashes → musical errors ────────────────────────────────


def test_motif_euclidean_zero_steps_zero_pulses_is_empty_motif () -> None:

	"""Nothing asked for on no grid is a clean empty motif, not a ZeroDivisionError."""

	m = subsequence.motifs.Motif.euclidean(pulses=0, steps=0, pitch=36)

	assert m.events == ()
	assert m.length == 4.0


def test_motif_euclidean_pulses_on_zero_steps_still_raises () -> None:

	"""Asking for pulses on a zero-step grid keeps the kernel's clear error."""

	with pytest.raises(ValueError, match="cannot be greater than steps"):
		subsequence.motifs.Motif.euclidean(pulses=3, steps=0, pitch=36)


def test_motif_notes_rejects_bool_pitch () -> None:

	"""True/False are not MIDI notes even though bool subclasses int."""

	with pytest.raises(TypeError, match="got bool"):
		subsequence.motifs.Motif.notes([True, 60])


def test_motif_euclidean_rejects_bool_pitch () -> None:

	"""A bool pitch raises a clear TypeError instead of a KeyError deep in sorting."""

	with pytest.raises(TypeError, match="MIDI int or drum name"):
		subsequence.motifs.Motif.euclidean(pulses=3, steps=16, pitch=True)


def test_markov_zero_spacing_raises () -> None:

	"""markov() names the spacing parameter instead of dividing by zero."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="spacing"):
		builder.markov(
			transitions={"a": [("a", 1)]},
			pitch_map={"a": 60},
			spacing=0,
		)


def test_melody_zero_spacing_raises () -> None:

	"""melody() names the spacing parameter instead of dividing by zero."""

	builder, _ = make_builder()
	state = subsequence.melodic_state.MelodicState()

	with pytest.raises(ValueError, match="spacing"):
		builder.melody(state, spacing=0)


def test_lsystem_zero_spacing_raises () -> None:

	"""lsystem() names the spacing parameter instead of dividing by zero."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="spacing"):
		builder.lsystem(
			pitch_map={"A": 60},
			axiom="A",
			rules={"A": "AB", "B": "A"},
			spacing=0,
		)


def test_de_bruijn_zero_spacing_raises () -> None:

	"""de_bruijn() names the spacing parameter instead of dividing by zero."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="spacing"):
		builder.de_bruijn([60, 62], spacing=0)


def test_lorenz_zero_spacing_raises () -> None:

	"""lorenz() names the spacing parameter instead of dividing by zero."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="spacing"):
		builder.lorenz([60, 62, 64], spacing=0)


def test_self_avoiding_walk_negative_spacing_raises () -> None:

	"""self_avoiding_walk() rejects negative spacing with a clear error."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="spacing"):
		builder.self_avoiding_walk([60, 62, 64], spacing=-0.25)


def test_every_zero_cycle_length_raises () -> None:

	"""every(0, ...) explains the cycle length instead of a modulo-by-zero crash."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="cycle length must be at least 1"):
		builder.every(0, lambda p: p.reverse())


def test_bar_cycle_zero_length_raises () -> None:

	"""bar_cycle(0) explains the cycle length instead of a modulo-by-zero crash."""

	builder, _ = make_builder()

	with pytest.raises(ValueError, match="cycle length must be at least 1"):
		builder.bar_cycle(0)


def test_cellular_automaton_2d_degenerate_grid_is_empty () -> None:

	"""Zero rows or columns yield the degenerate empty grid, matching the 1D no-op."""

	assert subsequence.sequence_utils.generate_cellular_automaton_2d(rows=0, cols=16) == []
	assert subsequence.sequence_utils.generate_cellular_automaton_2d(rows=3, cols=0) == [[], [], []]


def test_pink_noise_zero_sources_raises () -> None:

	"""pink_noise() asks for at least one source instead of an IndexError."""

	with pytest.raises(ValueError, match="at least one random source"):
		subsequence.sequence_utils.pink_noise(steps=8, sources=0)


def test_diatonic_extension_intervals_out_of_range_degree_raises () -> None:

	"""An out-of-range bare degree matches RomanChord.resolve's error style."""

	chord = subsequence.progressions.RomanChord(degree=8)

	with pytest.raises(ValueError, match="scale degree 8 is out of range"):
		chord.diatonic_extension_intervals(0, "ionian", (7,))


# ── Batch 3 behaviour changes ───────────────────────────────────────────────


def test_chord_weight_validates_documented_range () -> None:

	"""chord_weight is documented 0.0–1.0 and now validates like its sibling dials."""

	with pytest.raises(ValueError, match="between 0 and 1"):
		subsequence.melodic_state.MelodicState(chord_weight=1.5)

	with pytest.raises(ValueError, match="between 0 and 1"):
		subsequence.melodic_state.MelodicState(chord_weight=-0.1)

	# The documented endpoints stay valid.
	subsequence.melodic_state.MelodicState(chord_weight=0.0)
	subsequence.melodic_state.MelodicState(chord_weight=1.0)


def test_slide_rejects_notes_and_steps_together () -> None:

	"""notes= and steps= are documented mutually exclusive — passing both raises."""

	builder, _ = make_builder()
	builder.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])

	with pytest.raises(ValueError, match="not both"):
		builder.slide(notes=[1], steps=[4])


def test_slide_out_of_range_note_index_raises_musically () -> None:

	"""An out-of-range note index names the pattern's note count, not an IndexError."""

	builder, _ = make_builder()
	builder.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])

	with pytest.raises(ValueError, match="note index 5 is outside this pattern's 4 notes"):
		builder.slide(notes=[5])


def test_slide_negative_note_index_still_works () -> None:

	"""Documented negative indexing survives the new bounds check."""

	builder, pat = make_builder()
	builder.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 41])
	builder.legato(0.95)
	builder.slide(notes=[-1], time=0.2)

	assert any(e.message_type == "pitchwheel" for e in pat.cc_events)


# ── Batch 4: consolidation refactors keep behaviour ─────────────────────────


def test_thue_morse_two_pitch_placement_unchanged () -> None:

	"""Two-pitch mode still places pitch at 0-positions and pitch_b at 1-positions."""

	builder, pat = make_builder()
	builder.thue_morse(36, pitch_b=38, velocity=100)

	sequence = subsequence.sequence_utils.thue_morse(16)
	step_pulses = 96 / 16

	for i, val in enumerate(sequence):
		notes = pat.steps[int(i * step_pulses)].notes
		expected = 36 if val == 0 else 38

		assert [n.pitch for n in notes] == [expected]


def test_bresenham_poly_voices_never_overlap () -> None:

	"""Interlocking placement survives the shared-kernel refactor."""

	builder, pat = make_builder()
	builder.bresenham_poly(parts={36: 0.5, 38: 0.25}, velocity={36: 100, 38: 70})

	for step in pat.steps.values():
		assert len(step.notes) == 1

	velocities = {n.pitch: n.velocity for s in pat.steps.values() for n in s.notes}

	assert velocities == {36: 100, 38: 70}


def test_bend_emits_endpoint_when_resolution_skips_it () -> None:

	"""The endpoint rule survives delegating _generate_bend_events to the ramp kernel."""

	builder, pat = make_builder()
	builder.note(pitch=60, beat=0.0, duration=1.0)
	builder.note(pitch=62, beat=2.0, duration=1.0)

	# Duration 24 pulses, ramp over pulses 0..24 with resolution 5: 24 % 5 != 0,
	# so the target value must still be emitted at the ramp's final pulse.
	builder.bend(note=0, amount=1.0, resolution=5)

	wheel = [e for e in pat.cc_events if e.message_type == "pitchwheel"]
	final = [e for e in wheel if e.pulse == 24]

	assert final and final[-1].value == 8191


def test_euclidean_seeded_thinning_unchanged () -> None:

	"""Seeded probability thinning is stable through _place_gated_sequence."""

	builder_a, pat_a = make_builder()
	builder_a.euclidean(36, pulses=7, probability=0.6, seed=5)

	builder_b, pat_b = make_builder()
	builder_b.euclidean(36, pulses=7, probability=0.6, seed=5)

	assert sorted(pat_a.steps) == sorted(pat_b.steps)
	assert 0 < len(pat_a.steps) <= 7


# ── scale_velocities: last-half-step wrap ───────────────────────────────────


def test_scale_velocities_scales_note_in_last_half_step () -> None:

	"""A note in the pattern's last half-step wraps to step 0's factor instead of escaping."""

	builder, pat = make_builder()

	# 4 beats × 24 PPQ = 96 pulses; grid 16 → 6 pulses per step.  Beat 3.95
	# lands on pulse 94, which rounds to step 16 — the wrap to step 0.
	builder.note(pitch=60, beat=3.95, velocity=100, duration=0.1)
	builder.scale_velocities([0.5] + [1.0] * 15)

	note = next(iter(pat.steps.values())).notes[0]

	assert note.velocity == 50


def test_scale_velocities_on_grid_steps_unchanged () -> None:

	"""Notes on ordinary grid steps still scale by their own step's factor."""

	builder, pat = make_builder()
	builder.note(pitch=60, beat=0.0, velocity=100, duration=0.1)
	builder.note(pitch=60, beat=1.0, velocity=100, duration=0.1)

	factors = [1.0] * 16
	factors[4] = 0.25
	builder.scale_velocities(factors)

	assert pat.steps[0].notes[0].velocity == 100
	assert pat.steps[24].notes[0].velocity == 25
