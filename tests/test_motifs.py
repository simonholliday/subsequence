"""
The Motif/Phrase value layer: constructors, the combination algebra and its
laws, transforms (notes and control gestures), and the standard-form rules.
"""

import dataclasses

import pytest

import subsequence
import subsequence.motifs


M = subsequence.Motif
P = subsequence.Phrase
Degree = subsequence.Degree
ChordTone = subsequence.ChordTone
Approach = subsequence.Approach
MotifEvent = subsequence.MotifEvent
ControlEvent = subsequence.ControlEvent


def _beats(m: M) -> list:
    """Onset beats of a motif's note events."""

    return [e.beat for e in m.events]


def _pitches(m: M) -> list:
    """Pitch specs of a motif's note events."""

    return [e.pitch for e in m.events]


# ── constructors: the standard form ─────────────────────────────────────────


def test_degrees_one_per_beat_with_rests() -> None:
    """Ints are 1-based degrees, one per beat; None is a rest whose slot still advances."""

    m = M.degrees([5, 6, None, 3])

    assert _beats(m) == [0.0, 1.0, 3.0]
    assert _pitches(m) == [Degree(5), Degree(6), Degree(3)]
    assert m.length == 4.0


def test_degrees_durations_default_to_a_full_beat() -> None:
    """A written melody holds each beat slot by default."""

    m = M.degrees([1, 2])

    assert all(e.duration == 1.0 for e in m.events)


def test_degrees_length_covers_held_final_note() -> None:
    """Length defaults to the next whole beat after the last ring-out."""

    m = subsequence.motif([1, 3, 5, 6, 5, 3, 2], durations=[1, 1, 1, 1, 1, 1, 2])

    assert m.length == 8.0


def test_degrees_rejects_pasted_midi() -> None:
    """Implausibly large ints fail loud — they are MIDI notes, not degrees."""

    with pytest.raises(ValueError, match="Motif.notes"):
        subsequence.motif([60, 62, 64])


def test_degree_steps_are_one_based() -> None:
    """Degree 0 does not exist; musicians count from one."""

    with pytest.raises(ValueError, match="1-based"):
        Degree(0)


def test_lowercase_factory_is_degrees() -> None:
    """subsequence.motif([...]) means scale degrees — relative pitch is primary."""

    assert subsequence.motif([1, 5]) == M.degrees([1, 5])


def test_notes_are_absolute_midi() -> None:
    """Motif.notes ints pass through as MIDI."""

    m = M.notes([60, None, 64])

    assert _pitches(m) == [60, 64]
    assert _beats(m) == [0.0, 2.0]


def test_hits_places_one_pitch_at_beats() -> None:
    """The hit() convention: a drum name at a list of onsets, explicit length."""

    m = M.hits("kick", beats=[0, 1.5, 3], length=4)

    assert _pitches(m) == ["kick"] * 3
    assert _beats(m) == [0.0, 1.5, 3.0]
    assert m.length == 4.0


def test_steps_are_grid_indices() -> None:
    """The sequence() convention: 0-based sixteenth-grid indices by default."""

    m = M.steps([0, 4, 8, 12], pitches="kick")

    assert _beats(m) == [0.0, 1.0, 2.0, 3.0]
    assert m.length == 4.0


def test_steps_parallel_pitch_list() -> None:
    """Multi-voice drum figures via a parallel pitches list."""

    m = M.steps([0, 4], pitches=["kick", "snare"])

    assert _pitches(m) == ["kick", "snare"]


def test_parallel_list_mismatch_raises() -> None:
    """Parallel lists must match the sequence length — no silent recycling in values."""

    with pytest.raises(ValueError, match="parallel"):
        M.degrees([1, 2, 3], velocities=[100, 90])


def test_euclidean_constructor() -> None:
    """A euclidean rhythm as a value: pulses spread across the grid over length beats."""

    m = M.euclidean(4, 16, "kick", length=4)

    assert _beats(m) == [0.0, 1.0, 2.0, 3.0]
    assert m.length == 4.0


def test_chord_tone_names() -> None:
    """'root'/'third'/'fifth'/'seventh' are sugar for 1-based indices."""

    assert ChordTone("root") == ChordTone(1)
    assert ChordTone("seventh") == ChordTone(4)

    with pytest.raises(ValueError, match="ninth"):
        ChordTone("ninth")


def test_values_are_hashable_and_structurally_equal() -> None:
    """Frozen values: equal content, equal value, usable as dict keys."""

    a = M.hits("kick", beats=[0, 2], length=4)
    b = M.hits("kick", beats=[0, 2], length=4)

    assert a == b
    assert hash(a) == hash(b)
    assert {a: "x"}[b] == "x"


# ── control-gesture constructors ────────────────────────────────────────────


def test_cc_discrete_writes() -> None:
    """Discrete CC writes via parallel value/beat lists."""

    m = M.cc("cutoff", [20, 60, 110], beats=[0, 1, 2], length=4)

    assert len(m.controls) == 3
    assert m.events == ()
    assert m.controls[0].signal == subsequence.motifs.CC("cutoff")
    assert m.controls[0].end is None


def test_cc_ramp_value() -> None:
    """A shaped sweep as a value; beat_end defaults from length."""

    m = M.cc_ramp(74, 20, 110, length=4)
    ramp = m.controls[0]

    assert (ramp.start, ramp.end, ramp.span) == (20.0, 110.0, 4.0)
    assert m.length == 4.0


def test_ramp_needs_an_end() -> None:
    """A ramp with neither beat_end nor length is unconstructible."""

    with pytest.raises(ValueError, match="beat_end"):
        M.cc_ramp(74, 0, 127)


def test_nrpn_flags_travel() -> None:
    """fine/null_reset ride the signal into the value."""

    m = M.nrpn_ramp(9, 0, 1400, beat_end=4)

    assert m.controls[0].signal.fine is True
    assert m.controls[0].signal.null_reset is True


def test_control_event_invariants() -> None:
    """end= and span= come together or not at all."""

    with pytest.raises(ValueError):
        ControlEvent(beat=0.0, signal=subsequence.motifs.CC(74), start=0.0, end=100.0)


# ── the algebra ─────────────────────────────────────────────────────────────


def test_add_lifts_to_phrase() -> None:
    """Motif + Motif is a two-segment Phrase; segmentation is preserved."""

    a = M.hits("kick", beats=[0], length=4)
    b = M.hits("snare", beats=[0], length=4)
    phrase = a + b

    assert isinstance(phrase, P)
    assert phrase.segments == (a, b)
    assert phrase.length == 8.0


def test_then_is_the_closed_concat() -> None:
    """then() glues two cells into ONE longer motif, shifting the right operand."""

    a = M.hits("kick", beats=[0], length=4)
    b = M.hits("snare", beats=[1], length=4)
    glued = a.then(b)

    assert isinstance(glued, M)
    assert glued.length == 8.0
    assert _beats(glued) == [0.0, 5.0]


def test_join_folds_with_then() -> None:
    """Motif.join is the n-ary then; the empty motif is its identity."""

    a = M.hits("kick", beats=[0], length=2)

    assert M.join([a, a, a]).length == 6.0
    assert M.join([]) == M.empty()
    assert M.empty().then(a) == a


def test_multiplication_laws() -> None:
    """m*0 is empty, m*1 is m, m*n is an n-segment Phrase."""

    m = M.hits("kick", beats=[0], length=4)

    assert m * 0 == M.empty()
    assert m * 1 is m
    assert (m * 3).segments == (m, m, m)
    assert 2 * m == m * 2


def test_parallel_merge_semantics() -> None:
    """& is event union with length = max and no implicit tiling."""

    long = M.hits("kick", beats=[0, 2], length=4)
    short = M.hits("snare", beats=[1], length=2)
    merged = long & short

    assert merged.length == 4.0
    assert len(merged.events) == 3
    assert _beats(merged) == [0.0, 1.0, 2.0]  # the short one plays once — no tiling


def test_parallel_merge_is_commutative_and_associative() -> None:
    """Canonical event ordering makes & order-independent."""

    a = M.hits("kick", beats=[0], length=4)
    b = M.hits("snare", beats=[1], length=4)
    c = M.cc_ramp(74, 0, 127, length=4)

    assert a & b == b & a
    assert (a & b) & c == a & (b & c)


def test_stack_is_the_spelled_form() -> None:
    """a.stack(b) == a & b."""

    a = M.hits("kick", beats=[0], length=4)
    b = M.hits("snare", beats=[1], length=4)

    assert a.stack(b) == a & b


def test_merge_carries_controls() -> None:
    """Stacking a control-only motif packages the gesture with the figure."""

    riff = M.notes([60, 63], length=4)
    sweep = M.cc_ramp(74, 20, 110, beat_end=4)
    acid = riff & sweep

    assert len(acid.events) == 2
    assert len(acid.controls) == 1


def test_adding_non_music_raises() -> None:
    """The algebra is closed over the sounding family."""

    with pytest.raises(TypeError):
        M.empty() + 3


def test_slice_is_a_window() -> None:
    """Events outside drop; straddlers truncate at the cut; beats shift to zero."""

    m = M.notes([60, 62, 64, 65], durations=[1.0, 1.0, 1.0, 2.0])
    window = m.slice(1, 4)

    assert _pitches(window) == [62, 64, 65]
    assert _beats(window) == [0.0, 1.0, 2.0]
    assert window.length == 3.0
    assert window.events[-1].duration == 1.0  # the held final note is cut at the edge


def test_slice_truncates_ramps_at_interpolated_value() -> None:
    """A straddling ramp ends at its interpolated cut value."""

    m = M.cc_ramp(74, 0, 100, beat_end=4)
    window = m.slice(0, 2)
    ramp = window.controls[0]

    assert ramp.span == 2.0
    assert ramp.end == 50.0


# ── transform laws (the test-suite backbone) ────────────────────────────────


def test_reverse_law_over_addition() -> None:
    """(a + b).reverse() == b.reverse() + a.reverse()."""

    a = M.degrees([1, 3], length=2)
    b = M.degrees([5, 6, 5], length=3)

    assert (a + b).reverse() == b.reverse() + a.reverse()


def test_reverse_is_an_involution() -> None:
    """Reversing twice restores the motif."""

    m = M.degrees([1, 3, 5], durations=[0.5, 1.0, 0.25])

    assert m.reverse().reverse() == m


def test_reverse_mirrors_ramps() -> None:
    """A rising sweep becomes a falling one."""

    sweep = M.cc_ramp(74, 20, 110, beat_end=4)
    back = sweep.reverse().controls[0]

    assert (back.start, back.end) == (110.0, 20.0)


def test_transpose_distributes_over_merge_and_addition() -> None:
    """Pitch transforms distribute over & and +."""

    a = M.degrees([1, 3], length=2)
    b = M.degrees([5], length=2)

    assert (a & b).transpose(steps=2) == a.transpose(steps=2) & b.transpose(steps=2)
    assert (a + b).transpose(steps=2) == a.transpose(steps=2) + b.transpose(steps=2)


def test_stretch_distributes_over_then() -> None:
    """Stretch scales the whole timeline coherently."""

    a = M.degrees([1], length=2)
    b = M.degrees([5], length=2)

    assert a.then(b).stretch(2.0) == a.stretch(2.0).then(b.stretch(2.0))


def test_flatten_is_a_homomorphism() -> None:
    """Phrase.flatten() maps (+) onto (then)."""

    a = M.degrees([1, 3], length=2)
    b = M.degrees([5], length=2)

    assert (a + b).flatten() == a.then(b)


def test_rotate_is_whole_span_modular() -> None:
    """Onsets wrap modulo the length; rotating by the length is identity."""

    m = M.hits("kick", beats=[0, 1, 3], length=4)

    assert _beats(m.rotate(1)) == [0.0, 1.0, 2.0]
    assert m.rotate(4) == m


# ── transforms: behaviour ───────────────────────────────────────────────────


def test_stretch_scales_everything() -> None:
    """Beats, durations, spans, and length scale together."""

    m = M.notes([60], durations=[1.0]) & M.cc_ramp(74, 0, 127, beat_end=1)
    wide = m.stretch(2.0)

    assert wide.length == 2.0
    assert wide.events[0].duration == 2.0
    assert wide.controls[0].span == 2.0


def test_quantize_snaps_notes_only() -> None:
    """Note onsets snap to the grid; control gestures keep their timing."""

    m = M.from_events(
        [MotifEvent(beat=1.07, pitch=60)],
        length=4,
        controls=(
            ControlEvent(beat=1.07, signal=subsequence.motifs.CC(74), start=64.0),
        ),
    )
    snapped = m.quantize(0.25)

    assert snapped.events[0].beat == 1.0
    assert snapped.controls[0].beat == 1.07


def test_accent_boosts_at_beat_position() -> None:
    """accent() takes a 0-based beat position, not a note count."""

    m = M.degrees([1, 5], velocities=100)
    accented = m.accent(1.0, amount=20)

    assert [e.velocity for e in accented.events] == [100, 120]


def test_with_velocity_replaces_all() -> None:
    """Uniform velocity replacement, tuples allowed."""

    m = M.degrees([1, 5]).with_velocity((60, 90))

    assert all(e.velocity == (60, 90) for e in m.events)


def test_pitched_turns_rhythm_into_line() -> None:
    """kick.pitched('root') — same rhythm, chord-tone pitches."""

    bass = M.hits("kick", beats=[0, 1.5, 3], length=4).pitched("root")

    assert _pitches(bass) == [ChordTone(1)] * 3
    assert _beats(bass) == [0.0, 1.5, 3.0]


def test_rhythm_strips_pitches_and_controls() -> None:
    """A skeleton keeps timing/velocity/duration; pitches and gestures go."""

    m = (
        M.degrees([1, 5], velocities=[100, 80]) & M.cc_ramp(74, 0, 127, beat_end=2)
    ).rhythm()

    assert _pitches(m) == [None, None]
    assert [e.velocity for e in m.events] == [100, 80]
    assert m.controls == ()


def test_onsets_accessor() -> None:
    """onsets() hands the beat list to rhythm-first generation."""

    assert M.hits("kick", beats=[0, 1.5, 3], length=4).onsets() == [0.0, 1.5, 3.0]


def test_transpose_steps_moves_degrees() -> None:
    """Diatonic sequencing: degrees shift by scale steps."""

    m = subsequence.motif([5, 6, 5, 3]).transpose(steps=2)

    assert _pitches(m) == [Degree(7), Degree(8), Degree(7), Degree(5)]


def test_transpose_steps_raises_on_absolute_content() -> None:
    """MIDI ints have no degrees; the unit keyword protects the meaning."""

    with pytest.raises(TypeError, match="semitones"):
        M.notes([60, 62]).transpose(steps=2)


def test_transpose_semitones_is_chromatic() -> None:
    """MIDI shifts literally; degrees gain chroma."""

    assert _pitches(M.notes([60]).transpose(semitones=3)) == [63]
    assert _pitches(M.degrees([5]).transpose(semitones=1)) == [Degree(5, chroma=1)]


def test_transpose_drums_raise_on_both() -> None:
    """A transposed drum name is a different instrument, not a transposition."""

    kick = M.hits("kick", beats=[0], length=1)

    with pytest.raises(TypeError):
        kick.transpose(steps=1)
    with pytest.raises(TypeError):
        kick.transpose(semitones=1)


def test_transpose_takes_exactly_one_unit() -> None:
    """steps= or semitones=, never both, never neither."""

    m = M.degrees([1])

    with pytest.raises(ValueError):
        m.transpose()
    with pytest.raises(ValueError):
        m.transpose(steps=1, semitones=1)


def test_transpose_reaches_into_approach() -> None:
    """Approach targets move with the transposition."""

    m = M.from_events([MotifEvent(beat=0.0, pitch=Approach(Degree(5)))], length=1)

    assert _pitches(m.transpose(steps=2)) == [Approach(Degree(7))]


def test_invert_mirrors_around_pivot() -> None:
    """T/I/R serial group: absolute content mirrors around a MIDI pivot."""

    m = M.notes([60, 64, 67]).invert()

    assert _pitches(m) == [60, 56, 53]


def test_invert_degrees() -> None:
    """Degree content mirrors around a degree pivot."""

    m = M.degrees([1, 3, 5]).invert(pivot=3)

    assert _pitches(m) == [Degree(5), Degree(3), Degree(1)]


def test_invert_reflects_degree_octaves() -> None:
    """A degree's register flips under inversion: an octave up lands an octave down.

    Regression: ``invert`` used to mirror only ``step`` and leave ``octave``
    untouched, so an octave-bearing degree inverted to itself (wrong pitch).
    """

    m = subsequence.motif([1, Degree(1, octave=1)]).invert(pivot=1)

    assert _pitches(m) == [Degree(1, octave=0), Degree(1, octave=-1)]


def test_controls_ignore_pitch_transforms() -> None:
    """Transposing a riff does not rescale its bend depths."""

    acid = M.degrees([1, 5]) & M.pitch_bend_ramp(0.0, -0.5, beat_end=2)

    assert acid.transpose(steps=2).controls == acid.controls


# ── Phrase ──────────────────────────────────────────────────────────────────


def test_phrase_length_and_flatten_offsets() -> None:
    """Length sums segments; flatten shifts each segment to its offset."""

    a = M.hits("kick", beats=[0], length=4)
    b = M.hits("snare", beats=[1], length=4)
    phrase = P([a, b])

    assert phrase.length == 8.0
    assert _beats(phrase.flatten()) == [0.0, 5.0]


def test_phrase_addition_and_tiling() -> None:
    """Phrase + Motif appends; Phrase + Phrase concatenates; * tiles."""

    a = M.degrees([1], length=1)
    b = M.degrees([5], length=1)

    assert (P([a]) + b).segments == (a, b)
    assert (P([a]) + P([b])).segments == (a, b)
    assert (a + (P([b]))).segments == (a, b)
    assert (P([a, b]) * 2).segments == (a, b, a, b)


def test_phrase_merge_flattens_first() -> None:
    """Parallel merge is vertical — segmentation is erased honestly."""

    a = M.degrees([1], length=2)
    b = M.degrees([5], length=2)
    merged = P([a, b]) & M.hits("kick", beats=[0], length=4)

    assert isinstance(merged, M)
    assert merged.length == 4.0


def test_phrase_replace_is_one_based() -> None:
    """Musicians count segments from one."""

    a = M.degrees([1], length=1)
    b = M.degrees([5], length=1)
    swapped = P([a, a]).replace(2, b)

    assert swapped.segments == (a, b)

    with pytest.raises(IndexError, match="1-based"):
        P([a]).replace(0, b)


def test_phrase_reverse_law() -> None:
    """Reverse acts on the whole timeline and re-segments (the lifted law)."""

    a = M.degrees([1, 3], length=2)
    b = M.degrees([5], length=2)

    assert (a + b).reverse() == P([b.reverse(), a.reverse()])


def test_phrase_rotate_resegments_keeping_durations() -> None:
    """Rotation re-segments by onset; a note may ring past its new boundary."""

    a = M.notes([60], durations=[2.0], length=2)
    b = M.notes([72], durations=[2.0], length=2)
    rotated = (a + b).rotate(1)

    assert rotated.length == 4.0
    flat = rotated.flatten()
    assert _beats(flat) == [1.0, 3.0]
    assert all(e.duration == 2.0 for e in flat.events)


def test_phrase_lifts_pitch_transforms_segment_wise() -> None:
    """Non-time transforms apply per segment, preserving segmentation."""

    a = M.degrees([1], length=1)
    b = M.degrees([5], length=1)

    assert P([a, b]).transpose(steps=1).segments == (
        a.transpose(steps=1),
        b.transpose(steps=1),
    )


def test_phrase_slice_resegments_at_cuts() -> None:
    """Slicing a phrase windows each overlapped segment."""

    a = M.degrees([1, 2], length=2)
    b = M.degrees([5, 6], length=2)
    window = (a + b).slice(1, 3)

    assert window.length == 2.0
    assert len(window.segments) == 2
    assert _pitches(window.flatten()) == [Degree(2), Degree(5)]


def test_describe_smoke() -> None:
    """Every value prints something readable."""

    acid = M.hits("kick", beats=[0], length=4).pitched("root") & M.cc_ramp(
        74, 20, 110, beat_end=4
    )

    assert "tone1" in str(acid)
    assert "CC74" in str(acid)
    assert "segments" in str(acid * 2)
