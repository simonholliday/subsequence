"""Tests for subsequence/progressions.py — the unified Progression value.

Covers the roman/name/degree element parser, query-time resolution, the five
spice operators, the governing algebra, the ChordEvent iteration contract
(inherited from the absorbed ChordTimeline), and the breathing realize() path.
"""

import random

import pytest

import subsequence.chords
import subsequence.harmonic_rhythm
import subsequence.progressions


A_MINOR = "A"
WHOLE = 4.0


def chord (name: str) -> subsequence.chords.Chord:

	"""Shorthand for parse_chord in expectations."""

	return subsequence.chords.parse_chord(name)


# ---------------------------------------------------------------------------
# parse_roman — the music21-semantics grammar
# ---------------------------------------------------------------------------

def test_roman_case_is_quality () -> None:

	"""Uppercase is major, lowercase is minor."""

	major, _ = subsequence.progressions.parse_roman("IV")
	minor, _ = subsequence.progressions.parse_roman("iv")

	assert major.degree == 4 and major.quality == "major"
	assert minor.degree == 4 and minor.quality == "minor"


def test_roman_sevenths_follow_case () -> None:

	"""V7 is a dominant seventh; v7 a minor seventh; Imaj7 a major seventh."""

	dominant, _ = subsequence.progressions.parse_roman("V7")
	minor7, _ = subsequence.progressions.parse_roman("v7")
	major7, _ = subsequence.progressions.parse_roman("Imaj7")

	assert dominant.quality == "dominant_7th"
	assert minor7.quality == "minor_7th"
	assert major7.quality == "major_7th"


def test_roman_diminished_and_half_diminished () -> None:

	"""vii° is a diminished triad, vii°7 fully diminished, viiø7 half-diminished."""

	triad, _ = subsequence.progressions.parse_roman("vii°")
	full, _ = subsequence.progressions.parse_roman("vii°7")
	half, _ = subsequence.progressions.parse_roman("viiø7")

	assert triad.quality == "diminished"
	assert full.quality == "diminished_7th"
	assert half.quality == "half_diminished_7th"


def test_roman_augmented () -> None:

	"""III+ is an augmented triad."""

	aug, _ = subsequence.progressions.parse_roman("III+")

	assert aug.degree == 3 and aug.quality == "augmented"


def test_roman_figures_give_inversions () -> None:

	"""6/64 invert triads; 65/43/42 invert seventh chords."""

	assert subsequence.progressions.parse_roman("I6")[1] == 1
	assert subsequence.progressions.parse_roman("I64")[1] == 2
	assert subsequence.progressions.parse_roman("ii65")[1] == 1
	assert subsequence.progressions.parse_roman("V43")[1] == 2
	assert subsequence.progressions.parse_roman("V42")[1] == 3
	assert subsequence.progressions.parse_roman("V2")[1] == 3

	seventh, _ = subsequence.progressions.parse_roman("ii65")
	assert seventh.quality == "minor_7th"


def test_roman_accidental_prefix () -> None:

	"""bVII reads against the major scale — the whole step below tonic."""

	flat, _ = subsequence.progressions.parse_roman("bVII")

	assert flat.degree == 7 and flat.accidental == -1 and flat.quality == "major"


def test_roman_secondary_function () -> None:

	"""V/V parses one level of secondary function."""

	secondary, _ = subsequence.progressions.parse_roman("V7/V")

	assert secondary.degree == 5 and secondary.of == 5 and secondary.quality == "dominant_7th"


def test_roman_rejects_two_levels_of_secondary () -> None:

	"""Only one /x level is supported — V/V/V raises."""

	with pytest.raises(ValueError, match="one level"):
		subsequence.progressions.parse_roman("V/V/V")


def test_roman_rejects_mixed_case_and_garbage () -> None:

	"""Mixed-case numerals and non-numerals fail loudly."""

	with pytest.raises(ValueError):
		subsequence.progressions.parse_roman("Iv")
	with pytest.raises(ValueError):
		subsequence.progressions.parse_roman("VIII")
	with pytest.raises(ValueError):
		subsequence.progressions.parse_roman("xyz")


# ---------------------------------------------------------------------------
# parse_element — per-element dispatch (decision 16)
# ---------------------------------------------------------------------------

def test_element_int_is_degree () -> None:

	"""A bare int is a 1-based diatonic degree, quality inferred later."""

	span = subsequence.progressions.parse_element(6)

	assert isinstance(span.chord, subsequence.progressions.RomanChord)
	assert span.chord.degree == 6 and span.chord.quality is None


def test_element_note_letter_string_is_chord_name () -> None:

	"""Strings starting with a note letter parse as chord names."""

	span = subsequence.progressions.parse_element("Am")

	assert span.chord == chord("Am")


def test_element_roman_string () -> None:

	"""Other strings parse as romans — including figured inversions."""

	span = subsequence.progressions.parse_element("bVII7")

	assert isinstance(span.chord, subsequence.progressions.RomanChord)
	assert span.chord.accidental == -1 and span.chord.quality == "dominant_7th"

	inverted = subsequence.progressions.parse_element("I6")
	assert inverted.inversion == 1


def test_element_tuple_sets_beats () -> None:

	"""(element, beats) tuples carry per-chord durations."""

	span = subsequence.progressions.parse_element(("Am", 2))

	assert span.chord == chord("Am") and span.beats == 2.0


def test_element_pitchset_passthrough () -> None:

	"""A PitchSet is a valid span chord."""

	cluster = subsequence.progressions.PitchSet([60, 61, 65])
	span = subsequence.progressions.parse_element(cluster)

	assert span.chord is cluster


def test_element_rejects_bool_and_garbage () -> None:

	"""Bools and unknown types fail loudly."""

	with pytest.raises(TypeError):
		subsequence.progressions.parse_element(True)
	with pytest.raises(TypeError):
		subsequence.progressions.parse_element(3.5)


def test_degree_must_be_one_based () -> None:

	"""Degree 0 is a hard error (1-based, the musician count)."""

	with pytest.raises(ValueError):
		subsequence.progressions.parse_element(0)


# ---------------------------------------------------------------------------
# The factory
# ---------------------------------------------------------------------------

def test_factory_degree_list_resolves_in_a_minor () -> None:

	"""progression([1, 6, 3, 7]) means i–VI–III–VII in A minor."""

	value = subsequence.progressions.progression([1, 6, 3, 7]).resolve("A", "minor")

	assert value.chords == (chord("Am"), chord("F"), chord("C"), chord("G"))


def test_factory_blues_skeleton () -> None:

	"""The 12-bar blues writes its structure in the code itself."""

	value = subsequence.progressions.progression(
		["I7"] * 4 + ["IV7", "IV7", "I7", "I7", "V7", "IV7", "I7", "I7"]
	).resolve("C")

	assert len(value) == 12
	assert value.chords[0] == chord("C7")
	assert value.chords[4] == chord("F7")
	assert value.chords[8] == chord("G7")
	assert value.length == 48.0


def test_factory_beats_scalar_and_list () -> None:

	"""beats= shapes the harmonic rhythm — scalar for all, list cycled."""

	even = subsequence.progressions.progression(["Am", "F"], beats=2)
	shaped = subsequence.progressions.progression(["Am", "F", "C", "G"], beats=[4, 2])

	assert [span.beats for span in even.spans] == [2.0, 2.0]
	assert [span.beats for span in shaped.spans] == [4.0, 2.0, 4.0, 2.0]


def test_factory_tuple_beats_override_list () -> None:

	"""A per-element (chord, beats) tuple wins over the beats= list."""

	value = subsequence.progressions.progression([("Am", 6), "F"], beats=4)

	assert [span.beats for span in value.spans] == [6.0, 4.0]


def test_factory_unknown_preset_raises () -> None:

	"""A bare string is a preset name; unknown names fail with the list hint."""

	with pytest.raises(ValueError, match="preset"):
		subsequence.progressions.progression("trance_epic")


def test_factory_style_generation_is_seeded () -> None:

	"""style= generates deterministically under a seed."""

	first = subsequence.progressions.progression(style="aeolian_minor", key="A", bars=8, seed=7)
	second = subsequence.progressions.progression(style="aeolian_minor", key="A", bars=8, seed=7)

	assert first.chords == second.chords
	assert len(first) == 8
	assert first.is_concrete


def test_factory_style_without_seed_warns () -> None:

	"""A standalone generated value without a seed warns (live-reload contract)."""

	with pytest.warns(UserWarning, match="seed"):
		subsequence.progressions.progression(style="aeolian_minor", key="A", bars=2)


def test_factory_style_and_source_conflict () -> None:

	"""Passing both a source and style= is an error."""

	with pytest.raises(ValueError, match="not both"):
		subsequence.progressions.progression(["Am"], style="aeolian_minor", key="A")


def test_factory_empty_list_raises () -> None:

	"""An empty progression is an error, not a silent no-op."""

	with pytest.raises(ValueError, match="empty"):
		subsequence.progressions.progression([])


# ---------------------------------------------------------------------------
# Resolution — romans stay relative until query time
# ---------------------------------------------------------------------------

def test_flat_seven_resolves_against_the_scale_itself () -> None:

	"""bVII in C major is Bb; VII in A minor is already G (no accidental)."""

	in_major = subsequence.progressions.progression(["bVII"]).resolve("C")
	in_minor = subsequence.progressions.progression(["VII"]).resolve("A", "minor")

	assert in_major.chords[0] == chord("Bb")
	assert in_minor.chords[0] == chord("G")


def test_change_the_key_once_everything_follows () -> None:

	"""The same value resolves differently under different keys — P2."""

	value = subsequence.progressions.progression([1, 6])

	assert value.resolve("A", "minor").chords == (chord("Am"), chord("F"))
	assert value.resolve("E", "minor").chords == (chord("Em"), chord("C"))


def test_secondary_dominant_resolves_to_five_of_five () -> None:

	"""V7/V in C is D7 — the dominant of the dominant."""

	value = subsequence.progressions.progression(["V7/V"]).resolve("C")

	assert value.chords[0] == chord("D7")


def test_inference_needs_scale_qualities () -> None:

	"""Bare-int degrees on a quality-less scale fail with the register_scale hint."""

	value = subsequence.progressions.progression([1])

	with pytest.raises(ValueError, match="qualities"):
		value.resolve("C", "hirajoshi")


def test_iteration_of_relative_progression_raises_with_hint () -> None:

	"""Iterating an unresolved value names the relative spans and the fix."""

	value = subsequence.progressions.progression([1, "Am"])

	with pytest.raises(ValueError, match="resolve"):
		list(value)


# ---------------------------------------------------------------------------
# The ChordEvent iteration contract (ChordTimeline's, preserved)
# ---------------------------------------------------------------------------

def test_iteration_unpacks_as_chord_start_length () -> None:

	"""for chord, start, length in progression — the placement idiom."""

	value = subsequence.progressions.progression(["Am", ("F", 2), "C"])
	events = list(value)

	assert [(e.chord.name(), e.start, e.length) for e in events] == [
		("Am", 0.0, 4.0),
		("F", 4.0, 2.0),
		("C", 6.0, 4.0),
	]

	first_chord, first_start, first_length = events[0]
	assert first_chord == chord("Am") and first_start == 0.0 and first_length == 4.0


def test_span_at_wraps_modulo_length () -> None:

	"""span_at() serves looped playback by wrapping the beat."""

	value = subsequence.progressions.progression(["Am", "F"], beats=4)

	span, start, end = value.span_at(5.0)
	assert span.chord == chord("F") and (start, end) == (4.0, 8.0)

	wrapped, _, _ = value.span_at(9.0)
	assert wrapped.chord == chord("Am")


# ---------------------------------------------------------------------------
# Algebra — the governing family
# ---------------------------------------------------------------------------

def test_plus_concatenates_and_star_tiles () -> None:

	"""+ joins progressions; * repeats them."""

	a = subsequence.progressions.progression(["Am", "F"])
	b = subsequence.progressions.progression(["C", "G"])

	combined = a + b
	tiled = a * 2

	assert combined.chords == (chord("Am"), chord("F"), chord("C"), chord("G"))
	assert tiled.chords == (chord("Am"), chord("F"), chord("Am"), chord("F"))
	assert tiled.length == 16.0


def test_parallel_merge_is_a_type_error () -> None:

	"""There is one current chord — & on progressions raises by design."""

	a = subsequence.progressions.progression(["Am"])
	b = subsequence.progressions.progression(["F"])

	with pytest.raises(TypeError, match="one current chord"):
		a & b


# ---------------------------------------------------------------------------
# Spice operators — decoration on spans, never on chords (§8.11)
# ---------------------------------------------------------------------------

def test_extend_decorates_without_touching_the_chord () -> None:

	"""extend(9) keeps the bare triad as the chord and decorates the span."""

	value = subsequence.progressions.progression(["Am"]).extend(9)
	span = value.spans[0]

	assert span.chord == chord("Am")
	assert span.extensions == (9,)
	assert span.decorated_intervals() == [0, 3, 7, 10, 14]
	assert span.label() == "Am9"


def test_extend_diatonic_degree_gets_scale_true_seventh () -> None:

	"""extend(7) on degree 5 in C major yields the dominant seventh (F natural)."""

	value = subsequence.progressions.progression([5]).extend(7).resolve("C")
	span = value.spans[0]

	assert span.chord == chord("G")
	assert span.decorated_intervals() == [0, 4, 7, 10]


def test_extend_concrete_major_uses_its_own_colour () -> None:

	"""extend(7) on a concrete major chord deepens in its own colour (maj7)."""

	value = subsequence.progressions.progression(["G"]).extend(7)

	assert value.spans[0].decorated_intervals() == [0, 4, 7, 11]


def test_extend_only_restricts_slots () -> None:

	"""only=[...] spices the named 1-based slots and leaves the rest bare."""

	value = subsequence.progressions.progression(["Am", "F", "C"]).extend(7, only=[2])

	assert value.spans[0].extensions == ()
	assert value.spans[1].extensions == (7,)
	assert value.spans[2].extensions == ()


def test_extend_sus4_replaces_the_third () -> None:

	"""sus4 swaps the third for the fourth."""

	value = subsequence.progressions.progression(["C"]).extend("sus4")

	assert value.spans[0].decorated_intervals() == [0, 5, 7]
	assert value.spans[0].label() == "Csus4"


def test_unknown_extension_raises () -> None:

	"""Unknown extension markers fail at construction."""

	with pytest.raises(ValueError, match="extension"):
		subsequence.progressions.progression(["C"]).extend(15)


def test_inversions_scalar_and_cycled_list () -> None:

	"""inversions() takes one int for all spans or a list cycled per span."""

	value = subsequence.progressions.progression(["Am", "F", "C"])

	assert [s.inversion for s in value.inversions(1).spans] == [1, 1, 1]
	assert [s.inversion for s in value.inversions([0, 2]).spans] == [0, 2, 0]


def test_spread_open_is_drop_two () -> None:

	"""spread('open') lowers the second-from-top voice an octave."""

	value = subsequence.progressions.progression(["C"]).spread("open")
	tones = value.spans[0].tones(60)

	assert tones == sorted(tones)
	assert tones == [52, 60, 67]	# E below, C, G


def test_over_tonic_pedal_resolves_at_query_time () -> None:

	"""over('tonic') is key-relative — the pedal follows the key."""

	value = subsequence.progressions.progression(["Am", "F"]).over("tonic")

	resolved = value.resolve("A", "minor")
	assert [span.bass for span in resolved.spans] == [9, 9]

	tones = resolved.spans[1].tones(60)
	assert tones[0] % 12 == 9 and tones[0] < min(tones[1:])
	assert resolved.spans[1].label() == "F/A"


def test_over_validates_note_names_early () -> None:

	"""A typo'd bass name fails at the call, not at resolution."""

	with pytest.raises(ValueError):
		subsequence.progressions.progression(["Am"]).over("H")


def test_borrow_resolves_against_the_parallel_scale () -> None:

	"""borrow(6) in C major swaps degree 6 to the parallel minor's Ab."""

	value = subsequence.progressions.progression([1, 6]).borrow(2).resolve("C")

	assert value.chords == (chord("C"), chord("Ab"))


def test_borrow_concrete_chord_raises () -> None:

	"""There is nothing relative to borrow on a concrete chord."""

	with pytest.raises(ValueError, match="relative"):
		subsequence.progressions.progression(["Am"]).borrow(1)


def test_replace_keeps_the_slot_beats () -> None:

	"""replace() swaps the chord; the span keeps its duration."""

	value = subsequence.progressions.progression([("Am", 6), "F"]).replace(1, "C")

	assert value.spans[0].chord == chord("C")
	assert value.spans[0].beats == 6.0


def test_with_rhythm_reshapes_spans () -> None:

	"""with_rhythm() rewrites span lengths, cycling a list."""

	value = subsequence.progressions.progression(["Am", "F", "C", "G"]).with_rhythm([4, 4, 2, 6])

	assert [span.beats for span in value.spans] == [4.0, 4.0, 2.0, 6.0]
	assert value.length == 16.0


def test_slot_arguments_are_one_based () -> None:

	"""Slot 0 raises — chords are counted, not indexed."""

	value = subsequence.progressions.progression(["Am", "F"])

	with pytest.raises(ValueError):
		value.replace(0, "C")
	with pytest.raises(ValueError):
		value.extend(7, only=[3])


def test_spice_preserves_trailing_history () -> None:

	"""Engine continuity metadata survives decoration."""

	value = subsequence.progressions.Progression(
		spans = (subsequence.progressions.ChordSpan(chord=chord("Am"), beats=4.0),),
		trailing_history = (chord("G"),),
	)

	assert value.extend(7).trailing_history == (chord("G"),)


# ---------------------------------------------------------------------------
# DecoratedChord — the voicing-layer wrapper
# ---------------------------------------------------------------------------

def test_decorated_chord_duck_types_the_chord_protocol () -> None:

	"""tones/intervals/name/root_note/bass_note all answer."""

	span = subsequence.progressions.progression(["Am"]).extend(9).spans[0]
	decorated = subsequence.progressions.DecoratedChord(span)

	assert decorated.intervals() == [0, 3, 7, 10, 14]
	assert decorated.name() == "Am9"
	assert decorated.root_note(60) == 57
	assert decorated.bass_note(60) == 45
	assert decorated.base == chord("Am")
	assert 57 in decorated.tones(60)


def test_iteration_yields_decorated_chords_where_spiced () -> None:

	"""Placement loops over a spiced progression hear the decoration."""

	value = subsequence.progressions.progression(["Am", "F"]).extend(7, only=[1])
	events = list(value)

	assert isinstance(events[0].chord, subsequence.progressions.DecoratedChord)
	assert isinstance(events[1].chord, subsequence.chords.Chord)


def test_slash_bass_note () -> None:

	"""bass_note() lands on the slash bass pitch class when one is set."""

	span = subsequence.progressions.progression(["C"]).over("G").spans[0].resolve(0)
	decorated = subsequence.progressions.DecoratedChord(span)

	assert decorated.bass_note(60) % 12 == 7


# ---------------------------------------------------------------------------
# PitchSet
# ---------------------------------------------------------------------------

def test_pitchset_tones_are_absolute () -> None:

	"""tones() ignores root — the pitches chose their own register."""

	cluster = subsequence.progressions.PitchSet([65, 60, 61])

	assert cluster.pitches == (60, 61, 65)
	assert cluster.tones(root=80) == [60, 61, 65]
	assert cluster.tones(count=5) == [60, 61, 65, 72, 73]
	assert cluster.intervals() == [0, 1, 5]


def test_pitchset_forces_loop_on_exhaustion () -> None:

	"""A progression containing a PitchSet must loop, never fall through."""

	value = subsequence.progressions.progression([
		"Am",
		subsequence.progressions.PitchSet([60, 61, 65]),
	])

	assert value.loops_on_exhaustion
	assert not subsequence.progressions.progression(["Am"]).loops_on_exhaustion


def test_empty_pitchset_raises () -> None:

	"""A PitchSet needs at least one pitch."""

	with pytest.raises(ValueError):
		subsequence.progressions.PitchSet([])


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------

def test_describe_prints_romans_unbound_and_names_under_a_key () -> None:

	"""Unbound: as written.  Keyed: concrete names.  Printed names re-enter."""

	value = subsequence.progressions.progression([1, "bVII7"])

	unbound = value.describe()
	keyed = value.describe(key="A", scale="minor")

	assert "1" in unbound and "bVII7" in unbound
	assert "Am" in keyed and "G7" in keyed

	# A printed concrete name re-enters as a list element.
	reentered = subsequence.progressions.progression(["G7"])
	assert reentered.chords[0] == chord("G7")


# ---------------------------------------------------------------------------
# realize() — the breathing path (absorbed from progression.py)
# ---------------------------------------------------------------------------

def test_realize_explicit_list_trims_to_length () -> None:

	"""The final chord is trimmed so the timeline loops cleanly."""

	value = subsequence.progressions.realize(
		["Am", "F", "C", "G"], WHOLE, None, 14.0, random.Random(0)
	)

	events = list(value)
	assert value.length == 14.0
	assert events[-1].length == 2.0
	assert events[-1].start == 12.0


def test_realize_list_rhythm_cycles () -> None:

	"""A list harmonic rhythm cycles per chord."""

	value = subsequence.progressions.realize(
		["Am", "F"], [2.0, 4.0], None, 12.0, random.Random(0)
	)

	assert [event.length for event in value] == [2.0, 4.0, 2.0, 4.0]


def test_realize_style_is_deterministic_under_a_seed () -> None:

	"""Same seed, same walk."""

	first = subsequence.progressions.realize("phrygian_minor", WHOLE, "C", 32.0, random.Random(7))
	second = subsequence.progressions.realize("phrygian_minor", WHOLE, "C", 32.0, random.Random(7))

	assert first.chords == second.chords


def test_realize_style_needs_key () -> None:

	"""A graph style without a key is an error."""

	with pytest.raises(ValueError, match="key"):
		subsequence.progressions.realize("phrygian_minor", WHOLE, None, 16.0, random.Random(0))


def test_realize_relative_elements_need_key () -> None:

	"""Degree elements in the breathing path resolve against the given key."""

	value = subsequence.progressions.realize([1, 6], WHOLE, "A", 8.0, random.Random(0), scale="minor")
	assert value.chords == (chord("Am"), chord("F"))

	with pytest.raises(ValueError, match="key"):
		subsequence.progressions.realize([1, 6], WHOLE, None, 8.0, random.Random(0))


def test_realize_progression_value_tiles_with_its_own_spans () -> None:

	"""A Progression source cycles its spans across the part."""

	source = subsequence.progressions.progression(["Am", "F"], beats=2)
	value = subsequence.progressions.realize(source, WHOLE, None, 8.0, random.Random(0))

	# harmonic_rhythm shapes lengths; the source supplies the chord cycle.
	assert value.chords == (chord("Am"), chord("F"))


def test_realize_ambiguous_tuple_rhythm_raises () -> None:

	"""(low, high) tuples must be spelled between(...) here."""

	with pytest.raises(ValueError, match="between"):
		subsequence.progressions.realize(["Am"], (2, 4), None, 8.0, random.Random(0))  # type: ignore[arg-type]


def test_realize_between_rhythm_is_bounded () -> None:

	"""between(...) lengths stay within their bounds."""

	spec = subsequence.harmonic_rhythm.between(2, 4)
	value = subsequence.progressions.realize("phrygian_minor", spec, "C", 64.0, random.Random(2))

	for event in value:
		assert 2.0 <= event.length <= 4.0 or event.start + event.length == 64.0


def test_resolve_voices_draws_in_range () -> None:

	"""(low, high) voicing draws stay within bounds; ints pass through."""

	rng = random.Random(0)

	assert subsequence.progressions.resolve_voices(3, rng) == 3
	for _ in range(20):
		assert 3 <= subsequence.progressions.resolve_voices((3, 5), rng) <= 5

	with pytest.raises(ValueError):
		subsequence.progressions.resolve_voices(0, rng)


# ---------------------------------------------------------------------------
# Progression.generate() — the hybrid generator (stage 3)
# ---------------------------------------------------------------------------

def test_generate_end_lands_the_cadential_dominant () -> None:

	"""end="V" — the chromatic major dominant in minor — lands on the last bar, every seed."""

	for seed in range(10):
		value = subsequence.progressions.Progression.generate(
			style="aeolian_minor", bars=4, end="V", seed=seed, key="A", scale="minor",
		)

		assert len(value) == 4
		assert value.chords[-1] == chord("E")		# major V in A minor
		assert value.chords[0] == chord("Am")		# the walk still starts home


def test_generate_keyless_is_relative_and_resolves_anywhere () -> None:

	"""Sketch (a): no key= → a key-relative value that prints romans and binds later."""

	value = subsequence.progressions.Progression.generate(
		style="aeolian_minor", bars=4, end="V", seed=7,
	)

	assert not value.is_concrete

	unbound = value.describe()
	assert "i" in unbound		# the tonic prints as a roman

	in_a = value.resolve("A", "minor")
	in_e = value.resolve("E", "minor")

	assert in_a.chords[0] == chord("Am") and in_a.chords[-1] == chord("E")
	assert in_e.chords[0] == chord("Em") and in_e.chords[-1] == chord("B")


def test_generate_is_key_invariant () -> None:

	"""The same seed in two keys walks the same shape, transposed — the relative emission's premise."""

	in_c = subsequence.progressions.Progression.generate(style="aeolian_minor", bars=8, seed=11, key="C", scale="minor")
	in_g = subsequence.progressions.Progression.generate(style="aeolian_minor", bars=8, seed=11, key="G", scale="minor")

	for c_chord, g_chord in zip(in_c.chords, in_g.chords):
		assert (g_chord.root_pc - c_chord.root_pc) % 12 == 7
		assert g_chord.quality == c_chord.quality


def test_generate_relative_resolution_matches_concrete_generation () -> None:

	"""Keyless-then-resolved equals generating concretely in that key (round trip)."""

	relative = subsequence.progressions.Progression.generate(style="aeolian_minor", bars=8, seed=3)
	concrete = subsequence.progressions.Progression.generate(style="aeolian_minor", bars=8, seed=3, key="A")

	assert relative.resolve("A", "minor").chords == concrete.chords


def test_generate_pins_fix_interior_bars () -> None:

	"""pins={bar: spec} compile into the walk — int degrees and romans both."""

	value = subsequence.progressions.Progression.generate(
		style="functional_major", bars=6, key="C", pins={3: 4, 5: "V7"}, seed=2,
	)

	assert value.chords[2] == chord("F")		# degree 4 in C major
	assert value.chords[4] == chord("G7")


def test_generate_pin_on_bar_one_overrides_the_tonic_start () -> None:

	"""pins={1: ...} sets where the walk begins."""

	value = subsequence.progressions.Progression.generate(
		style="functional_major", bars=4, key="C", pins={1: 6}, seed=5,
	)

	assert value.chords[0] == chord("Am")


def test_generate_avoid_excludes_everywhere () -> None:

	"""avoid=[...] never sounds, under any seed."""

	banned = chord("Am")

	for seed in range(10):
		value = subsequence.progressions.Progression.generate(
			style="functional_major", bars=8, key="C", avoid=["vi"], seed=seed,
		)
		assert banned not in value.chords


def test_generate_unsatisfiable_constraints_raise () -> None:

	"""Contradictory constraints fail loudly before any chord is drawn."""

	with pytest.raises(ValueError):
		subsequence.progressions.Progression.generate(
			style="functional_major", bars=4, key="C", end="V", avoid=["V"], seed=1,
		)


def test_generate_pin_outside_vocabulary_raises () -> None:

	"""A pin the style can never sound is named in the error."""

	with pytest.raises(ValueError, match="vocabulary"):
		subsequence.progressions.Progression.generate(
			style="functional_major", bars=4, key="C", pins={3: "F#m"}, seed=1,
		)


def test_generate_beats_shape_spans () -> None:

	"""beats= cycles per span, exactly as the factory's."""

	value = subsequence.progressions.Progression.generate(
		style="functional_major", bars=4, beats=[4, 2], key="C", seed=1,
	)

	assert [span.beats for span in value.spans] == [4.0, 2.0, 4.0, 2.0]


def test_generate_without_seed_warns () -> None:

	"""The standalone-generator seed policy applies."""

	with pytest.warns(UserWarning, match="seed"):
		subsequence.progressions.Progression.generate(style="functional_major", bars=2, key="C")


def test_factory_forwards_hybrid_constraints () -> None:

	"""progression(style=, end=, pins=, avoid=) is the same generator."""

	via_factory = subsequence.progressions.progression(
		style="aeolian_minor", bars=4, end="V", seed=7,
	)
	via_generate = subsequence.progressions.Progression.generate(
		style="aeolian_minor", bars=4, end="V", seed=7,
	)

	assert via_factory.resolve("A", "minor").chords == via_generate.resolve("A", "minor").chords


def test_generate_unconstrained_matches_stage_two_walk () -> None:

	"""No constraints → the walk consumes the RNG exactly as the plain engine would."""

	import subsequence.harmonic_state

	value = subsequence.progressions.Progression.generate(
		style="aeolian_minor", bars=6, key="A", seed=9,
	)

	state = subsequence.harmonic_state.HarmonicState(
		key_name="A", graph_style="aeolian_minor", rng=random.Random(9),
	)
	expected = [state.current_chord]
	for _ in range(5):
		expected.append(state.step())

	assert list(value.chords) == expected
