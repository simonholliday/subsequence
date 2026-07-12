"""Tests for stage 6 — the cadence table and everything wired to it.

The formula table; ``Progression.cadence()`` tail substitution;
``Progression.generate(cadence=)`` / ``freeze(cadence=)`` pins;
``Motif.generate(cadence=)`` melodic closes; the clock-side request hooks
(``request_cadence`` / ``section_cadence``); and the ``sentence()`` /
``period()`` combinators.
"""

import logging
import random
import typing
import unittest.mock

import pytest

import subsequence
import subsequence.cadences
import subsequence.chords
import subsequence.composition
import subsequence.harmonic_state
import subsequence.motifs
import subsequence.progressions


# ---------------------------------------------------------------------------
# The formula table
# ---------------------------------------------------------------------------


def test_cadence_table_producer_names() -> None:
    """The four producer names map to the documented formulas and closes."""

    strong = subsequence.cadences.cadence_formula("strong")
    assert strong.formula == ("V", 1)
    assert strong.close_degree == 1
    assert strong.theory_name == "authentic"

    soft = subsequence.cadences.cadence_formula("soft")
    assert soft.formula == (4, 1)
    assert soft.close_degree == 1

    open_half = subsequence.cadences.cadence_formula("open")
    assert open_half.formula == (4, "V")
    assert open_half.close_degree == 5

    fakeout = subsequence.cadences.cadence_formula("fakeout")
    assert fakeout.formula == ("V", 6)
    assert fakeout.close_degree == 1


def test_cadence_theory_aliases() -> None:
    """Theory names resolve to the same table entries."""

    assert subsequence.cadences.cadence_formula("authentic").name == "strong"
    assert subsequence.cadences.cadence_formula("perfect").name == "strong"
    assert subsequence.cadences.cadence_formula("plagal").name == "soft"
    assert subsequence.cadences.cadence_formula("half").name == "open"
    assert subsequence.cadences.cadence_formula("deceptive").name == "fakeout"
    assert subsequence.cadences.cadence_formula("interrupted").name == "fakeout"
    assert subsequence.cadences.cadence_formula("  Strong ").name == "strong"


def test_cadence_unknown_name_lists_the_table() -> None:
    """An unknown name raises, listing every valid name and alias."""

    with pytest.raises(ValueError, match="fakeout, open, soft, strong"):
        subsequence.cadences.cadence_formula("huge")

    with pytest.raises(TypeError, match="named by string"):
        subsequence.cadences.cadence_formula(1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Progression.cadence() — tail substitution
# ---------------------------------------------------------------------------


def test_progression_cadence_substitutes_the_tail() -> None:
    """The final spans take the formula's chords; the rest stay."""

    value = subsequence.progression(["Am", "F", "C", "G"]).cadence("open")
    resolved = value.resolve("A", "aeolian")

    names = [span.chord.name() for span in resolved.spans]
    assert names == ["Am", "F", "Dm", "E"]  # iv → V: the half close


def test_progression_cadence_strong_in_minor_is_the_major_dominant() -> None:
    """``"V"`` carries its quality — E major in A minor, the convention."""

    value = (
        subsequence.progression([1, 6, 4, 5]).cadence("strong").resolve("A", "aeolian")
    )

    names = [span.chord.name() for span in value.spans]
    assert names[-2:] == ["E", "Am"]


def test_progression_cadence_keeps_beats_and_drops_decorations() -> None:
    """Replaced spans keep their lengths; old chords and spice go."""

    value = subsequence.progression([("Am", 4), ("F", 2), ("C", 6)]).extend(9)
    closed = value.cadence("fakeout")

    assert [span.beats for span in closed.spans] == [4.0, 2.0, 6.0]
    assert closed.spans[0].extensions == (9,)  # untouched outside the tail
    assert closed.spans[1].extensions == ()
    assert closed.spans[2].extensions == ()

    resolved = closed.resolve("A", "aeolian")
    assert [span.chord.name() for span in resolved.spans[-2:]] == ["E", "F"]  # V → VI


def test_progression_cadence_too_short_raises() -> None:
    """A one-span progression cannot take a two-chord formula."""

    with pytest.raises(ValueError, match="only 1"):
        subsequence.progression(["Am"]).cadence("strong")


# ---------------------------------------------------------------------------
# Generation pins — Progression.generate(cadence=) and the factory
# ---------------------------------------------------------------------------


def test_generate_cadence_pins_the_tail() -> None:
    """The walk arrives V → I in C major; the body is still walked."""

    value = subsequence.Progression.generate(
        style="functional_major",
        bars=4,
        key="C",
        seed=3,
        cadence="strong",
    )

    names = [span.chord.name() for span in value.spans]
    assert names[-2:] == ["G", "C"]


def test_generate_cadence_soft_is_walkable() -> None:
    """The plagal close exists in the functional major grammar (IV → I)."""

    value = subsequence.Progression.generate(
        style="functional_major",
        bars=4,
        key="C",
        seed=3,
        cadence="soft",
    )

    names = [span.chord.name() for span in value.spans]
    assert names[-2:] == ["F", "C"]


def test_generate_cadence_fakeout_swerves() -> None:
    """V → vi: the harmony promises home and lands on the submediant."""

    value = subsequence.Progression.generate(
        style="functional_major",
        bars=4,
        key="C",
        seed=3,
        cadence="fakeout",
    )

    names = [span.chord.name() for span in value.spans]
    assert names[-2:] == ["G", "Am"]


def test_generate_cadence_key_relative_value() -> None:
    """Without key= the cadence rides the key-relative spelling."""

    value = subsequence.Progression.generate(
        style="aeolian_minor",
        bars=4,
        seed=3,
        cadence="strong",
    )

    resolved = value.resolve("A", "aeolian")
    assert [span.chord.name() for span in resolved.spans[-2:]] == ["E", "Am"]


def test_generate_cadence_conflicts_raise() -> None:
    """cadence= cannot combine with end= or pins on the formula bars."""

    with pytest.raises(ValueError, match="conflicts with end"):
        subsequence.Progression.generate(
            style="functional_major",
            bars=4,
            key="C",
            seed=1,
            cadence="strong",
            end="V",
        )

    with pytest.raises(ValueError, match=r"pins\[3\]"):
        subsequence.Progression.generate(
            style="functional_major",
            bars=4,
            key="C",
            seed=1,
            cadence="strong",
            pins={3: "F"},
        )

    with pytest.raises(ValueError, match="needs 2 bars"):
        subsequence.Progression.generate(
            style="functional_major",
            bars=1,
            key="C",
            seed=1,
            cadence="strong",
        )


def test_progression_factory_passes_cadence_through() -> None:
    """The lowercase factory's style path forwards cadence=."""

    value = subsequence.progression(
        style="functional_major", key="C", bars=4, seed=3, cadence="strong"
    )

    names = [span.chord.name() for span in value.spans]
    assert names[-2:] == ["G", "C"]


# ---------------------------------------------------------------------------
# freeze(cadence=) and the constraint-scale inference
# ---------------------------------------------------------------------------


def test_freeze_cadence_pins_the_tail(patch_midi: None) -> None:
    """freeze(cadence=) compiles the formula into the final bars."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=5
    )
    composition.harmony(style="functional_major", cycle_beats=4)

    frozen = composition.freeze(4, cadence="strong")

    names = [span.chord.name() for span in frozen.spans]
    assert names[-2:] == ["G", "C"]


def test_freeze_cadence_conflicts_with_end(patch_midi: None) -> None:
    """The same conflict rules as generation."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="C", seed=5
    )
    composition.harmony(style="functional_major", cycle_beats=4)

    with pytest.raises(ValueError, match="conflicts with end"):
        composition.freeze(4, cadence="strong", end="V")


def test_constraint_scale_inferred_from_style(patch_midi: None) -> None:
    """Without Composition(scale=), int constraints follow the harmony style."""

    composition = subsequence.Composition(
        output_device="Dummy MIDI", bpm=120, key="A", seed=5
    )
    composition.harmony(style="aeolian_minor", cycle_beats=4)

    assert composition._constraint_scale() == "minor"

    frozen = composition.freeze(4, cadence="strong")
    names = [span.chord.name() for span in frozen.spans]
    assert names[-2:] == ["E", "Am"]  # the tonic pin resolved minor


# ---------------------------------------------------------------------------
# Melody closes — Motif.generate(cadence=)
# ---------------------------------------------------------------------------


def test_motif_generate_cadence_close() -> None:
    """cadence= is end_on sugar: strong lands on 1, open on 5."""

    strong = subsequence.Motif.generate(rhythm=[0, 1, 2, 3], cadence="strong", seed=7)
    last = [event.pitch for event in strong.events if event.pitch is not None][-1]
    assert isinstance(last, subsequence.Degree) and last.step == 1

    open_half = subsequence.Motif.generate(rhythm=[0, 1, 2, 3], cadence="open", seed=7)
    last = [event.pitch for event in open_half.events if event.pitch is not None][-1]
    assert isinstance(last, subsequence.Degree) and last.step == 5


def test_motif_generate_cadence_conflicts_with_end_on() -> None:
    """Both name the close — together they raise."""

    with pytest.raises(ValueError, match="conflicts with end_on"):
        subsequence.Motif.generate(rhythm=[0, 1], cadence="strong", end_on=5, seed=1)


# ---------------------------------------------------------------------------
# The request hooks — the clock-side seam
# ---------------------------------------------------------------------------


async def _capture_clock(
    **kwargs: typing.Any,
) -> typing.Tuple[
    typing.Callable[[int], typing.Optional[float]],
    "subsequence.composition._HarmonyHorizon",
]:
    """Schedule the clock against a mock sequencer; return (callback, horizon)."""

    captured: typing.Dict[str, typing.Any] = {}

    mock_seq = unittest.mock.MagicMock()
    mock_seq.pulses_per_beat = 24

    async def capture(
        callback: typing.Callable, start_pulse: int = 0, reschedule_lookahead: float = 1
    ) -> None:
        captured["callback"] = callback

    mock_seq.schedule_callback_sequence = capture

    horizon = subsequence.composition._HarmonyHorizon()

    await subsequence.composition.schedule_harmonic_clock(
        sequencer=mock_seq,
        horizon=horizon,
        bar_beats=4.0,
        **kwargs,
    )

    return captured["callback"], horizon


def _major_resolver(
    key_pc: int = 0,
) -> typing.Callable[[str], typing.List[subsequence.chords.Chord]]:
    """A resolve_cadence callable for a major key rooted at key_pc."""

    def resolve(name: str) -> typing.List[subsequence.chords.Chord]:
        spec = subsequence.cadences.cadence_formula(name)
        return [
            subsequence.progressions.resolve_constraint(
                element, key_pc, "ionian", "cadence"
            )
            for element in spec.formula
        ]

    return resolve


@pytest.mark.asyncio
async def test_request_cadence_steers_the_live_walk(patch_midi: None) -> None:
    """A pending request plans a constrained approach: the formula arrives at its bar."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )
    requests = {4: "strong"}

    cb, horizon = await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        cadence_requests=requests,
        resolve_cadence=_major_resolver(0),
    )

    # Beat 0 sounds the tonic; the request is still pending.
    assert horizon.chord_at(0.0).name() == "C"
    assert requests == {4: "strong"}

    # The first boundary plans the whole approach and consumes the request.
    cb(4 * 24)
    assert requests == {}
    assert hs.current_chord.name() not in ("",)  # a real chord committed

    cb(8 * 24)
    assert horizon.chord_at(8.0).name() == "G"  # the dominant in place at bar 3

    cb(12 * 24)
    assert horizon.chord_at(12.0).name() == "C"  # the arrival at bar 4
    assert hs.current_chord.name() == "C"

    # The journey continued through the close: every boundary committed.
    assert len(hs.history) == 3


@pytest.mark.asyncio
async def test_request_cadence_publishes_the_planned_approach(patch_midi: None) -> None:
    """While the queue serves, the window's next chord is the queued one — no fresh draw."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )

    cb, horizon = await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        cadence_requests={4: "strong"},
        resolve_cadence=_major_resolver(0),
    )

    cb(4 * 24)
    # The dominant is already visible one boundary ahead.
    assert horizon.chord_at(8.0).name() == "G"

    cb(8 * 24)
    assert horizon.chord_at(12.0).name() == "C"


@pytest.mark.asyncio
async def test_request_cadence_unwalkable_falls_back_to_fiat(
    patch_midi: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A formula outside the graph's vocabulary lands by fiat, loudly."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )

    out_of_vocabulary = [
        subsequence.chords.Chord(root_pc=1, quality="major"),  # C#
        subsequence.chords.Chord(root_pc=6, quality="major"),  # F#
    ]

    cb, horizon = await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        cadence_requests={3: "strong"},
        resolve_cadence=lambda name: list(out_of_vocabulary),
    )

    with caplog.at_level(logging.WARNING):
        cb(4 * 24)
        cb(8 * 24)

    assert "lands by fiat" in caplog.text
    assert horizon.chord_at(4.0).name() == "C#"
    assert horizon.chord_at(8.0).name() == "F#"
    assert (
        hs.current_chord.name() == "F#"
    )  # fiat still commits — the engine stays coherent


@pytest.mark.asyncio
async def test_request_cadence_expires_when_the_bar_passes(
    patch_midi: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A request whose bar has passed is dropped with a warning."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )
    requests = {1: "strong"}

    cb, _horizon = await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        cadence_requests=requests,
        resolve_cadence=_major_resolver(0),
    )

    with caplog.at_level(logging.WARNING):
        cb(4 * 24)

    assert requests == {}
    assert "expired unserved" in caplog.text


@pytest.mark.asyncio
async def test_request_cadence_too_late_uses_the_formula_tail(
    patch_midi: None, caplog: pytest.LogCaptureFixture
) -> None:
    """One boundary of room: only the arrival chord lands, with a warning."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )

    cb, horizon = await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        cadence_requests={2: "strong"},
        resolve_cadence=_major_resolver(0),
    )

    with caplog.at_level(logging.WARNING):
        cb(4 * 24)

    assert "formula's tail" in caplog.text
    assert horizon.chord_at(4.0).name() == "C"  # the arrival, at its bar


@pytest.mark.asyncio
async def test_section_cadence_registers_at_the_final_bar(patch_midi: None) -> None:
    """Entering a live section with a registered cadence requests its last bar."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )
    requests: typing.Dict[int, str] = {}

    cb, horizon = await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        get_section_progression=lambda: ("verse", 0, 4, None),
        cadence_requests=requests,
        resolve_cadence=_major_resolver(0),
        get_section_cadence={"verse": "open"}.get,
    )

    # Entry at bar 1, 4 bars → the arrival lands at bar 4.
    assert requests == {4: "open"}

    cb(4 * 24)
    cb(8 * 24)
    assert horizon.chord_at(8.0).name() == "F"  # IV approaching

    cb(12 * 24)
    assert horizon.chord_at(12.0).name() == "G"  # hanging on V at bar 4


@pytest.mark.asyncio
async def test_section_cadence_ignores_data_bound_sections(patch_midi: None) -> None:
    """A section with bound chords is data — no request is registered."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major", rng=random.Random(7)
    )
    prog = subsequence.progression(["Am", "F", "C", "G"]).resolve("C")
    requests: typing.Dict[int, str] = {}

    await _capture_clock(
        get_harmonic_state=lambda: hs,
        cycle_beats=4,
        get_section_progression=lambda: ("verse", 0, 4, prog),
        cadence_requests=requests,
        resolve_cadence=_major_resolver(0),
        get_section_cadence={"verse": "open"}.get,
    )

    assert requests == {}


def test_request_cadence_method_validates(patch_midi: None) -> None:
    """The Composition method validates the name and the bar, loudly."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

    with pytest.raises(ValueError, match="Unknown cadence"):
        composition.request_cadence("huge", bar=8)

    with pytest.raises(ValueError, match="needs bar="):
        composition.request_cadence("strong")

    composition.request_cadence("half", bar=8)
    assert composition._cadence_requests == {8: "open"}  # aliases normalise


def test_section_cadence_method_registers_and_unregisters(patch_midi: None) -> None:
    """section_cadence binds by name; None unbinds."""

    composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

    composition.section_cadence("verse", "deceptive")
    assert composition._section_cadences == {"verse": "fakeout"}

    composition.section_cadence("verse", None)
    assert composition._section_cadences == {}

    with pytest.raises(ValueError, match="Unknown cadence"):
        composition.section_cadence("verse", "huge")


# ---------------------------------------------------------------------------
# Graph edge labels
# ---------------------------------------------------------------------------


def test_functional_major_cadential_edges_are_labelled() -> None:
    """The cadence arrivals carry their producer labels (and IV→I exists)."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="C", graph_style="functional_major"
    )

    chord = subsequence.chords.Chord
    tonic = chord(root_pc=0, quality="major")
    subdominant = chord(root_pc=5, quality="major")
    dominant = chord(root_pc=7, quality="major")
    submediant = chord(root_pc=9, quality="minor")

    assert hs.graph.get_label(dominant, tonic) == "strong"
    assert hs.graph.get_label(subdominant, tonic) == "soft"
    assert hs.graph.get_label(dominant, submediant) == "fakeout"
    assert hs.graph.get_label(subdominant, dominant) == "open"


def test_aeolian_minor_cadential_edges_are_labelled() -> None:
    """The minor flagship carries the same labels on its cadence edges."""

    hs = subsequence.harmonic_state.HarmonicState(
        key_name="A", graph_style="aeolian_minor"
    )

    chord = subsequence.chords.Chord
    tonic = chord(root_pc=9, quality="minor")
    subdominant = chord(root_pc=2, quality="minor")
    dominant = chord(root_pc=4, quality="major")

    assert hs.graph.get_label(dominant, tonic) == "strong"
    assert hs.graph.get_label(subdominant, tonic) == "soft"
    assert hs.graph.get_label(subdominant, dominant) == "open"


# ---------------------------------------------------------------------------
# sentence() and period()
# ---------------------------------------------------------------------------


def test_sentence_shape_and_close() -> None:
    """Four units: idea, idea, contrast, contrast closing on the cadence degree."""

    idea = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3])
    value = subsequence.sentence(idea, bars=8, cadence="strong", seed=11)

    assert len(value.segments) == 4
    assert value.length == 32.0

    # The presentation states the idea twice, exactly.
    assert value.segments[0].events == value.segments[1].events

    # The continuation differs from the idea (re-pitched, same rhythm).
    assert value.segments[2].events != value.segments[0].events
    assert [e.beat for e in value.segments[2].events] == [
        e.beat for e in value.segments[0].events
    ]

    # The cadential unit lands on 1.
    last = [e.pitch for e in value.segments[3].events if e.pitch is not None][-1]
    assert isinstance(last, subsequence.Degree) and last.step == 1


def test_sentence_open_close_and_recipe() -> None:
    """cadence="open" lands on 5; the recipe records plan and cadence."""

    idea = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3])
    value = subsequence.sentence(idea, bars=8, cadence="half", seed=11)

    last = [e.pitch for e in value.segments[3].events if e.pitch is not None][-1]
    assert isinstance(last, subsequence.Degree) and last.step == 5

    assert value.recipe is not None
    assert value.recipe.plan == "sentence"
    assert value.recipe.cadence == "open"

    # Rerolls compose — the recipe survives.
    rerolled = value.reroll(bar=5, seed=4)
    assert rerolled.recipe is not None and rerolled.recipe.plan == "sentence"


def test_sentence_tiles_a_short_idea() -> None:
    """A 1-bar idea in an 8-bar sentence tiles up to the 2-bar unit."""

    idea = subsequence.motif([1, 2, 3, 4])
    value = subsequence.sentence(idea, bars=8, seed=2)

    assert value.segments[0].length == 8.0  # two tiles of the 4-beat idea
    assert len(value.segments) == 4


def test_sentence_seed_or_warn_and_determinism() -> None:
    """Seeded sentences reproduce; unseeded ones warn."""

    idea = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3])

    first = subsequence.sentence(idea, seed=11)
    second = subsequence.sentence(idea, seed=11)
    assert first.segments == second.segments

    with pytest.warns(UserWarning, match="seed"):
        subsequence.sentence(idea)


def test_period_question_and_answer() -> None:
    """Two halves, identical except the closes: 5 (open) then 1 (strong)."""

    idea = subsequence.motif([3, 4, 5, 1, None, 6, 5, 4])
    value = subsequence.period(idea)

    assert len(value.segments) == 2
    assert value.length == 16.0

    ante_pitches = [e.pitch for e in value.segments[0].events if e.pitch is not None]
    cons_pitches = [e.pitch for e in value.segments[1].events if e.pitch is not None]

    assert ante_pitches[:-1] == cons_pitches[:-1]  # same body
    assert ante_pitches[-1].step == 5  # the question
    assert cons_pitches[-1].step == 1  # the answer

    assert value.recipe is not None and value.recipe.plan == "period"


def test_period_keeps_phrase_segmentation() -> None:
    """A Phrase antecedent keeps its segments; only tail units re-aim."""

    a = subsequence.motif([5, 6, 5, 3])
    b = subsequence.motif([1, 2, 3, 4])
    value = subsequence.period(subsequence.Phrase([a, b]), cadence="strong")

    assert len(value.segments) == 4

    # The non-tail units are untouched restatements.
    assert value.segments[0].events == a.events
    assert value.segments[2].events == a.events

    ante_last = [e.pitch for e in value.segments[1].events if e.pitch is not None][-1]
    cons_last = [e.pitch for e in value.segments[3].events if e.pitch is not None][-1]
    assert ante_last.step == 5 and cons_last.step == 1


def test_period_is_deterministic() -> None:
    """No generation, no seed — the same input always gives the same period."""

    idea = subsequence.motif([3, 4, 5, 1])
    assert subsequence.period(idea).segments == subsequence.period(idea).segments


def test_period_rejects_empty_antecedent() -> None:
    """An empty antecedent raises loudly."""

    with pytest.raises(ValueError, match="empty antecedent"):
        subsequence.period(subsequence.Phrase([]))
