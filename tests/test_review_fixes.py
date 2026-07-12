"""Regression tests for issues found in the full code review.

Each test locks in one of the fixes so the bug can't silently return.
"""

import typing

import pytest

import subsequence
import subsequence.composition
import subsequence.constants
import subsequence.constants.durations
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequence_utils
import subsequence.sequencer


def _builder(
    drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
    length: float = 4.0,
    cycle: int = 0,
    data: typing.Optional[dict] = None,
) -> typing.Tuple[
    subsequence.pattern.Pattern, subsequence.pattern_builder.PatternBuilder
]:
    """A Pattern/PatternBuilder pair for unit-level builder tests."""

    default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
    pattern = subsequence.pattern.Pattern(channel=0, length=length)
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern,
        cycle=cycle,
        default_grid=default_grid,
        drum_note_map=drum_note_map,
        data=data if data is not None else {},
    )
    return pattern, builder


class _FakeChord:
    """Minimal chord stand-in exposing the ``tones`` interface chord()/strum() use."""

    def tones(
        self, root: int, inversion: int = 0, count: typing.Optional[int] = None
    ) -> typing.List[int]:
        return [root, root + 4, root + 7]


# ── M4: cc() clamps its value to the 7-bit range ─────────────────────────────


def test_cc_clamps_out_of_range_value() -> None:
    pattern, builder = _builder()

    builder.cc(74, 200)
    builder.cc(74, -5, beat=1)

    assert [e.value for e in pattern.cc_events] == [127, 0]


# ── M3: fibonacci_rhythm spreads (golden angle), it doesn't cluster ──────────


def test_fibonacci_rhythm_spreads_not_clusters() -> None:
    positions = subsequence.sequence_utils.fibonacci_rhythm(8, length=4.0)
    gaps = [b - a for a, b in zip(positions, positions[1:])]

    # The corrected frac(i·φ)·length form keeps a min gap ~0.36; the old
    # (i·φ) % length clustered two notes to within ~0.09.
    assert min(gaps) > 0.3


# ── M1: bar math honours the time signature, not a hardcoded 4 ───────────────


def test_resolve_length_uses_beats_per_bar() -> None:
    assert (
        subsequence.Composition._resolve_length(None, 2, None, None, beats_per_bar=3)[0]
        == 6.0
    )
    assert (
        subsequence.Composition._resolve_length(None, 2, None, None, beats_per_bar=4)[0]
        == 8.0
    )
    assert (
        subsequence.Composition._resolve_length(None, 2, None, None)[0] == 8.0
    )  # default 4/4


def test_set_target_bpm_respects_time_signature(patch_midi: None) -> None:
    seq = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120, time_signature=(3, 4)
    )

    seq.set_target_bpm(140, bars=2)

    assert seq._bpm_transition is not None
    assert seq._bpm_transition.total_pulses == 2 * seq.pulses_per_beat * 3


# ── H2: evolve() keys its buffer on seed content, not object identity ────────


def test_evolve_buffer_key_is_content_stable_across_cycles() -> None:
    shared: dict = {}

    # A fresh seed literal every cycle (the documented idiom).
    for cycle in range(4):
        _, builder = _builder(cycle=cycle, data=shared)
        builder.evolve([60, 62, 64, 67], length=4, drift=0.2, spacing=0.5)

    evolve_keys = [k for k in shared if k.startswith("_evolve_")]

    # One stable key reused across cycles — not a new (leaked) key each cycle,
    # which was the id(pitches) bug that stopped drift accumulating.
    assert len(evolve_keys) == 1


# ── M2: no_overlap honoured in thue_morse's two-pitch branch ─────────────────


def test_thue_morse_two_pitch_honours_no_overlap() -> None:
    pattern, builder = _builder(drum_note_map={"a": 36, "b": 38})

    # Pre-fill voice "a" on every step (same grid thue_morse uses).
    builder.hit_steps("a", list(range(16)), velocity=100)

    builder.thue_morse("a", pitch_b="b", no_overlap=True)

    # no_overlap must stop a second "a" landing where one already sounds.
    for step in pattern.steps.values():
        a_notes = [n for n in step.notes if n.pitch == 36]
        assert len(a_notes) <= 1


# ── M5: chord/strum detached guard gives a clear error ───────────────────────


def test_chord_detached_exceeding_length_raises_clear_error() -> None:
    _, builder = _builder(length=4.0)

    with pytest.raises(ValueError, match="detached"):
        builder.chord(_FakeChord(), root=60, detached=5.0)  # 5 > length 4


def test_strum_detached_exceeding_length_raises_clear_error() -> None:
    _, builder = _builder(length=4.0)

    with pytest.raises(ValueError, match="detached"):
        builder.strum(_FakeChord(), root=60, detached=5.0, spacing=0.1)


# ── Low: negative beats wrap from the end at any magnitude ───────────────────


def test_negative_beat_wraps_any_magnitude() -> None:
    pattern, builder = _builder(length=4.0)

    builder.note(60, beat=-5.0)  # -5 % 4 == 3.0

    pulse = int(3.0 * subsequence.constants.MIDI_QUARTER_NOTE)
    assert pulse in pattern.steps
    assert pattern.steps[pulse].notes[0].pitch == 60


# ── Low: set_length() chains ─────────────────────────────────────────────────


def test_set_length_returns_self_for_chaining() -> None:
    pattern, builder = _builder()

    result = builder.set_length(8.0)

    assert result is builder
    assert pattern.length == 8.0


# ── Test gap: p.sysex() emits the event with its payload ─────────────────────


def test_sysex_emits_event_with_payload() -> None:
    pattern, builder = _builder()

    builder.sysex([0x7E, 0x7F, 0x09, 0x01], beat=0)

    sysex_events = [e for e in pattern.cc_events if e.message_type == "sysex"]
    assert len(sysex_events) == 1
    assert list(sysex_events[0].data) == [0x7E, 0x7F, 0x09, 0x01]


# ── H1: each layer() gets a distinct, stable name (no collision) ─────────────


def test_layer_patterns_get_distinct_names(patch_midi: None) -> None:
    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

    def kick(p: typing.Any) -> None: ...
    def hats(p: typing.Any) -> None: ...
    def snare(p: typing.Any) -> None: ...
    def claps(p: typing.Any) -> None: ...

    comp.layer(kick, hats, channel=10, beats=4)
    comp.layer(snare, claps, channel=11, beats=4)

    names = [p.builder_fn.__name__ for p in comp._pending_patterns]

    # The name suffix uses the RESOLVED 0-indexed channel: user channel 10 → ch9.
    assert "kick+hats@ch9" in names
    assert "snare+claps@ch10" in names
    assert len(set(names)) == len(names)  # no "merged_builder" collision


# ── Low: cellular-automaton memoisation is correct (incremental == from-scratch) ──


def test_cellular_1d_memoised_matches_from_scratch() -> None:
    import subsequence.sequence_utils as su

    su._ca_1d_cache.clear()
    fresh = su.generate_cellular_automaton_1d(16, rule=30, generation=7, seed=1)

    su._ca_1d_cache.clear()
    incremental: typing.List[int] = []
    for gen in range(8):
        incremental = su.generate_cellular_automaton_1d(
            16, rule=30, generation=gen, seed=1
        )

    assert incremental == fresh


def test_cellular_2d_memoised_matches_from_scratch() -> None:
    import subsequence.sequence_utils as su

    su._ca_2d_cache.clear()
    fresh = su.generate_cellular_automaton_2d(
        rows=4, cols=8, rule="B3/S23", generation=6, seed=42
    )

    su._ca_2d_cache.clear()
    incremental: typing.List[typing.List[int]] = []
    for gen in range(7):
        incremental = su.generate_cellular_automaton_2d(
            rows=4, cols=8, rule="B3/S23", generation=gen, seed=42
        )

    assert incremental == fresh


# ── M6: previously-unreachable diatonic chords are now reachable from the tonic ──


def _reachable_from_tonic(
    graph: typing.Any, tonic: typing.Any
) -> typing.Set[typing.Any]:
    """Set of chords reachable from *tonic* by following graph edges (BFS)."""

    seen = {tonic}
    frontier = [tonic]

    while frontier:
        node = frontier.pop()
        for target, _weight in graph.get_transitions(node):
            if target not in seen:
                seen.add(target)
                frontier.append(target)

    return seen


def test_chord_graph_orphans_now_reachable() -> None:
    import subsequence.chord_graphs.aeolian_minor
    import subsequence.chord_graphs.dorian_minor
    import subsequence.chord_graphs.functional_major
    import subsequence.chord_graphs.lydian_major
    import subsequence.chords

    chord = subsequence.chords.Chord

    # (built graph+tonic, chords that the review found unreachable) — key of C.
    cases = [
        (
            subsequence.chord_graphs.functional_major.DiatonicMajor().build("C"),
            [
                chord(root_pc=4, quality="minor"),
                chord(root_pc=11, quality="diminished"),
            ],
        ),  # iii, vii°
        (
            subsequence.chord_graphs.aeolian_minor.AeolianMinor().build("C"),
            [
                chord(root_pc=3, quality="major"),
                chord(root_pc=2, quality="diminished"),
                chord(root_pc=11, quality="diminished"),
            ],
        ),  # bIII, ii°, vii°
        (
            subsequence.chord_graphs.dorian_minor.DorianMinor().build("C"),
            [chord(root_pc=9, quality="diminished")],
        ),  # vi°
        (
            subsequence.chord_graphs.lydian_major.LydianMajor().build("C"),
            [
                chord(root_pc=6, quality="diminished"),
                chord(root_pc=11, quality="minor"),
            ],
        ),  # #iv°, vii
    ]

    for (graph, tonic), expected in cases:
        reachable = _reachable_from_tonic(graph, tonic)
        for orphan in expected:
            assert orphan in reachable, (
                f"{orphan} should now be reachable from the tonic"
            )
