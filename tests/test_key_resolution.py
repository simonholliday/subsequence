"""Tests for the key-resolution consistency model (the three intents).

The contract: *how you spell the content is the key contract.*
- **Absolute** content (note names, MIDI pitches, PitchSet, frozen captures)
  is never moved by any key.
- **Key-relative** content (degrees, romans, generated relative material,
  key-relative section progressions) resolves against the effective key —
  layered ``Section.key`` > form key > composition key, with mode following
  the same chain.
- **Chord-relative** content (ChordTone, Approach-at-chord-tone, fit) tracks
  the sounding chord, independent of key.

Plus the three audit bug-fixes: trigger() honours the key, transition fills
use the section key, and a persistent MelodicState follows the section key.
"""

import pathlib
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.composition
import subsequence.form_state
import subsequence.melodic_state


def _placed_pitches(
    composition: "subsequence.composition.Composition", index: int = 0
) -> typing.List[int]:
    """Build the pending pattern at *index* and return the MIDI note numbers it placed."""

    pattern = composition._build_pattern_from_pending(
        composition._pending_patterns[index]
    )
    return [note.pitch for step in pattern.steps.values() for note in step.notes]


# ---------------------------------------------------------------------------
# Absolute content is never moved by a key
# ---------------------------------------------------------------------------


def test_absolute_notes_ignore_section_key(patch_midi: None) -> None:
    """MIDI note atoms stay put regardless of the section key."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form(subsequence.Form([subsequence.Section("verse", 4, key="A")]))

    @composition.pattern(channel=1, beats=4)
    def lead(p: typing.Any) -> None:
        p.motif(subsequence.Motif.notes([60, 64, 67]), root=60)

    assert _placed_pitches(composition) == [60, 64, 67]


def test_chord_name_progression_ignores_section_key(patch_midi: None) -> None:
    """A name-spelled progression is absolute — the section key does not move it."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.section_chords("verse", ["Am", "F"])

    bound = composition._section_progressions["verse"]
    assert bound.is_concrete  # names froze at parse — nothing to re-key

    info = subsequence.form_state.SectionInfo(
        name="verse", bar=0, bars=4, index=0, key="A"
    )
    resolved = composition._resolve_section_progression(info)
    assert resolved is not None
    assert [c.name() for c in resolved.chords] == [
        "Am",
        "F",
    ]  # still A minor / F, not transposed


# ---------------------------------------------------------------------------
# Key-relative content: the layered effective key, and mode travel
# ---------------------------------------------------------------------------


def test_effective_key_precedence() -> None:
    """Section > form > composition, key and scale resolved independently."""

    comp = subsequence.composition.Composition.__new__(
        subsequence.composition.Composition
    )
    comp.key = "C"
    comp.scale = "major"
    comp._form_key = None
    comp._form_scale = None

    S = subsequence.form_state.SectionInfo

    # Nothing overrides → composition.
    assert comp._effective_key_scale(S("v", 0, 4, 0)) == ("C", "major")

    # Form tier overrides composition.
    comp._form_key, comp._form_scale = "G", None
    assert comp._effective_key_scale(S("v", 0, 4, 0)) == (
        "G",
        "major",
    )  # scale falls to composition

    # Section overrides form; key and scale independent.
    assert comp._effective_key_scale(S("v", 0, 4, 0, key="A", scale="minor")) == (
        "A",
        "minor",
    )
    assert comp._effective_key_scale(S("v", 0, 4, 0, key="A")) == (
        "A",
        "major",
    )  # tonic moves, mode stays


def test_section_key_re_anchors_degrees(patch_midi: None) -> None:
    """Degree 1 follows the section key."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form(subsequence.Form([subsequence.Section("verse", 4, key="D")]))

    @composition.pattern(channel=1, beats=4)
    def lead(p: typing.Any) -> None:
        p.motif(subsequence.motif([1]), root=60)

    assert _placed_pitches(composition) == [62]  # D, nearest middle C


def test_section_mode_travels(patch_midi: None) -> None:
    """Section.scale moves the mode: degree 3 of A minor is C, not C#."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.form(
        subsequence.Form([subsequence.Section("verse", 4, key="A", scale="minor")])
    )

    @composition.pattern(channel=1, beats=4)
    def lead(p: typing.Any) -> None:
        p.motif(subsequence.motif([3]), root=60)

    # Degree 3 in A minor = C (60); in A major it would be C# (61).
    assert _placed_pitches(composition) == [60]


def test_form_key_tier(patch_midi: None) -> None:
    """A form key re-anchors degrees when no section key overrides it."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form([("verse", 4)], key="E")

    @composition.pattern(channel=1, beats=4)
    def lead(p: typing.Any) -> None:
        p.motif(subsequence.motif([1]), root=60)

    assert _placed_pitches(composition) == [64]  # E


def test_form_value_carries_its_own_key(patch_midi: None) -> None:
    """A Form(key=...) seeds the form tier; an explicit form(key=) overrides it."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form(subsequence.Form([subsequence.Section("verse", 4)], key="E"))
    assert composition._form_key == "E"

    composition.form(
        subsequence.Form([subsequence.Section("verse", 4)], key="E"), key="G"
    )
    assert composition._form_key == "G"  # explicit argument wins


# ---------------------------------------------------------------------------
# The headline case: a relative section progression re-keys per occurrence
# ---------------------------------------------------------------------------


def test_relative_section_progression_re_keys(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """The truck-driver's modulation: same numbered progression, two keys, two sections."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=480, key="C", scale="major", seed=1
    )
    composition.form(
        subsequence.Form(
            [
                subsequence.Section("chorus", 4),
                subsequence.Section("chorus2", 4, key="D"),
            ]
        )
    )

    prog = subsequence.progression([1, 4, 5, 1])
    composition.section_chords("chorus", prog)
    composition.section_chords("chorus2", prog)  # the SAME relative value

    heard: typing.List[typing.Tuple[str, str]] = []

    @composition.pattern(channel=1, beats=4)
    def pads(p, chord) -> None:
        heard.append((p.section.name if p.section else "?", chord.name()))
        p.note(60, beat=0)

    composition.render(bars=8, filename=str(tmp_path / "m.mid"))

    chorus = [name for section, name in heard if section == "chorus"]
    chorus2 = [name for section, name in heard if section == "chorus2"]

    assert chorus[0] == "C"  # I-IV-V-I in C
    assert chorus2[0] == "D"  # the SAME numbers, a tone up in D
    assert chorus2[:4] == ["D", "G", "A", "D"]


def test_section_key_moves_melody_and_chords_together(
    tmp_path: pathlib.Path, patch_midi: None
) -> None:
    """Within one re-keyed section, the degree melody and the numbered chords share a tonic."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=480, key="C", scale="major", seed=1
    )
    composition.form(
        subsequence.Form([subsequence.Section("verse", 4, key="A", scale="minor")])
    )
    composition.section_chords("verse", subsequence.progression([1]))

    roots: typing.List[int] = []
    chord_roots: typing.List[str] = []

    @composition.pattern(channel=1, beats=4)
    def lead(p, chord) -> None:
        chord_roots.append(chord.name())
        p.motif(subsequence.motif([1]), root=60)
        roots.extend(
            note.pitch for step in p._pattern.steps.values() for note in step.notes
        )

    composition.render(bars=2, filename=str(tmp_path / "v.mid"))

    assert roots and roots[0] == 57  # degree 1 melody = A (nearest 60)
    assert chord_roots[0] == "Am"  # degree-1 chord = A minor — same tonic


def test_section_fall_through_uses_composition_key(patch_midi: None) -> None:
    """A re-keyed section that exhausts hands off to the live engine in the composition key."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.harmony(style="functional_major", cycle_beats=4)
    composition.form(subsequence.Form([subsequence.Section("verse", 8, key="D")]))
    composition.section_chords(
        "verse", subsequence.progression([1, 4])
    )  # only 2 bars of an 8-bar section

    info = subsequence.form_state.SectionInfo(
        name="verse", bar=0, bars=8, index=0, key="D"
    )
    resolved = composition._resolve_section_progression(info)

    assert resolved is not None
    assert [c.name() for c in resolved.chords] == [
        "D",
        "G",
    ]  # the written bars are in D
    # Bars 3-8 fall through to the live engine, which is fixed in C (documented).
    assert composition._harmonic_state is not None
    assert composition._harmonic_state.key_root_pc == subsequence.chords.key_name_to_pc(
        "C"
    )


def test_relative_section_no_key_raises_at_run(patch_midi: None) -> None:
    """A key-relative section progression with no resolvable key fails at play/render, clearly."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, seed=1
    )  # no key
    composition.form([("verse", 4)])
    composition.section_chords("verse", subsequence.progression([1, 4, 5]))

    with pytest.raises(ValueError, match="no key resolves"):
        composition.render(bars=4, filename="unused.mid")


# ---------------------------------------------------------------------------
# Determinism: re-keying is a pure function, reproducible
# ---------------------------------------------------------------------------


def test_re_keying_is_deterministic(tmp_path: pathlib.Path, patch_midi: None) -> None:
    """Same seed + same key → byte-identical render (deferred resolution stays pure)."""

    def render(path: str) -> bytes:
        composition = subsequence.Composition(
            output_device="Dummy MIDI", bpm=480, key="C", scale="major", seed=7
        )
        composition.form(
            subsequence.Form([subsequence.Section("v", 4, key="A", scale="minor")])
        )
        composition.section_chords("v", subsequence.progression([1, 4, 5, 1]))

        @composition.pattern(channel=1, beats=4)
        def pads(p, chord) -> None:
            p.chord(chord, root=48, beat=0)

        composition.render(bars=4, filename=path)
        return pathlib.Path(path).read_bytes()

    assert render(str(tmp_path / "a.mid")) == render(str(tmp_path / "b.mid"))


def test_resolution_cache_reuses_one_realisation(patch_midi: None) -> None:
    """Repeated resolution of a stable section returns the same object (memoised)."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.section_chords("verse", subsequence.progression([1, 4]))

    info = subsequence.form_state.SectionInfo(
        name="verse", bar=0, bars=4, index=0, key="A", scale="minor"
    )
    first = composition._resolve_section_progression(info)
    second = composition._resolve_section_progression(info)
    assert first is second  # memoised by (name, key, scale)


# ---------------------------------------------------------------------------
# Bug fixes the audit surfaced
# ---------------------------------------------------------------------------


def test_trigger_honours_the_key(patch_midi: None) -> None:
    """A degree in a one-shot resolves against the effective key (was: raised)."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="D", seed=1
    )

    placed: typing.List[int] = []
    composition._schedule_one_shot = lambda pattern, start_pulse: placed.extend(  # type: ignore[method-assign]
        note.pitch for step in pattern.steps.values() for note in step.notes
    )

    composition.trigger(lambda p: p.motif(subsequence.motif([1]), root=60), channel=1)
    assert placed == [62]  # degree 1 of D — no longer a crash


def test_trigger_uses_section_key(patch_midi: None) -> None:
    """A one-shot fired during a re-keyed section uses that section's key."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form(subsequence.Form([subsequence.Section("verse", 4, key="A")]))

    placed: typing.List[int] = []
    composition._schedule_one_shot = lambda pattern, start_pulse: placed.extend(  # type: ignore[method-assign]
        note.pitch for step in pattern.steps.values() for note in step.notes
    )

    composition.trigger(lambda p: p.motif(subsequence.motif([1]), root=60), channel=1)
    assert placed == [57]  # degree 1 of A (nearest 60)


def test_transition_fill_uses_section_key(patch_midi: None) -> None:
    """A degree-bearing fill resolves against the section it sounds in (was: composition key)."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form(
        subsequence.Form(
            [subsequence.Section("verse", 2, key="A"), subsequence.Section("chorus", 2)]
        )
    )
    composition.transition(
        before="*", fill=subsequence.motif([1], length=2), channel=1, beat=0.0
    )

    fired: typing.List[int] = []
    composition._schedule_one_shot = lambda pattern, start_pulse: fired.extend(  # type: ignore[method-assign]
        note.pitch for step in pattern.steps.values() for note in step.notes
    )

    state = composition._form_state
    assert state is not None
    state.advance()  # into verse bar 1 (the last bar before chorus)
    composition._check_transitions(96, False)

    assert fired == [57]  # degree 1 of the verse's A, not C


def test_pin_re_keys_to_the_pinned_bars_section_not_the_playhead(
    patch_midi: None,
) -> None:
    """A relative pin in a later, differently-keyed section keys to THAT section.

    Regression for the review's HIGH finding: the clock's lookahead reads a
    future bar's pin while the playhead is still in an earlier section, so
    _resolve_pin must key the pin to the section that owns the bar.
    """

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.form(
        subsequence.Form(
            [
                subsequence.Section("verse", 8, key="C"),
                subsequence.Section("chorus", 8, key="Eb"),
            ]
        )
    )
    composition.pin_chord(9, "V")  # bar 9 is the chorus (Eb) — V of Eb is Bb (pc 10)

    # Regardless of where the playhead is, bar 9's pin resolves in Eb.
    assert composition._resolve_pin(9).root_pc == subsequence.chords.key_name_to_pc(
        "Bb"
    )

    # And a pin in the verse keys to C.
    composition.pin_chord(2, "V")
    assert composition._resolve_pin(2).name() == "G"


def test_pin_falls_back_to_playhead_for_graph_forms(patch_midi: None) -> None:
    """Graph forms have no fixed layout, so a relative pin keys off the playhead section."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.form({"verse": (8, None)}, start="verse")
    composition.pin_chord(2, "V")

    assert composition._resolve_pin(2).name() == "G"  # composition key, via playhead


def test_resolve_error_skips_section_not_crashes(patch_midi: None) -> None:
    """A degree out of range for the effective scale is caught at _run, with a clear message."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.form(
        subsequence.Form([subsequence.Section("verse", 4, scale="minor_pentatonic")])
    )
    composition.section_chords(
        "verse", subsequence.progression([1, 7])
    )  # 7 is out of a 5-note scale

    with pytest.raises(ValueError, match="does not resolve against its effective"):
        composition.render(bars=4, filename="unused.mid")


def test_resolve_error_safety_net_returns_none(patch_midi: None) -> None:
    """The clock-time resolve guard never lets a ValueError escape — it skips with a warning."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", scale="major", seed=1
    )
    composition.section_chords("verse", subsequence.progression([1, 7]))

    # An effective scale that cannot hold degree 7 → None (fall-through), not a crash.
    info = subsequence.form_state.SectionInfo(
        name="verse", bar=0, bars=4, index=0, scale="minor_pentatonic"
    )
    assert composition._resolve_section_progression(info) is None


def test_form_freeze_carries_form_key(patch_midi: None) -> None:
    """A graph form's tier key survives freeze → rebind (the round-trip is lossless)."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=1
    )
    composition.form(
        {"intro": (4, [("verse", 1)]), "verse": (4, None)},
        start="intro",
        key="A",
        scale="minor",
    )

    path = composition.form_freeze()
    assert path.key == "A" and path.scale == "minor"

    composition.form(path)  # rebind without re-passing key
    assert composition._form_key == "A" and composition._form_scale == "minor"


def test_melodic_state_follows_section_key() -> None:
    """A persistent MelodicState re-tracks the section key on each build (no first-use freeze)."""

    state = subsequence.melodic_state.MelodicState()

    state.configure_defaults("C", "major")
    assert state.key == "C"

    # A later section in A — the state tracks it (history would persist; the
    # pool/tonic move).
    state.configure_defaults("A", "minor")
    assert state.key == "A" and state.mode == "minor"

    # An explicit constructor key is never overridden.
    pinned = subsequence.melodic_state.MelodicState(key="F", mode="dorian")
    pinned.configure_defaults("A", "minor")
    assert pinned.key == "F" and pinned.mode == "dorian"
