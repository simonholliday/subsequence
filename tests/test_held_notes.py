import asyncio
import time
import typing

import mido

import subsequence
import subsequence.held_notes
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequencer


# ---------------------------------------------------------------------------
# HeldNotes — pure unit tests (time is injected, so these are deterministic)
# ---------------------------------------------------------------------------


def test_held_notes_on_off_snapshot() -> None:
    """A pressed note appears in the snapshot; releasing it removes it."""
    h = subsequence.held_notes.HeldNotes()
    h.note_on(60, 100, now=0.0)
    assert h.snapshot(now=0.0) == [60]
    h.note_off(60, now=0.0)
    assert h.snapshot(now=0.0) == []


def test_held_notes_snapshot_sorted_and_deduped() -> None:
    """Snapshot is sorted ascending regardless of press order."""
    h = subsequence.held_notes.HeldNotes()
    for pitch in (67, 60, 64):
        h.note_on(pitch, 100, now=0.0)
    assert h.snapshot(now=0.0) == [60, 64, 67]


def test_held_notes_unknown_note_off_is_noop() -> None:
    """A note-off for a pitch that was never down does nothing."""
    h = subsequence.held_notes.HeldNotes()
    h.note_off(99, now=0.0)
    assert h.snapshot(now=0.0) == []


def test_held_notes_release_window_holds_then_drops() -> None:
    """With release_ms, a released note lingers until its deadline passes."""
    h = subsequence.held_notes.HeldNotes(release_ms=50.0)  # 0.05 s
    h.note_on(60, 100, now=0.0)
    h.note_off(60, now=1.0)
    # Still within the 50 ms window — counts as held.
    assert h.snapshot(now=1.04) == [60]
    # Just past the deadline — gone.
    assert h.snapshot(now=1.06) == []


def test_held_notes_release_zero_drops_instantly() -> None:
    """release_ms=0 removes a note the instant its note-off arrives."""
    h = subsequence.held_notes.HeldNotes(release_ms=0.0)
    h.note_on(60, 100, now=0.0)
    h.note_off(60, now=1.0)
    assert h.snapshot(now=1.0) == []


def test_held_notes_repress_cancels_release() -> None:
    """Re-pressing a note inside the release window keeps it held indefinitely."""
    h = subsequence.held_notes.HeldNotes(release_ms=50.0)
    h.note_on(60, 100, now=0.0)
    h.note_off(60, now=1.0)
    h.note_on(60, 100, now=1.02)  # quick re-press during changeover
    # Long after the original deadline it is still held (no dropout).
    assert h.snapshot(now=5.0) == [60]


def test_held_notes_latch_persists_after_release() -> None:
    """In latch mode the chord stays held after every key is lifted."""
    h = subsequence.held_notes.HeldNotes(latch=True)
    h.note_on(60, 100, now=0.0)
    h.note_on(64, 100, now=0.0)
    h.note_off(60, now=1.0)
    h.note_off(64, now=1.0)
    assert h.snapshot(now=2.0) == [60, 64]


def test_held_notes_latch_new_chord_replaces() -> None:
    """The first key after a full release starts a fresh latched chord."""
    h = subsequence.held_notes.HeldNotes(latch=True)
    h.note_on(60, 100, now=0.0)
    h.note_off(60, now=1.0)
    assert h.snapshot(now=1.5) == [60]  # latched
    h.note_on(67, 100, now=2.0)  # new chord — replaces, not adds
    assert h.snapshot(now=2.0) == [67]


# ---------------------------------------------------------------------------
# Sequencer integration — _on_midi_input buffering + the loop-thread drain
# ---------------------------------------------------------------------------


def _make_seq(
    release_ms: float = 0.0,
    latch: bool = False,
    channel: typing.Optional[int] = None,
    device: typing.Optional[int] = None,
) -> subsequence.sequencer.Sequencer:
    seq = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    # _on_midi_input early-returns unless these are set.
    seq._midi_input_queue = asyncio.Queue()
    seq._input_loop = asyncio.new_event_loop()
    seq._held_notes = subsequence.held_notes.HeldNotes(
        release_ms=release_ms, latch=latch
    )
    seq._note_input_channel = channel
    seq._note_input_device = device
    return seq


def _note_on(note: int, channel: int = 0, velocity: int = 100) -> mido.Message:
    return mido.Message("note_on", channel=channel, note=note, velocity=velocity)


def _note_off(note: int, channel: int = 0) -> mido.Message:
    return mido.Message("note_off", channel=channel, note=note, velocity=0)


def test_on_midi_input_buffers_note_events() -> None:
    """note_on/note_off append (is_on, pitch, …) tuples to the buffer."""
    seq = _make_seq()
    seq._on_midi_input(_note_on(60), device_idx=0)
    seq._on_midi_input(_note_off(60), device_idx=0)
    events = list(seq._note_input_buffer)
    assert events[0][:3] == (True, 60, 100)
    assert events[1][:3] == (False, 60, 0)


def test_on_midi_input_velocity_zero_is_note_off() -> None:
    """A note_on with velocity 0 (running-status off) buffers as a release."""
    seq = _make_seq()
    seq._on_midi_input(
        mido.Message("note_on", channel=0, note=60, velocity=0), device_idx=0
    )
    assert list(seq._note_input_buffer)[0][:3] == (False, 60, 0)


def test_on_midi_input_channel_filter() -> None:
    """With a channel filter set, notes on other channels are ignored."""
    seq = _make_seq(channel=0)
    seq._on_midi_input(_note_on(60, channel=0), device_idx=0)
    seq._on_midi_input(_note_on(64, channel=5), device_idx=0)
    pitches = [ev[1] for ev in seq._note_input_buffer]
    assert pitches == [60]


def test_on_midi_input_device_filter() -> None:
    """With an input_device filter set, notes from other devices are ignored."""
    seq = _make_seq(device=0)
    seq._on_midi_input(_note_on(60), device_idx=0)
    seq._on_midi_input(_note_on(64), device_idx=1)
    pitches = [ev[1] for ev in seq._note_input_buffer]
    assert pitches == [60]


def test_advance_pulse_drains_into_tracker() -> None:
    """The real loop-thread drain in _advance_pulse feeds the tracker."""
    seq = _make_seq()
    seq._on_midi_input(_note_on(60), device_idx=0)
    seq._on_midi_input(_note_on(64), device_idx=0)
    asyncio.run(seq._advance_pulse())
    assert len(seq._note_input_buffer) == 0  # drained
    assert seq._held_notes.snapshot(time.perf_counter()) == [60, 64]


# ---------------------------------------------------------------------------
# PatternBuilder.held_notes() accessor
# ---------------------------------------------------------------------------


def _builder(
    held: typing.Optional[subsequence.held_notes.HeldNotes] = None,
) -> subsequence.pattern_builder.PatternBuilder:
    pattern = subsequence.pattern.Pattern(channel=0, length=4)
    return subsequence.pattern_builder.PatternBuilder(
        pattern=pattern, cycle=0, default_grid=16, held_notes=held
    )


def test_held_notes_accessor_empty_without_tracker() -> None:
    """No note_input declared (or headless render) → held_notes() is empty."""
    assert _builder().held_notes() == []


def test_held_notes_accessor_returns_snapshot() -> None:
    """With a tracker, held_notes() returns its current sorted snapshot."""
    h = subsequence.held_notes.HeldNotes()
    h.note_on(67, 100, now=0.0)
    h.note_on(60, 100, now=0.0)
    assert _builder(h).held_notes() == [60, 67]


def test_arpeggio_over_held_notes_rests_when_empty() -> None:
    """p.arpeggio(p.held_notes()) places nothing when no keys are held."""
    pattern = subsequence.pattern.Pattern(channel=0, length=4)
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern,
        cycle=0,
        default_grid=16,
        held_notes=subsequence.held_notes.HeldNotes(),
    )
    result = builder.arpeggio(builder.held_notes(), direction="up")
    assert result is builder
    assert pattern.steps == {}


def test_arpeggio_over_held_notes_places_notes() -> None:
    """p.arpeggio(p.held_notes()) arpeggiates whatever the player is holding."""
    h = subsequence.held_notes.HeldNotes()
    for pitch in (60, 64, 67):
        h.note_on(pitch, 100, now=0.0)
    pattern = subsequence.pattern.Pattern(channel=0, length=4)
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern, cycle=0, default_grid=16, held_notes=h
    )

    builder.arpeggio(builder.held_notes(), spacing=1.0, direction="up")

    placed = [note.pitch for step in pattern.steps.values() for note in step.notes]
    assert sorted(set(placed)) == [60, 64, 67]


# ---------------------------------------------------------------------------
# Composition API — note_input() registration
# ---------------------------------------------------------------------------


def test_note_input_stores_config(patch_midi: None) -> None:
    """note_input() records its config on the composition."""
    comp = subsequence.Composition(bpm=120)
    comp.note_input(channel=1, release_ms=40, latch=True)
    assert comp._note_input is not None
    assert comp._note_input["release_ms"] == 40
    assert comp._note_input["latch"] is True


def test_note_input_second_call_raises(patch_midi: None) -> None:
    """v1 supports a single note_input source — a second call is rejected."""
    comp = subsequence.Composition(bpm=120)
    comp.note_input()
    try:
        comp.note_input()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "one note_input source" in str(exc)
