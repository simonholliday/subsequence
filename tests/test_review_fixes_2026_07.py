"""Regression tests for the 2026-07 review fix wave.

Each test locks in one of the fixes so the bug can't silently return.
Structured like test_review_fixes.py: one or two focused tests per fix,
grouped by the module the fix landed in.
"""

import asyncio
import heapq
import inspect
import logging
import pathlib
import random
import typing
import unittest.mock
import warnings

import pytest

import conftest

import subsequence
import subsequence.composition
import subsequence.conductor
import subsequence.constants
import subsequence.constants.durations
import subsequence.event_emitter
import subsequence.form_state
import subsequence.forms
import subsequence.groove
import subsequence.midi_utils
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.progressions
import subsequence.sequence_utils
import subsequence.sequencer
import subsequence.voicings
import subsequence.web_ui


def _builder(
    drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
    length: float = 4.0,
    conductor: typing.Optional[subsequence.conductor.Conductor] = None,
    bar: int = 0,
    time_signature: typing.Tuple[int, int] = (4, 4),
) -> typing.Tuple[
    subsequence.pattern.Pattern, subsequence.pattern_builder.PatternBuilder
]:
    """A Pattern/PatternBuilder pair for unit-level builder tests."""

    default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
    pattern = subsequence.pattern.Pattern(channel=0, length=length)
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern,
        cycle=0,
        conductor=conductor,
        bar=bar,
        default_grid=default_grid,
        drum_note_map=drum_note_map,
        time_signature=time_signature,
    )
    return pattern, builder


# ── sequence_utils: negative pulses rejected with a clear message ─────────────


def test_euclidean_negative_pulses_raises() -> None:
    """generate_euclidean_sequence(16, -1) raises instead of hanging/garbage."""

    with pytest.raises(ValueError, match="zero or positive"):
        subsequence.sequence_utils.generate_euclidean_sequence(16, -1)


def test_bresenham_negative_pulses_raises() -> None:
    """generate_bresenham_sequence(16, -1) raises the same clear error."""

    with pytest.raises(ValueError, match="zero or positive"):
        subsequence.sequence_utils.generate_bresenham_sequence(16, -1)


# ── sequence_utils: van der Corput guards its base ────────────────────────────


def test_van_der_corput_invalid_base_raises() -> None:
    """base=0 (division by zero) and base=1 (infinite loop) both raise."""

    with pytest.raises(ValueError, match="at least 2"):
        subsequence.sequence_utils.generate_van_der_corput_sequence(4, base=0)

    with pytest.raises(ValueError, match="at least 2"):
        subsequence.sequence_utils.generate_van_der_corput_sequence(4, base=1)


def test_van_der_corput_base_two_unchanged() -> None:
    """The classic base-2 sequence still comes out of the guarded function."""

    assert subsequence.sequence_utils.generate_van_der_corput_sequence(4) == [
        0.0,
        0.5,
        0.25,
        0.75,
    ]


# ── progressions: accidental degrees are scale-proof under short scales ───────


def test_accidental_degree_resolves_under_five_degree_scale() -> None:
    """bVII reads the major scale, so it survives a 5-degree scale like hirajoshi."""

    chord = subsequence.progressions.RomanChord(
        degree=7, accidental=-1, quality="major"
    ).resolve(0, "hirajoshi")

    assert chord.root_pc == 10


def test_plain_out_of_range_degree_still_raises() -> None:
    """An unprefixed degree beyond the scale keeps its out-of-range error."""

    with pytest.raises(ValueError, match="out of range"):
        subsequence.progressions.RomanChord(degree=9).resolve(0, "ionian")


# ── progressions: extend(9) on a degree stacks the implied diatonic seventh ───


def test_extend_nine_on_degree_stacks_implied_seventh() -> None:
    """extend(9) on V in C yields a full ninth chord (7th AND 9th), not add9."""

    resolved = subsequence.progression([5]).extend(9).resolve("C")

    # G B D F A — the diatonic seventh (F) is implied by the ninth.
    assert resolved.spans[0].tones(60) == [55, 59, 62, 65, 69]


# ── progressions: generation-only kwargs on a concrete list raise ──────────────


def test_generation_only_kwargs_on_concrete_list_raise() -> None:
    """cadence=/key= on a concrete progression name the style= path in the error."""

    with pytest.raises(ValueError, match="style="):
        subsequence.progression(["Am", "F", "C", "G"], cadence="strong")

    with pytest.raises(ValueError, match="style="):
        subsequence.progression(["Am", "F", "C", "G"], key="C")


# ── pattern: sub-pulse durations clamp to one pulse instead of raising ─────────


def test_add_note_beats_subpulse_duration_clamps_to_one_pulse() -> None:
    """A positive duration shorter than one pulse stores a 1-pulse note."""

    pattern = subsequence.pattern.Pattern(channel=0, length=4.0)

    pattern.add_note_beats(0.0, 60, 100, duration_beats=0.001)

    assert pattern.steps[0].notes[0].duration == 1


# ── pattern_builder: grid=0 transforms are silent no-ops ───────────────────────


def test_grid_zero_transforms_are_silent_noops() -> None:
    """hit_steps/sequence/scale_velocities/rotate with grid=0 return the builder untouched."""

    pattern, builder = _builder()

    assert builder.hit_steps(60, [0, 4], grid=0) is builder
    assert builder.sequence([0, 4], 60, grid=0) is builder
    assert builder.scale_velocities([1.0], grid=0) is builder
    assert builder.rotate(1, grid=0) is builder

    assert pattern.steps == {}  # nothing placed, nothing crashed


# ── pattern_builder: signal() honours the time signature ───────────────────────


def test_signal_reads_bar_start_in_any_metre() -> None:
    """In 3/4, bar 1 starts at beat 3 — signal() must read the conductor there."""

    conductor = subsequence.conductor.Conductor()
    conductor.line("ramp", start_val=0.0, end_val=1.0, duration_beats=6.0)

    _, builder = _builder(conductor=conductor, bar=1, time_signature=(3, 4))

    # Beat 3 of a 6-beat line = 0.5.  The old hardcoded 4 read beat 4 (≈0.667).
    assert builder.signal("ramp") == pytest.approx(0.5)


# ── pattern_midi: ramps emit their endpoint ────────────────────────────────────


def test_cc_ramp_emits_endpoint_when_resolution_does_not_divide() -> None:
    """A ramp whose resolution doesn't divide the span still reaches its target."""

    pattern, builder = _builder()

    builder.cc_ramp(74, 0, 127, beat_end=1.0, resolution=5)

    events = [e for e in pattern.cc_events if e.message_type == "control_change"]
    last = max(events, key=lambda e: e.pulse)

    assert (last.pulse, last.value) == (24, 127)


# ── pattern_midi: bend_range must be positive ──────────────────────────────────


def test_zero_bend_range_raises() -> None:
    """portamento()/slide() reject bend_range=0 with a clear message."""

    _, builder = _builder()

    with pytest.raises(ValueError, match="bend_range"):
        builder.portamento(bend_range=0)

    with pytest.raises(ValueError, match="bend_range"):
        builder.slide(notes=[0], bend_range=0)


# ── pattern_midi: sysex data bytes are validated to 7-bit ──────────────────────


def test_sysex_data_byte_out_of_range_raises() -> None:
    """A sysex data byte over 127 raises instead of dying at dispatch time."""

    _, builder = _builder()

    with pytest.raises(ValueError, match="0-127"):
        builder.sysex([0x7E, 200])


# ── motifs: the fume_fume preset carries the catalogued onsets ─────────────────


def test_preset_fume_fume_onsets() -> None:
    """fume fume onsets land at pulses 0,2,4,7,9 of a 12-pulse bar."""

    bell = subsequence.Motif.preset("fume_fume")

    assert bell.onsets() == pytest.approx([p * 4.0 / 12 for p in (0, 2, 4, 7, 9)])
    assert bell.length == 4.0


# ── motifs: unseeded develop() is genuinely nondeterministic ───────────────────


def _phrase_events(
    phrase: subsequence.Phrase,
) -> typing.List[typing.Tuple[typing.Any, ...]]:
    """Flatten a phrase to comparable (beat, pitch, velocity) tuples."""

    return [
        (e.beat, e.pitch, e.velocity)
        for segment in phrase.segments
        for e in segment.events
    ]


def test_develop_unseeded_differs_seeded_repeats() -> None:
    """develop() without seed= draws a fresh salt (it used to silently repeat)."""

    motif = subsequence.motif([1, 2, 3, 4])

    # Seed the module RNG only to make the two salt draws deterministic
    # for the test — the two calls still draw DIFFERENT salts.
    random.seed(123)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first = subsequence.Phrase.develop(motif, bars=4, plan=["a", "b"], seed=None)
        second = subsequence.Phrase.develop(motif, bars=4, plan=["a", "b"], seed=None)

    assert all("nondeterministic" in str(w.message) for w in caught)
    assert len(caught) == 2
    assert _phrase_events(first) != _phrase_events(second)

    seeded_a = subsequence.Phrase.develop(motif, bars=4, plan=["a", "b"], seed=3)
    seeded_b = subsequence.Phrase.develop(motif, bars=4, plan=["a", "b"], seed=3)

    assert _phrase_events(seeded_a) == _phrase_events(seeded_b)


def test_sentence_and_reroll_share_the_salt_fix() -> None:
    """sentence() and Phrase.reroll() follow the same unseeded-differs contract."""

    motif = subsequence.motif([1, 2, 3, 4])
    random.seed(123)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        s1 = subsequence.sentence(motif, bars=4, seed=None)
        s2 = subsequence.sentence(motif, bars=4, seed=None)

    assert len(caught) == 2
    assert _phrase_events(s1) != _phrase_events(s2)

    base = subsequence.Phrase.develop(motif, bars=4, plan=["a", "b"], seed=3)

    with warnings.catch_warnings(record=True) as caught_reroll:
        warnings.simplefilter("always")
        r1 = base.reroll(bar=2, seed=None)
        r2 = base.reroll(bar=2, seed=None)

    assert len(caught_reroll) == 2
    assert _phrase_events(r1) != _phrase_events(r2)
    assert _phrase_events(base.reroll(bar=2, seed=5)) == _phrase_events(
        base.reroll(bar=2, seed=5)
    )


# ── motifs: generate() with an explicit MIDI pool ──────────────────────────────

_MIDI_POOL: typing.List[int] = [60, 63, 65, 70]


def test_generate_midi_pool_cadence_raises() -> None:
    """cadence= names a scale degree — meaningless against a MIDI pool."""

    with pytest.raises(ValueError, match="MIDI pool"):
        subsequence.Motif.generate(
            rhythm=[0, 1, 2, 3], scale=_MIDI_POOL, seed=1, cadence="strong"
        )


def test_generate_midi_pool_degree_pin_raises() -> None:
    """A Degree pin has no scale to read against an explicit MIDI pool."""

    with pytest.raises(ValueError, match="MIDI pool"):
        subsequence.Motif.generate(
            rhythm=[0, 1, 2, 3],
            scale=_MIDI_POOL,
            seed=1,
            pins={-1: subsequence.Degree(5)},
        )


def test_generate_midi_pool_int_pin_is_exact_note() -> None:
    """An int pin against a MIDI pool pins that exact MIDI note."""

    generated = subsequence.Motif.generate(
        rhythm=[0, 1, 2, 3], scale=_MIDI_POOL, seed=1, pins={-1: 63}
    )

    assert generated.events[-1].pitch == 63


# ── motifs: accent() clamps to a playable velocity ─────────────────────────────


def test_accent_negative_amount_clamps_to_playable_velocity() -> None:
    """A heavy de-accent stores velocity 1, never zero or negative."""

    accented = subsequence.motif([1, 2, 3], velocities=90).accent(0.0, amount=-200)

    assert [e.velocity for e in accented.events] == [1, 90, 90]


# ── motifs: join()/tiling no longer strip fit ──────────────────────────────────


def test_join_and_tiling_preserve_fit() -> None:
    """then()-folding from empty() inherits the operand's fit instead of erasing it."""

    generated = subsequence.Motif.generate(rhythm=[0, 1], seed=2)
    assert generated.fit == 0.7  # generate() sets the chord-snapping dial

    assert subsequence.Motif.join([generated, generated]).fit == 0.7
    # m * 2 is a Phrase; flatten() folds via join()/then() — the path that used to strip fit.
    assert (generated * 2).flatten().fit == 0.7


# ── composition._InjectedChord: reads never advance voice leading ──────────────


def test_injected_chord_reads_do_not_advance_voice_leading() -> None:
    """root_note()/bass_note() are reads: correct pitches, state untouched."""

    state = subsequence.voicings.VoiceLeadingState()

    # Prime the state with a C-major voicing (tones() legitimately advances it).
    c_chord = subsequence.composition._InjectedChord(
        subsequence.parse_chord("C"), state
    )
    assert c_chord.tones(60) == [60, 64, 67]

    primed = list(state.previous_voicing or [])

    f_chord = subsequence.composition._InjectedChord(
        subsequence.parse_chord("F"), state
    )

    assert f_chord.root_note(60) == 65
    assert f_chord.bass_note(60) == 53
    assert state.previous_voicing == primed  # reads left the voicing alone


# ── form_state: empty forms, graph validation, and post-finish queue_next ──────


def test_empty_form_constructs_and_never_advances() -> None:
    """FormState([], loop=True) is legal and simply stays finished."""

    form = subsequence.form_state.FormState([], loop=True)

    assert form.advance() is False
    assert form.get_section_info() is None


def test_graph_form_unknown_transition_target_raises_at_construction() -> None:
    """A typo'd transition target fails loudly at build time, naming the target."""

    with pytest.raises(ValueError, match="chorsu"):
        subsequence.form_state.FormState(
            {
                "verse": (4, [("chorsu", 1.0)]),
                "chorus": (4, None),
            }
        )


def test_sequence_form_queue_next_revives_finished_form() -> None:
    """queue_next() after a sequence form finishes restarts it at the queued section."""

    form = subsequence.form_state.FormState(
        [
            subsequence.forms.Section("verse", 1),
            subsequence.forms.Section("chorus", 1),
        ]
    )

    assert form.advance() is True  # verse → chorus
    assert form.advance() is True  # chorus → finished
    assert form.get_section_info() is None

    form.queue_next("verse")

    assert form.advance() is True
    info = form.get_section_info()
    assert info is not None and info.name == "verse"


def test_graph_form_queue_next_revives_terminal_end() -> None:
    """queue_next() after a graph form ends at a terminal section revives it."""

    form = subsequence.form_state.FormState(
        {
            "verse": (1, [("outro", 1.0)]),
            "outro": (1, None),
        }
    )

    assert form.advance() is True  # verse → outro
    assert form.advance() is True  # outro is terminal → finished
    assert form.get_section_info() is None

    form.queue_next("verse")

    assert form.advance() is True
    info = form.get_section_info()
    assert info is not None and info.name == "verse"


# ── groove: .agr import — the tracked asset and the one-note-per-cell guard ────

_AGR_ASSET = (
    pathlib.Path(__file__).parent.parent / "examples" / "assets" / "Swing 16ths 57.agr"
)


def test_from_agr_tracked_asset_still_parses() -> None:
    """The shipped Ableton groove imports: 16th grid, alternating swing offsets."""

    groove = subsequence.groove.Groove.from_agr(str(_AGR_ASSET))

    assert groove.grid == pytest.approx(0.25)
    assert len(groove.offsets) == 16

    for i in range(0, 16, 2):
        assert groove.offsets[i] == pytest.approx(0.0, abs=1e-3)
    for i in range(1, 16, 2):
        assert groove.offsets[i] == pytest.approx(0.035, abs=1e-3)


def _write_agr_clip(
    path: pathlib.Path, notes: typing.List[typing.Tuple[float, int]], clip_length: float
) -> None:
    """Write a minimal .agr XML clip (the structure of the shipped asset, reduced)."""

    notes_xml = "\n".join(
        f'<MidiNoteEvent Time="{time}" Duration="0.0625" Velocity="{velocity}" '
        f'VelocityDeviation="0" OffVelocity="64" Probability="1" IsEnabled="true" NoteId="{i + 1}" />'
        for i, (time, velocity) in enumerate(notes)
    )

    path.write_text(
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<Ableton MajorVersion="5">\n'
        "<Groove>\n"
        '<Clip><Value><MidiClip Id="0" Time="0">\n'
        '<CurrentStart Value="0" />\n'
        f'<CurrentEnd Value="{clip_length}" />\n'
        '<Notes><KeyTracks><KeyTrack Id="0"><Notes>\n'
        f"{notes_xml}\n"
        "</Notes></KeyTrack></KeyTracks></Notes>\n"
        "</MidiClip></Value></Clip>\n"
        '<TimingAmount Value="100" />\n'
        '<VelocityAmount Value="100" />\n'
        "</Groove>\n"
        "</Ableton>\n"
    )


def test_from_agr_chord_clip_raises_grid_error(tmp_path: pathlib.Path) -> None:
    """Two notes in one grid cell (a chord) raise, with and without grid=."""

    agr = tmp_path / "chord.agr"
    _write_agr_clip(
        agr, [(0.0, 127), (0.25, 100), (0.25, 90), (0.75, 80)], clip_length=1.0
    )

    with pytest.raises(ValueError, match="grid"):
        subsequence.groove.Groove.from_agr(str(agr))

    # A chord shares a slot at ANY grid — grid= can't rescue it.
    with pytest.raises(ValueError, match="grid"):
        subsequence.groove.Groove.from_agr(str(agr), grid=0.25)


def test_from_agr_rest_imports_cleanly_with_explicit_grid(
    tmp_path: pathlib.Path,
) -> None:
    """Three notes on a 4-cell grid import when grid= is explicit; the rest stays neutral."""

    agr = tmp_path / "rest.agr"
    _write_agr_clip(agr, [(0.0, 127), (0.25, 127), (0.75, 127)], clip_length=1.0)

    groove = subsequence.groove.Groove.from_agr(str(agr), grid=0.25)

    assert len(groove.offsets) == 4
    assert groove.offsets[2] == 0.0  # the empty cell keeps a neutral offset


# ── sequencer: named-drone mirroring re-resolves through each map ──────────────


@pytest.mark.asyncio
async def test_named_drone_mirrors_use_their_own_drum_maps(patch_midi: None) -> None:
    """A named drone sounds the mirror's own note; a map lacking the name stays silent."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0,
        length=4,
        device=0,
        mirrors=[(1, 5, {"kick": 50}), (2, 6, {"snare": 40})],
    )
    pattern.raw_note_events.append(
        subsequence.pattern.RawNoteEvent(
            pulse=0,
            message_type="note_on",
            pitch=36,
            velocity=100,
            origin="kick",
        )
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = [e for e in sequencer.event_queue if e.message_type == "note_on"]

    # Primary keeps its own pitch; the kick-mapped mirror re-resolves to 50;
    # the snare-only mirror (device 2) gets NO event — silence, never a wrong note.
    assert sorted((e.device, e.channel, e.note) for e in note_ons) == [
        (0, 0, 36),
        (1, 5, 50),
    ]


# ── sequencer: negative-priority CC dispatches before same-pulse note_on ───────


@pytest.mark.asyncio
async def test_onset_bend_priority_beats_note_push_order(patch_midi: None) -> None:
    """A priority=-1 CcEvent pops before a pulse-0 note_on even though notes push first."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)
    pattern.add_note(position=0, pitch=60, velocity=100, duration=12)
    pattern.cc_events.append(
        subsequence.pattern.CcEvent(
            pulse=0,
            message_type="pitchwheel",
            value=1234,
            priority=-1,
        )
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    popped: typing.List[str] = []
    while sequencer.event_queue:
        popped.append(heapq.heappop(sequencer.event_queue).message_type)

    assert popped == ["pitchwheel", "note_on", "note_off"]


def test_midi_event_priority_outranks_sequence() -> None:
    """At a shared pulse, a lower priority sorts first regardless of push order."""

    early = subsequence.sequencer.MidiEvent(
        pulse=0, message_type="pitchwheel", channel=0, priority=-1, sequence=10
    )
    late = subsequence.sequencer.MidiEvent(
        pulse=0, message_type="note_on", channel=0, priority=0, sequence=1
    )

    assert early < late


# ── sequencer: unregister note_offs ride latency compensation ──────────────────


@pytest.mark.asyncio
async def test_stop_pattern_notes_defers_note_off_on_fast_device(
    patch_midi: None,
) -> None:
    """_stop_pattern_notes routes through compensation — a fast device's note_off is deferred."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    sequencer._event_loop = asyncio.get_running_loop()

    spy = conftest.SpyMidiOut()
    sequencer.midi_out = spy
    sequencer.set_device_latency(0, 0)
    # A very slow second device gives device 0 a 5s offset, so the deferred
    # note_off cannot fire during the test.
    sequencer.add_output_device("slow", conftest.SpyMidiOut(), latency_ms=5000)

    pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)
    sequencer.active_notes.add((0, 0, 60))

    await sequencer._stop_pattern_notes(pattern)

    assert not any(m.type == "note_off" for m in spy.sent)  # not sent immediately
    assert len(sequencer._pending_sends) == 1  # deferred instead
    assert (0, 0, 60) not in sequencer.active_notes

    sequencer._cancel_pending_sends()


# ── sequencer: Link tempo changes land in the recording ────────────────────────


class _FakeLinkClock:
    """Minimal Link session stand-in: one tempo, instant syncs."""

    tempo: float = 100.0
    num_peers: int = 0

    async def wait_for_bar(self) -> float:
        """Pretend the bar boundary is now, at beat 0."""

        return 0.0

    async def sync(self, beat: float) -> None:
        """Never block — the loop stops itself when the queue is empty."""

        return None


@pytest.mark.asyncio
async def test_link_tempo_change_recorded_as_set_tempo(patch_midi: None) -> None:
    """The Link loop records a set_tempo meta event when the session tempo differs."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    sequencer.recording = True
    sequencer.running = True

    await sequencer._run_loop_link_clock(_FakeLinkClock(), pulses_per_bar=96)

    tempos = [
        message
        for _, message in sequencer.recorded_events
        if message.type == "set_tempo"
    ]

    assert len(tempos) == 1
    assert tempos[0].tempo == 600000  # mido.bpm2tempo(100)
    assert sequencer.current_bpm == pytest.approx(100.0)


# ── web_ui: the dashboard reports the live tempo ───────────────────────────────


def test_web_ui_state_reports_live_bpm(patch_midi: None) -> None:
    """_get_state() reads the sequencer's current_bpm, not the declared comp.bpm."""

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
    ui = subsequence.web_ui.WebUI(comp)

    comp._sequencer.current_bpm = 133.5  # a live tempo change

    assert ui._get_state(comp)["bpm"] == 133.5


# ── midi_utils: headless multi-output selection fails usably ───────────────────


def test_select_output_device_headless_multi_output_fails_usably(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """EOF on the device prompt ends the call instead of spinning forever.

    The prompt loop raises RuntimeError naming output_device=; the function's
    outer error handler converts that into its documented (None, None) failure
    return, logging the usable message.  This test pins both halves: no hang,
    and the actionable "pass output_device=" text reaching the log.
    """

    import mido

    monkeypatch.setattr(mido, "get_output_names", lambda: ["Synth A", "Synth B"])

    def _eof(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)

    with caplog.at_level(logging.ERROR, logger="subsequence.midi_utils"):
        result = subsequence.midi_utils.select_output_device(None)

    assert result == (None, None)
    assert any("output_device" in record.getMessage() for record in caplog.records)


# ── harmonic clock: callable without horizon and bar_beats ─────────────────────


def test_schedule_harmonic_clock_defaults_horizon_and_bar_beats() -> None:
    """The clock binds with just a sequencer, a state getter, and cycle_beats."""

    signature = inspect.signature(subsequence.composition.schedule_harmonic_clock)

    bound = signature.bind("seq", lambda: None, cycle_beats=4)

    assert "horizon" not in bound.arguments
    assert "bar_beats" not in bound.arguments


# ── harmonic clock: schedule_form advances the CURRENT form after a swap ───────


@pytest.mark.asyncio
async def test_schedule_form_advances_swapped_form_state() -> None:
    """get_form_state= is re-read per bar: after a swap, the NEW form advances."""

    form_a = subsequence.form_state.FormState([("verse", 4)])
    form_b = subsequence.form_state.FormState([("bridge", 4)])
    holder: typing.Dict[str, subsequence.form_state.FormState] = {"fs": form_a}

    captured: typing.Dict[str, typing.Any] = {}

    mock_seq = unittest.mock.MagicMock()
    mock_seq.pulses_per_beat = 24
    mock_seq.time_signature = (4, 4)
    mock_seq.events = subsequence.event_emitter.EventEmitter()

    async def capture(
        callback: typing.Callable,
        interval_beats: float,
        start_pulse: int = 0,
        reschedule_lookahead: float = 1,
    ) -> None:
        captured["callback"] = callback

    mock_seq.schedule_callback_repeating = capture

    await subsequence.composition.schedule_form(
        sequencer=mock_seq,
        form_state=form_a,
        reschedule_lookahead=1,
        get_form_state=lambda: holder["fs"],
    )

    advance = captured["callback"]

    advance(72)  # bar 1 boundary — form A is current
    assert (form_a.total_bars, form_b.total_bars) == (1, 0)

    holder["fs"] = form_b  # a mid-playback form() re-bind

    advance(168)  # bar 2 boundary — form B must advance, A must not
    assert (form_a.total_bars, form_b.total_bars) == (1, 1)


# ── harmonic clock: _start_harmonic_clock is idempotent per playback ───────────


def test_start_harmonic_clock_is_idempotent(
    patch_midi: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second _start_harmonic_clock() call registers nothing new."""

    calls: typing.List[typing.Dict[str, typing.Any]] = []

    async def fake_clock(**kwargs: typing.Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subsequence.composition, "schedule_harmonic_clock", fake_clock)

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

    asyncio.run(comp._start_harmonic_clock())
    assert comp._harmonic_clock_started is True
    assert len(calls) == 1

    asyncio.run(comp._start_harmonic_clock())
    assert len(calls) == 1  # the second call returned without rescheduling


def test_harmony_before_play_does_not_start_clock(patch_midi: None) -> None:
    """harmony() before play() leaves clock startup to _run() (no loop yet)."""

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

    comp.harmony(progression=subsequence.progression(["Am", "F", "C", "G"]))

    assert comp._harmonic_clock_started is False
