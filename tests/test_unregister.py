"""Tests for ``Composition.unregister()`` — full pattern removal.

Unlike ``mute()`` (which keeps the pattern alive but silent), ``unregister()``
sets a ``_removed`` flag, sends note-offs for the pattern's sounding notes
(including on mirror destinations), and drops the entry from
``_running_patterns``.
"""

import asyncio
import logging
import typing

import mido
import pytest

import subsequence
import subsequence.pattern
import subsequence.sequencer

import tests.conftest as conftest


def _running_pattern_stub(
    channel: int = 0,
    device: int = 0,
    mirrors: typing.Optional[list] = None,
) -> typing.Any:
    """Minimal stand-in for a running pattern with the fields unregister() touches."""

    pat = subsequence.pattern.Pattern(
        channel=channel, length=4, device=device, mirrors=mirrors
    )
    pat._muted = False
    pat._tweaks = {}
    pat._cycle_count = 0
    return pat


# ── Flag and dict mutation ──────────────────────────────────────────────────


def test_unregister_sets_removed_flag(patch_midi: None) -> None:
    """unregister() sets pattern._removed = True."""

    composition = subsequence.Composition(bpm=120)
    pattern = _running_pattern_stub()
    composition._running_patterns["drums"] = pattern

    composition.unregister("drums")

    assert pattern._removed is True


def test_unregister_removes_from_running_patterns(patch_midi: None) -> None:
    """After unregister(), the name is gone from _running_patterns."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub()

    composition.unregister("drums")

    assert "drums" not in composition._running_patterns


def test_unregister_unknown_pattern_is_silent(
    patch_midi: None, caplog: pytest.LogCaptureFixture
) -> None:
    """unregister() on a non-existent name is a debug-log no-op."""

    composition = subsequence.Composition(bpm=120)

    with caplog.at_level(logging.DEBUG):
        composition.unregister("not_running")

    assert any("no-op" in r.message for r in caplog.records)


def test_unregister_idempotent(patch_midi: None) -> None:
    """Calling unregister() twice on the same name doesn't crash."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub()

    composition.unregister("drums")
    composition.unregister("drums")  # already gone — second call is no-op

    assert "drums" not in composition._running_patterns


# ── Reschedule loop skip ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reschedule_loop_skips_removed_patterns(patch_midi: None) -> None:
    """A ScheduledPattern with pattern._removed=True is popped but never re-added.

    Direct test against the sequencer: schedule a pattern, set the flag,
    pump the reschedule loop, verify the queue is empty after.
    """

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)

    # Schedule the pattern so it lives in reschedule_queue.
    await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)
    assert len(sequencer.reschedule_queue) == 1

    # Flag it for removal.
    pattern._removed = True

    # Pump _maybe_reschedule_patterns at a pulse past the next_reschedule_pulse
    # to force the pop.  The reschedule loop runs inside this method.
    await sequencer._maybe_reschedule_patterns(pulse=1000)

    # Queue is empty: the pattern was popped and not re-added.
    assert sequencer.reschedule_queue == []


# ── Note-off targeting ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unregister_stops_active_notes_on_primary(patch_midi: None) -> None:
    """unregister() sends note_off for the pattern's notes on its primary destination."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )

    # Inject a SpyMidiOut so we can inspect outgoing messages.
    spy = conftest.SpyMidiOut()
    sequencer.midi_out = spy

    pattern = subsequence.pattern.Pattern(channel=5, length=4, device=0)

    # Simulate a sounding note: (device=0, channel=5, note=60).
    sequencer.active_notes.add((0, 5, 60))

    await sequencer._stop_pattern_notes(pattern)

    # Spy received exactly one note_off on (channel=5, note=60).
    note_offs = [m for m in spy.sent if m.type == "note_off"]
    assert len(note_offs) == 1
    assert note_offs[0].channel == 5
    assert note_offs[0].note == 60

    # Active note cleared.
    assert (0, 5, 60) not in sequencer.active_notes


@pytest.mark.asyncio
async def test_unregister_stops_active_notes_on_mirrors(patch_midi: None) -> None:
    """Pattern with mirrors: note_offs go to every (device, channel) destination."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )

    spy0 = conftest.SpyMidiOut()
    spy1 = conftest.SpyMidiOut()
    sequencer.midi_out = spy0
    sequencer._output_devices.add("Secondary", spy1)

    # Pattern primary (device=0, channel=2), mirror (device=1, channel=7).
    pattern = subsequence.pattern.Pattern(
        channel=2, length=4, device=0, mirrors=[(1, 7)]
    )

    # Sounding notes on each destination.
    sequencer.active_notes.add((0, 2, 60))
    sequencer.active_notes.add((1, 7, 60))
    # Unrelated note on a different channel — should NOT be touched.
    sequencer.active_notes.add((0, 9, 36))

    await sequencer._stop_pattern_notes(pattern)

    # Each spy got exactly one note_off matching its destination.
    primary_offs = [m for m in spy0.sent if m.type == "note_off"]
    mirror_offs = [m for m in spy1.sent if m.type == "note_off"]

    assert len(primary_offs) == 1
    assert primary_offs[0].channel == 2 and primary_offs[0].note == 60

    assert len(mirror_offs) == 1
    assert mirror_offs[0].channel == 7 and mirror_offs[0].note == 60

    # The unrelated note survives.
    assert (0, 9, 36) in sequencer.active_notes
    assert (0, 2, 60) not in sequencer.active_notes
    assert (1, 7, 60) not in sequencer.active_notes


@pytest.mark.asyncio
async def test_unregister_with_no_active_notes_does_not_crash(patch_midi: None) -> None:
    """Calling _stop_pattern_notes on a pattern with no sounding notes is a no-op."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)

    await sequencer._stop_pattern_notes(pattern)

    assert sequencer.active_notes == set()


# ── live_info() excludes unregistered patterns ─────────────────────────────


def test_live_info_excludes_unregistered_pattern(patch_midi: None) -> None:
    """composition.live_info() doesn't list patterns that have been unregistered."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["keeper"] = _running_pattern_stub(channel=0)
    composition._running_patterns["goner"] = _running_pattern_stub(channel=1)

    composition.unregister("goner")

    info = composition.live_info()
    pattern_names = [p["name"] for p in info["patterns"]]

    assert "keeper" in pattern_names
    assert "goner" not in pattern_names
