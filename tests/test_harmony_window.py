"""Composition-level tests for the harmony window wave.

Covers harmony(progression=) binding, freeze()'s span-based result,
pin_chord, the p.harmony view and injected-chord anticipation inside real
renders, the min-span/lookahead floor, and ChordTone placement end-to-end.
"""

import pathlib
import typing

import mido
import pytest

import subsequence
import subsequence.chords
import subsequence.progressions


# ---------------------------------------------------------------------------
# harmony(progression=) binding
# ---------------------------------------------------------------------------


def test_bind_resolves_degrees_against_key_and_scale(patch_midi: None) -> None:
    """Key-relative content resolves at bind time, against key + scale."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="A", scale="minor"
    )
    composition.harmony(progression=[1, 6, 3, 7])

    bound = composition._bound_progression

    assert bound is not None and bound.is_concrete
    assert [chord.name() for chord in bound.chords] == ["Am", "F", "C", "G"]


def test_bind_relative_without_key_raises(patch_midi: None) -> None:
    """Degrees cannot resolve without a composition key."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

    with pytest.raises(ValueError, match="key"):
        composition.harmony(progression=[1, 6, 3, 7])


def test_bind_concrete_chords_needs_no_key(patch_midi: None) -> None:
    """Chord names bind without a key, and no live engine is created."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
    composition.harmony(progression=["Am", "F"])

    assert composition._bound_progression is not None
    assert composition._harmonic_state is None  # progression-only: loop mode


def test_harmony_default_keeps_the_live_engine(patch_midi: None) -> None:
    """comp.harmony() with no arguments still means functional_major (compat)."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
    composition.harmony()

    assert composition._harmonic_state is not None
    assert composition._bound_progression is None


def test_style_plus_progression_keeps_both(patch_midi: None) -> None:
    """harmony(style=, progression=) configures the fall-through bridge."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
    composition.harmony(style="functional_major", progression=["Am", "F"])

    assert composition._harmonic_state is not None
    assert composition._bound_progression is not None


# ---------------------------------------------------------------------------
# freeze() — span-based capture
# ---------------------------------------------------------------------------


def test_freeze_returns_span_progression(patch_midi: None) -> None:
    """freeze() captures spans of cycle_beats each, with trailing history."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=42
    )
    composition.harmony(style="functional_major", cycle_beats=8)

    frozen = composition.freeze(4)

    assert isinstance(frozen, subsequence.Progression)
    assert len(frozen.spans) == 4
    assert all(span.beats == 8.0 for span in frozen.spans)
    assert frozen.is_concrete
    assert len(frozen.chords) == 4
    assert frozen.trailing_history  # NIR context captured


def test_frozen_value_takes_spice(patch_midi: None) -> None:
    """A frozen capture is an ordinary value — spice and editing apply."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=42
    )
    composition.harmony(cycle_beats=4)

    spiced = composition.freeze(4).extend(7).over("tonic")

    assert all(span.extensions == (7,) for span in spiced.spans)
    assert all(span.bass == "tonic" for span in spiced.spans)
    assert spiced.trailing_history  # metadata survives decoration


# ---------------------------------------------------------------------------
# section_chords coercion
# ---------------------------------------------------------------------------


def test_section_chords_accepts_element_lists(patch_midi: None) -> None:
    """section_chords coerces lists through the factory and keeps them RELATIVE.

    Key-relative section harmony re-keys per occurrence, so the stored value
    stays un-resolved (degrees/romans) and resolves late against the
    section's effective key.
    """

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="A", scale="minor"
    )
    composition.section_chords("verse", [1, 6])

    bound = composition._section_progressions["verse"]

    assert isinstance(bound, subsequence.Progression)
    assert not bound.is_concrete  # stored relative, not frozen at bind
    assert [chord.name() for chord in bound.resolve("A", "minor").chords] == ["Am", "F"]


# ---------------------------------------------------------------------------
# pin_chord
# ---------------------------------------------------------------------------


def test_pin_chord_stores_and_unpins(patch_midi: None) -> None:
    """Pins parse like progression elements; None removes them.

    Concrete pins resolve to their exact chord; a relative pin re-keys
    against the section in force (here, just the composition's A minor).
    """

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="A", scale="minor"
    )

    composition.pin_chord(8, "E7")
    assert composition._resolve_pin(8).name() == "E7"  # concrete: exact

    composition.pin_chord(8, 5)  # a degree pin re-keys against the effective key
    assert composition._resolve_pin(8).name() == "Em"  # degree 5 in A minor

    composition.pin_chord(8, None)
    assert 8 not in composition._pinned_chords


def test_pin_chord_validates(patch_midi: None) -> None:
    """Bars are 1-based; relative pins need a key."""

    keyless = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

    with pytest.raises(ValueError):
        keyless.pin_chord(0, "Am")
    with pytest.raises(ValueError, match="key"):
        keyless.pin_chord(4, 5)


# ---------------------------------------------------------------------------
# End-to-end: the window drives what actually sounds
# ---------------------------------------------------------------------------


def _note_pcs_by_bar(filename: str, ticks_per_bar: int) -> typing.Dict[int, set]:
    """Pitch classes of note_ons grouped by the bar they sound in."""

    mid = mido.MidiFile(filename)
    by_bar: typing.Dict[int, set] = {}

    for track in mid.tracks:
        now = 0
        for msg in track:
            now += msg.time
            if (
                not isinstance(msg, mido.MetaMessage)
                and msg.type == "note_on"
                and msg.velocity > 0
            ):
                by_bar.setdefault(now // ticks_per_bar, set()).add(msg.note % 12)

    return by_bar


def test_render_bound_progression_drives_the_chord_pattern(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """A two-parameter chord builder hears the bound progression, bar by bar, from bar 1."""

    filename = str(tmp_path / "bound.mid")
    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480)
    composition.harmony(progression=["Am", "F"])

    @composition.pattern(channel=1, beats=4)
    def pad(p, chord) -> None:
        for pitch in chord.tones(60):
            p.note(pitch, beat=0, duration=4)

    composition.render(bars=2, filename=filename)

    ticks_per_bar = mido.MidiFile(filename).ticks_per_beat * 4
    by_bar = _note_pcs_by_bar(filename, ticks_per_bar)

    assert by_bar[0] == {9, 0, 4}  # A minor — the FIRST chord sounds at bar 1
    assert by_bar[1] == {5, 9, 0}  # F major


def test_render_exposes_p_harmony_and_anticipation(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """Inside builds, p.harmony and the injected chord's window mirrors tell the truth."""

    filename = str(tmp_path / "window.mid")
    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480)
    composition.harmony(progression=["Am", "F", "C", "G"])

    seen: typing.List[
        typing.Tuple[str, typing.Optional[str], typing.Optional[float], str]
    ] = []

    @composition.pattern(channel=1, beats=4)
    def watcher(p, chord) -> None:
        next_name = chord.next.name() if chord.next is not None else None
        seen.append(
            (
                p.harmony.chord.name(),
                next_name,
                chord.beats_remaining,
                p.harmony.chord_at(2.0).name(),
            )
        )
        p.note(60, beat=0)

    composition.render(bars=3, filename=filename)

    assert seen[0] == ("Am", "F", 4.0, "Am")
    assert seen[1] == ("F", "C", 4.0, "F")
    assert seen[2] == ("C", "G", 4.0, "C")


def test_render_variable_harmonic_rhythm(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """Spans of 2 beats change chords mid-bar — the part hears each span via chord_at."""

    filename = str(tmp_path / "spans.mid")
    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480)
    composition.harmony(progression=subsequence.progression(["Am", "F"], beats=2))

    @composition.pattern(channel=1, beats=4)
    def stabs(p) -> None:
        for beat in (0.0, 2.0):
            chord = p.harmony.chord_at(beat)
            p.note(chord.tones(60)[0], beat=beat, duration=1)

    composition.render(bars=1, filename=filename)

    ticks_per_beat = mido.MidiFile(filename).ticks_per_beat
    by_half_bar = _note_pcs_by_bar(filename, ticks_per_beat * 2)

    assert by_half_bar[0] == {9}  # Am root in beats 0–2
    assert by_half_bar[1] == {5}  # F root in beats 2–4


def test_render_chord_tones_follow_the_changes(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """ChordTone motif events resolve against the chord under each event."""

    filename = str(tmp_path / "tones.mid")
    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480)
    composition.harmony(progression=subsequence.progression(["Am", "F"], beats=2))

    riff = subsequence.Motif.from_events(
        [
            subsequence.MotifEvent(
                beat=0.0, pitch=subsequence.ChordTone("root"), duration=1.0
            ),
            subsequence.MotifEvent(
                beat=2.0, pitch=subsequence.ChordTone("root"), duration=1.0
            ),
        ],
        length=4,
    )

    @composition.pattern(channel=1, beats=4)
    def lead(p) -> None:
        p.motif(riff, root=60)

    composition.render(bars=1, filename=filename)

    ticks_per_beat = mido.MidiFile(filename).ticks_per_beat
    by_half_bar = _note_pcs_by_bar(filename, ticks_per_beat * 2)

    assert by_half_bar[0] == {9}  # Am root
    assert by_half_bar[1] == {5}  # F root


def test_render_section_progressions_with_form(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """Section-bound progressions follow the form, restarting on entry."""

    filename = str(tmp_path / "sections.mid")
    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="C")
    composition.form([("verse", 2), ("chorus", 2)])
    composition.section_chords("verse", ["Am", "F"])
    composition.section_chords("chorus", ["C", "G"])

    @composition.pattern(channel=1, beats=4)
    def pad(p, chord) -> None:
        p.note(chord.tones(60)[0], beat=0, duration=4)

    composition.render(bars=4, filename=filename)

    ticks_per_bar = mido.MidiFile(filename).ticks_per_beat * 4
    by_bar = _note_pcs_by_bar(filename, ticks_per_bar)

    assert by_bar[0] == {9}  # verse: Am
    assert by_bar[1] == {5}  # verse: F
    assert by_bar[2] == {0}  # chorus: C — restarted at section entry
    assert by_bar[3] == {7}  # chorus: G


def test_min_span_below_lookahead_raises_at_play(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """The span floor: chords shorter than the largest pattern lookahead refuse to bind."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480)
    composition.harmony(progression=subsequence.progression(["Am", "F"], beats=0.5))

    @composition.pattern(channel=1, beats=4)
    def pad(p) -> None:
        p.note(60, beat=0)

    with pytest.raises(ValueError, match="span"):
        composition.render(bars=1, filename=str(tmp_path / "floor.mid"))


def test_current_chord_reads_the_window(patch_midi: None) -> None:
    """current_chord() answers in progression-only mode (no engine) before playback."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
    composition.harmony(progression=["Am", "F"])

    assert composition.current_chord() is None  # nothing published yet

    composition._harmony_horizon.commit(0.0, 4.0, subsequence.chords.parse_chord("Am"))

    assert composition.current_chord().name() == "Am"


# ---------------------------------------------------------------------------
# Sketch (a) — the acceptance contract, end to end (stage 3 completes it)
# ---------------------------------------------------------------------------


def test_sketch_a_verse_by_hand_chorus_generated_under_a_constraint(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """Verse hand-written (spiced), chorus generated with end="V", both bound and
    inspectable before play — sketch (a), as written in the design document."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=480, key="A", scale="minor", seed=42
    )

    verse = subsequence.progression([1, 6, 3, 7]).extend(9).borrow(2)
    chorus = subsequence.progression(style="aeolian_minor", bars=4, end="V", seed=7)

    # Both print before binding — degrees/romans unbound, names under a key.
    assert "9" in verse.describe()
    assert "V" in chorus.describe()
    assert not chorus.is_concrete

    composition.form([("verse", 4), ("chorus", 4)], loop=True)
    composition.section_chords("verse", verse)
    composition.section_chords("chorus", chorus)

    heard: typing.List[str] = []

    @composition.pattern(channel=1, beats=4)
    def pads(p, chord) -> None:
        heard.append(chord.name())
        p.note(60, beat=0)

    composition.render(bars=8, filename=str(tmp_path / "sketch_a.mid"))

    # Verse: i VI III VII in A minor, extended (9ths) with degree 2 borrowed
    # from the parallel major (VI of A major = F#m).
    assert heard[0] == "Am9"
    assert heard[1] == "F#m9"
    assert heard[2] == "C9"
    assert heard[3] == "G9"

    # Chorus: generated under the constraint — the last bar is the cadential
    # major dominant, resolved against the section's effective key at the
    # clock (the chorus has no key override, so the composition's A minor).
    assert heard[7] == "E"
    assert (
        composition._section_progressions["chorus"]
        .resolve("A", "minor")
        .chords[0]
        .name()
        == "Am"
    )
