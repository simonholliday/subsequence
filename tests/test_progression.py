"""Tests for declarative chord progressions.

Covers between(), realize(), the yielding p.progression(), positional
p.chord()/p.strum(beat=), and the comp.chords() block convenience.
"""

import logging
import random
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.harmonic_rhythm
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.progression

WHOLE = subsequence.constants.durations.WHOLE
HALF = subsequence.constants.durations.HALF
PPQ = subsequence.constants.MIDI_QUARTER_NOTE


def _builder (
	length: float = 16.0,
	key: typing.Optional[str] = None,
	seed: typing.Optional[int] = None,
) -> typing.Tuple[subsequence.pattern.Pattern, subsequence.pattern_builder.PatternBuilder]:

	"""A Pattern/PatternBuilder pair for unit-level progression tests."""

	default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
	pattern = subsequence.pattern.Pattern(channel=0, length=length)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern,
		cycle=0,
		default_grid=default_grid,
		key=key,
		rng=random.Random(seed) if seed is not None else None,
	)
	return pattern, builder


# ── between(): the harmonic-rhythm range ─────────────────────────────────────

def test_between_quantizes_to_step () -> None:
	rng = random.Random(0)
	spec = subsequence.harmonic_rhythm.between(WHOLE, 3 * WHOLE, step=WHOLE)

	draws = {spec.resolve(rng) for _ in range(300)}

	assert draws == {4.0, 8.0, 12.0}


def test_between_continuous_stays_within_bounds () -> None:
	rng = random.Random(1)
	spec = subsequence.harmonic_rhythm.between(2.0, 5.0)

	for _ in range(300):
		assert 2.0 <= spec.resolve(rng) <= 5.0


def test_between_rejects_bad_bounds () -> None:
	with pytest.raises(ValueError):
		subsequence.harmonic_rhythm.between(0.0, 4.0)
	with pytest.raises(ValueError):
		subsequence.harmonic_rhythm.between(8.0, 4.0)


# ── realize(): laying a progression out in time (chord, start, length only) ───

def test_realize_fills_and_trims_to_length () -> None:
	chords = [subsequence.chords.Chord(0, "minor"), subsequence.chords.Chord(2, "minor")]

	timeline = subsequence.progression.realize(chords, WHOLE, None, 14.0, random.Random(0))

	assert sum(e.length for e in timeline.events) == 14.0
	assert [e.start for e in timeline.events] == [0.0, 4.0, 8.0, 12.0]
	assert timeline.events[-1].length == 2.0						# last chord trimmed (14 − 12)
	assert [e.chord.root_pc for e in timeline.events] == [0, 2, 0, 2]	# list cycles


def test_realize_list_harmonic_rhythm_cycles () -> None:
	chords = [subsequence.chords.Chord(0, "major")]

	timeline = subsequence.progression.realize(chords, [HALF, WHOLE], None, 12.0, random.Random(0))

	assert [e.length for e in timeline.events] == [2.0, 4.0, 2.0, 4.0]
	assert [e.start for e in timeline.events] == [0.0, 2.0, 6.0, 8.0]


def test_realize_is_deterministic_under_seed () -> None:
	spec = subsequence.harmonic_rhythm.between(WHOLE, 3 * WHOLE, step=WHOLE)

	first = subsequence.progression.realize("phrygian_minor", spec, "C", 32.0, random.Random(7))
	second = subsequence.progression.realize("phrygian_minor", spec, "C", 32.0, random.Random(7))

	assert first == second


def test_realize_style_requires_a_key () -> None:
	with pytest.raises(ValueError):
		subsequence.progression.realize("phrygian_minor", WHOLE, None, 16.0, random.Random(0))


def test_realize_phrygian_chords_are_in_key () -> None:
	timeline = subsequence.progression.realize("phrygian_minor", WHOLE, "C", 64.0, random.Random(2))

	# C Phrygian graph: i, bii, iv, v — all minor, roots in {0, 1, 5, 7}.
	for event in timeline.events:
		assert event.chord.quality == "minor"
		assert event.chord.root_pc in {0, 1, 5, 7}


def test_realize_rejects_nonpositive_harmonic_rhythm () -> None:
	chords = [subsequence.chords.Chord(0, "major")]
	with pytest.raises(ValueError):
		subsequence.progression.realize(chords, 0.0, None, 16.0, random.Random(0))


# ── ChordEvent / ChordTimeline shape ─────────────────────────────────────────

def test_chord_event_unpacks_and_has_attributes () -> None:
	timeline = subsequence.progression.realize([subsequence.chords.Chord(0, "minor")], WHOLE, None, 8.0, random.Random(0))

	assert len(timeline) == 2									# ChordTimeline supports len()

	rows = [(chord, start, length) for chord, start, length in timeline]		# iterable + unpackable
	assert len(rows) == 2

	event = timeline.events[0]
	assert event.chord.root_pc == 0 and event.start == 0.0 and event.length == 4.0	# attribute access


def test_resolve_voices_fixed_and_range () -> None:
	rng = random.Random(0)

	assert subsequence.progression.resolve_voices(3, rng) == 3
	assert {subsequence.progression.resolve_voices((3, 4), rng) for _ in range(50)} == {3, 4}


# ── parse_chord() ────────────────────────────────────────────────────────────

def test_parse_chord_reads_common_names () -> None:
	assert subsequence.chords.parse_chord("Cm7") == subsequence.chords.Chord(0, "minor_7th")
	assert subsequence.chords.parse_chord("Dbmaj7") == subsequence.chords.Chord(1, "major_7th")
	assert subsequence.chords.parse_chord("F#") == subsequence.chords.Chord(6, "major")
	assert subsequence.chords.parse_chord("Gm7b5") == subsequence.chords.Chord(7, "half_diminished_7th")


def test_parse_chord_round_trips_chord_name () -> None:
	for pc in range(12):
		for quality in subsequence.chords.CHORD_INTERVALS:
			chord = subsequence.chords.Chord(pc, quality)
			assert subsequence.chords.parse_chord(chord.name()) == chord


def test_parse_chord_rejects_garbage () -> None:
	with pytest.raises(ValueError):
		subsequence.chords.parse_chord("H7")
	with pytest.raises(ValueError):
		subsequence.chords.parse_chord("Cwhatever")


# ── p.progression(): yields a timeline; you place with a verb ────────────────

def test_progression_returns_iterable_timeline_without_placing () -> None:
	pattern, builder = _builder(length=16.0, key="C", seed=1)

	timeline = builder.progression("phrygian_minor", harmonic_rhythm=WHOLE, seed=7)

	assert isinstance(timeline, subsequence.progression.ChordTimeline)
	assert len(timeline) == 4									# 16 beats / whole note
	assert len(pattern.steps) == 0								# progression() itself places nothing


def test_progression_loop_with_strum_places_notes () -> None:
	pattern, builder = _builder(length=16.0)

	for chord, start, length in builder.progression([subsequence.chords.Chord(0, "minor")], harmonic_rhythm=WHOLE, seed=1):
		builder.strum(chord, root=48, beat=start, duration=length - 0.25, offset=0.1, count=3)

	# 4 chords × 3 staggered voices.
	assert sum(len(step.notes) for step in pattern.steps.values()) == 12


def test_progression_defaults_key_to_builder_key () -> None:
	# No key= passed; the builder's key ("C") must let a style generate.
	_, builder = _builder(length=16.0, key="C")

	timeline = builder.progression("phrygian_minor", harmonic_rhythm=WHOLE)

	assert len(timeline) == 4


# ── positional p.chord() / p.strum() (beat=) ─────────────────────────────────

def test_chord_beat_places_at_offset () -> None:
	pattern, builder = _builder(length=16.0)

	builder.chord(subsequence.chords.Chord(0, "minor"), root=48, beat=8.0, duration=2.0, count=3)

	pulse = int(8.0 * PPQ)
	assert pulse in pattern.steps
	assert len(pattern.steps[pulse].notes) == 3


def test_chord_beat_defaults_to_start () -> None:
	pattern, builder = _builder(length=16.0)

	builder.chord(subsequence.chords.Chord(0, "minor"), root=48, duration=1.0, count=3)

	assert 0 in pattern.steps


def test_strum_beat_offsets_the_stagger () -> None:
	pattern, builder = _builder(length=16.0)

	builder.strum(subsequence.chords.Chord(0, "minor"), root=48, beat=4.0, offset=0.5, count=3, duration=1.0)

	# First note on beat 4, then +0.5 each.
	assert int(4.0 * PPQ) in pattern.steps
	assert int(4.5 * PPQ) in pattern.steps
	assert int(5.0 * PPQ) in pattern.steps


# ── comp.chords(): the one-call block convenience ────────────────────────────

def test_comp_chords_returns_timeline_and_registers (patch_midi: None) -> None:
	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	before = len(comp._pending_patterns)

	timeline = comp.chords(channel=1, bars=4, progression="phrygian_minor", harmonic_rhythm=WHOLE, seed=1)

	assert isinstance(timeline, subsequence.progression.ChordTimeline)
	assert sum(e.length for e in timeline.events) == 16.0		# 4 bars of 4/4
	assert len(comp._pending_patterns) == before + 1


def test_comp_chords_is_stable_with_seed (patch_midi: None) -> None:
	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	spec = subsequence.harmonic_rhythm.between(WHOLE, 2 * WHOLE, step=WHOLE)

	first = comp.chords(channel=1, bars=8, progression="phrygian_minor", harmonic_rhythm=spec, seed=5)
	second = comp.chords(channel=2, bars=8, progression="phrygian_minor", harmonic_rhythm=spec, seed=5)

	assert first.events == second.events


def test_comp_chords_registered_builder_plays_block_chords (patch_midi: None) -> None:
	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	timeline = comp.chords(channel=1, bars=4, progression="phrygian_minor", harmonic_rhythm=WHOLE, voicing=3, seed=1)

	pending = comp._pending_patterns[-1]
	pattern = subsequence.pattern.Pattern(channel=0, length=pending.length)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern, cycle=0, default_grid=pending.default_grid, key="C"
	)
	pending.builder_fn(builder)

	# One onset per chord (block), three voices each (voicing=3).
	assert len(pattern.steps) == len(timeline)
	assert sum(len(step.notes) for step in pattern.steps.values()) == 3 * len(timeline)


def test_comp_chords_key_handling (patch_midi: None) -> None:
	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)		# no composition key

	# An explicit chord list needs no key.
	explicit = comp.chords(channel=1, bars=2, progression=["Cm7", "Fm7"], harmonic_rhythm=WHOLE)
	assert len(explicit.events) == 2

	# A style generates when a key override is supplied.
	overridden = comp.chords(channel=2, bars=2, progression="phrygian_minor", harmonic_rhythm=WHOLE, key="A")
	assert len(overridden.events) == 2

	# A style with no key anywhere is an error.
	with pytest.raises(ValueError):
		comp.chords(channel=3, bars=2, progression="phrygian_minor", harmonic_rhythm=WHOLE)


# ── API-consistency-pass fixes (review of the chord-progression feature) ─────

def test_harmonic_rhythm_bare_tuple_is_rejected () -> None:
	# (low, high) means a random range elsewhere (velocity); a bare tuple here is ambiguous.
	with pytest.raises(ValueError, match="ambiguous"):
		subsequence.progression.realize([subsequence.chords.Chord(0, "minor")], (4.0, 8.0), None, 16.0, random.Random(0))


def test_harmonic_rhythm_list_still_cycles () -> None:
	# A list is the explicit spelling for a shaped sequence — still accepted.
	timeline = subsequence.progression.realize([subsequence.chords.Chord(0, "minor")], [2.0, 4.0], None, 12.0, random.Random(0))
	assert [e.length for e in timeline.events] == [2.0, 4.0, 2.0, 4.0]


def test_positioned_chord_with_detached_warns_once (caplog: typing.Any) -> None:
	_, builder = _builder(length=16.0)

	with caplog.at_level(logging.WARNING, logger="subsequence.pattern_builder"):
		builder.chord(subsequence.chords.Chord(0, "minor"), root=48, beat=4.0, detached=0.25, count=3)
		builder.chord(subsequence.chords.Chord(0, "minor"), root=48, beat=8.0, detached=0.25, count=3)

	warned = [r for r in caplog.records if "past its slot" in r.getMessage()]
	assert len(warned) == 1		# fires, and dedupes across calls on the same pattern


def test_chord_at_beat_zero_does_not_warn (caplog: typing.Any) -> None:
	_, builder = _builder(length=16.0)

	with caplog.at_level(logging.WARNING, logger="subsequence.pattern_builder"):
		builder.chord(subsequence.chords.Chord(0, "minor"), root=48, detached=0.25, count=3)		# beat=0 default

	assert not [r for r in caplog.records if "past its slot" in r.getMessage()]


def test_staccato_param_is_beats_not_ratio () -> None:
	pattern, builder = _builder(length=4.0)
	builder.note(60, beat=0.0, duration=2.0)

	builder.staccato(beats=0.5)		# the keyword is now 'beats'
	assert pattern.steps[0].notes[0].duration == int(0.5 * PPQ)

	with pytest.raises(TypeError):
		builder.staccato(ratio=0.5)		# the old keyword is gone


def test_ghost_fill_rejects_non_pair_velocity_tuple () -> None:
	pattern, builder = _builder(length=4.0, seed=0)
	with pytest.raises(ValueError, match=r"must be \(low, high\)"):
		builder.ghost_fill(38, density=1.0, velocity=(10, 20, 30), bias="uniform")
