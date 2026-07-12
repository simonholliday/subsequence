"""Tests for MIDI mirroring — `pattern.mirrors`, decorator `mirrors=` parameter,
and the runtime `composition.mirror() / unmirror() / unmirror_all()` API.

The fan-out logic lives in ``Sequencer.schedule_pattern``; most tests exercise
it directly by scheduling a Pattern with ``mirrors`` set and inspecting
``sequencer.event_queue``.
"""

import typing

import pytest

import subsequence
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequencer


# ── Pattern data model ──────────────────────────────────────────────────────


def test_pattern_default_mirrors_empty() -> None:
    """A Pattern constructed without `mirrors` defaults to an empty list."""

    pattern = subsequence.pattern.Pattern(channel=0, length=4)

    assert pattern.mirrors == []


def test_pattern_accepts_mirrors() -> None:
    """Pattern stores mirrors as a list of (device, channel) tuples."""

    pattern = subsequence.pattern.Pattern(channel=0, length=4, mirrors=[(1, 5), (2, 9)])

    assert pattern.mirrors == [(1, 5), (2, 9)]


def test_pattern_mirrors_is_independent_copy() -> None:
    """Mutating the input list after construction must not affect the Pattern."""

    user_list = [(1, 5)]
    pattern = subsequence.pattern.Pattern(channel=0, length=4, mirrors=user_list)
    user_list.append((2, 9))

    assert pattern.mirrors == [(1, 5)]


# ── Sequencer fan-out: notes ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mirror_duplicates_note_events(patch_midi: None) -> None:
    """Note On / Note Off are scheduled for the primary AND each mirror."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5)]
    )
    pattern.add_note(position=0, pitch=60, velocity=100, duration=12)

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = [e for e in sequencer.event_queue if e.message_type == "note_on"]
    note_offs = [e for e in sequencer.event_queue if e.message_type == "note_off"]

    # Two destinations × one note = two note_on + two note_off
    assert len(note_ons) == 2
    assert len(note_offs) == 2

    # Primary on (device=0, channel=0); mirror on (device=1, channel=5)
    primary_on = next(e for e in note_ons if e.device == 0)
    mirror_on = next(e for e in note_ons if e.device == 1)

    assert (primary_on.channel, primary_on.note, primary_on.velocity) == (0, 60, 100)
    assert (mirror_on.channel, mirror_on.note, mirror_on.velocity) == (5, 60, 100)


@pytest.mark.asyncio
async def test_mirror_with_two_destinations_fans_out_three_ways(
    patch_midi: None,
) -> None:
    """Two mirrors → 3× events total (primary + 2 mirrors)."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5), (2, 9)]
    )
    pattern.add_note(position=0, pitch=60, velocity=100, duration=12)

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = sorted(
        [e for e in sequencer.event_queue if e.message_type == "note_on"],
        key=lambda e: e.device,
    )

    assert [(e.device, e.channel) for e in note_ons] == [(0, 0), (1, 5), (2, 9)]


# ── Sequencer fan-out: CC / pitch bend / NRPN ──────────────────────────────


@pytest.mark.asyncio
async def test_mirror_duplicates_cc_events(patch_midi: None) -> None:
    """Plain CC events fan out to mirror destinations."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5)]
    )
    pattern.cc_events.append(
        subsequence.pattern.CcEvent(
            pulse=0, message_type="control_change", control=74, value=100
        )
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    ccs = [e for e in sequencer.event_queue if e.message_type == "control_change"]
    assert len(ccs) == 2

    by_device = {e.device: e for e in ccs}
    assert (
        by_device[0].channel == 0
        and by_device[0].control == 74
        and by_device[0].value == 100
    )
    assert (
        by_device[1].channel == 5
        and by_device[1].control == 74
        and by_device[1].value == 100
    )


@pytest.mark.asyncio
async def test_mirror_duplicates_pitchwheel_events(patch_midi: None) -> None:
    """Pitch bend events fan out to mirror destinations."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5)]
    )
    pattern.cc_events.append(
        subsequence.pattern.CcEvent(pulse=0, message_type="pitchwheel", value=4000)
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    pbs = [e for e in sequencer.event_queue if e.message_type == "pitchwheel"]
    assert len(pbs) == 2

    by_device = {e.device: e for e in pbs}
    assert by_device[0].channel == 0 and by_device[0].value == 4000
    assert by_device[1].channel == 5 and by_device[1].value == 4000


@pytest.mark.asyncio
async def test_mirror_preserves_nrpn_burst_ordering(patch_midi: None) -> None:
    """A 4-CC NRPN burst at the same pulse stays in 99→98→6→38 order on the mirror.

    This is a regression fence for the ``MidiEvent.sequence`` tie-breaker —
    without it the heap would scramble same-pulse mirrored CCs.
    """

    import heapq

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5)]
    )

    # Build an NRPN burst at pulse 0
    for cc in (99, 98, 6, 38):
        pattern.cc_events.append(
            subsequence.pattern.CcEvent(
                pulse=0, message_type="control_change", control=cc, value=cc
            )
        )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    # Pop everything from the heap and check ordering per device
    order_by_device: typing.Dict[int, list] = {}
    while sequencer.event_queue:
        ev = heapq.heappop(sequencer.event_queue)
        if ev.message_type == "control_change":
            order_by_device.setdefault(ev.device, []).append(ev.control)

    assert order_by_device[0] == [99, 98, 6, 38]
    assert order_by_device[1] == [99, 98, 6, 38]


# ── Sequencer fan-out: drones ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mirror_duplicates_drone_events(patch_midi: None) -> None:
    """Drone (raw_note_event) events fan out to mirror destinations."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5)]
    )
    pattern.raw_note_events.append(
        subsequence.pattern.RawNoteEvent(
            pulse=0, message_type="note_on", pitch=48, velocity=80
        )
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    notes = [e for e in sequencer.event_queue if e.message_type == "note_on"]
    assert len(notes) == 2

    by_device = {e.device: e for e in notes}
    assert by_device[0].channel == 0 and by_device[0].note == 48
    assert by_device[1].channel == 5 and by_device[1].note == 48


# ── OSC events are NOT mirrored ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mirror_does_not_duplicate_osc_events(patch_midi: None) -> None:
    """OSC events are deliberately excluded from mirroring."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5), (2, 9)]
    )
    pattern.osc_events.append(
        subsequence.pattern.OscEvent(pulse=0, address="/fader/1", args=(0.8,))
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    osc = [e for e in sequencer.event_queue if e.message_type == "osc"]
    assert len(osc) == 1


# ── CcEvent override semantics with mirrors ─────────────────────────────────


@pytest.mark.asyncio
async def test_mirror_ignores_cc_event_channel_override(patch_midi: None) -> None:
    """A CcEvent with explicit `channel=` overrides the primary only.

    Mirrors always use their pinned channel — by design, since the override
    is meaningful for the primary's port (e.g. polyphonic-tuning rotation)
    but mirrors are independent destinations.
    """

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 9)]
    )

    # CcEvent targets channel 7 explicitly (e.g. polyphonic-tuning bend).
    pattern.cc_events.append(
        subsequence.pattern.CcEvent(
            pulse=0, message_type="pitchwheel", value=2000, channel=7
        )
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    pbs = [e for e in sequencer.event_queue if e.message_type == "pitchwheel"]
    assert len(pbs) == 2

    by_device = {e.device: e for e in pbs}
    # Primary respected the explicit channel=7
    assert by_device[0].channel == 7
    # Mirror used its pinned channel (9), ignoring the override
    assert by_device[1].channel == 9


# ── Decorator integration ──────────────────────────────────────────────────


def test_pattern_decorator_accepts_mirrors() -> None:
    """@composition.pattern(..., mirrors=[...]) carries through to _PendingPattern."""

    composition = subsequence.Composition(bpm=120)

    @composition.pattern(channel=1, beats=4, mirrors=[(1, 10), (2, 1)])
    def p1(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    pending = composition._pending_patterns[0]
    # Channel 1 (1-indexed) → 0; Channel 10 → 9; Channel 1 → 0
    assert pending.mirrors == [(1, 9), (2, 0)]


def test_pattern_decorator_resolves_channels_zero_indexed() -> None:
    """Mirror channels go through `_resolve_channel`, honouring zero_indexed_channels."""

    composition = subsequence.Composition(bpm=120, zero_indexed_channels=True)

    @composition.pattern(channel=0, beats=4, mirrors=[(1, 9)])
    def p2(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    pending = composition._pending_patterns[0]
    assert pending.mirrors == [(1, 9)]  # 0-indexed input passed through unchanged


def test_pattern_decorator_validates_mirror_shape() -> None:
    """Malformed mirror entries raise ValueError at decoration time."""

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(ValueError, match="2 or 3 elements"):

        @composition.pattern(channel=1, beats=4, mirrors=[(1,)])  # type: ignore[list-item]
        def bad1(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass


def test_pattern_decorator_accepts_list_mirrors() -> None:
    """Mirror entries can be lists, not just tuples — useful for JSON-driven configs."""

    composition = subsequence.Composition(bpm=120)

    @composition.pattern(channel=1, beats=4, mirrors=[[1, 5], [2, 9]])  # type: ignore[list-item]
    def from_config(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    pending = composition._pending_patterns[0]
    assert pending.mirrors == [(1, 4), (2, 8)]


def test_pattern_decorator_rejects_bool_as_device() -> None:
    """``True`` / ``False`` are technically int subclasses but should be rejected as devices."""

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(ValueError, match="Mirror device must be an integer"):

        @composition.pattern(channel=1, beats=4, mirrors=[(True, 5)])  # type: ignore[list-item]
        def bad_bool(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass


def test_pattern_decorator_validates_device_type() -> None:
    """Non-integer device raises ValueError at decoration time."""

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(ValueError, match="Mirror device must be an integer"):

        @composition.pattern(channel=1, beats=4, mirrors=[("synth_b", 5)])  # type: ignore[list-item]
        def bad2(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass


def test_pattern_decorator_validates_channel() -> None:
    """Mirror channel out of range raises via _resolve_channel."""

    composition = subsequence.Composition(bpm=120)  # 1-indexed default

    with pytest.raises(ValueError, match="MIDI channel must be 1-16"):

        @composition.pattern(
            channel=1, beats=4, mirrors=[(1, 0)]
        )  # 0 invalid in 1-indexed mode
        def bad3(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass


def test_layer_decorator_accepts_mirrors() -> None:
    """composition.layer(..., mirrors=[...]) carries through."""

    composition = subsequence.Composition(bpm=120)

    def part_a(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    def part_b(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    composition.layer(part_a, part_b, channel=1, beats=4, mirrors=[(1, 5)])

    pending = composition._pending_patterns[0]
    assert pending.mirrors == [(1, 4)]


@pytest.mark.asyncio
async def test_trigger_with_mirrors_fans_out(patch_midi: None) -> None:
    """composition.trigger(mirrors=...) duplicates events onto mirror destinations.

    The full trigger path: temp Pattern → PatternBuilder → schedule_pattern.
    Verifies the mirrors list survives the round trip and the sequencer
    fan-outs to both destinations.
    """

    import asyncio

    composition = subsequence.Composition(bpm=120)
    # trigger() needs an event loop reference to defer scheduling onto.  In a
    # real run that's set in Sequencer.start(); for this test we set it
    # explicitly to the running loop.
    composition._sequencer._event_loop = asyncio.get_event_loop()

    composition.trigger(
        lambda p: p.note(60, beat=0, velocity=100, duration=0.5),
        channel=1,
        beats=1,
        mirrors=[(1, 5)],
    )

    # trigger() spawns an asyncio task for schedule_pattern; let it complete.
    await asyncio.sleep(0)

    note_ons = [
        e for e in composition._sequencer.event_queue if e.message_type == "note_on"
    ]
    # Primary on (device=0); mirror on (device=1)
    assert sorted({e.device for e in note_ons}) == [0, 1]

    # Both events carry the same note number on their respective channels.
    # Composition is in default 1-indexed mode, so channel=1 → 0 internal,
    # and the mirror's channel=5 → 4 internal.
    by_device = {e.device: e for e in note_ons}
    assert by_device[0].channel == 0
    assert by_device[0].note == 60
    assert by_device[1].channel == 4
    assert by_device[1].note == 60


# ── Runtime API ────────────────────────────────────────────────────────────


def _running_pattern_stub(
    channel: int = 0, mirrors: typing.Optional[list] = None
) -> typing.Any:
    """Minimal stand-in for a running pattern with the fields composition.mirror() touches."""

    pat = subsequence.pattern.Pattern(channel=channel, length=4, mirrors=mirrors)
    pat._muted = False
    pat._tweaks = {}
    pat._cycle_count = 0
    return pat


def test_runtime_mirror_adds_destination() -> None:
    """composition.mirror() appends to the running pattern's mirrors list."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub()

    composition.mirror("drums", device=1, channel=10)

    assert composition._running_patterns["drums"].mirrors == [(1, 9)]


def test_runtime_mirror_is_idempotent() -> None:
    """Adding the same destination twice does not double-fan."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub()

    composition.mirror("drums", device=1, channel=10)
    composition.mirror("drums", device=1, channel=10)

    assert composition._running_patterns["drums"].mirrors == [(1, 9)]


def test_runtime_unmirror_removes_destination() -> None:
    """composition.unmirror() removes a single destination."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub(
        mirrors=[(1, 9), (2, 4)]
    )

    composition.unmirror("drums", device=1, channel=10)

    assert composition._running_patterns["drums"].mirrors == [(2, 4)]


def test_runtime_unmirror_silent_on_missing_destination() -> None:
    """Removing a destination that isn't there is a no-op (idempotent)."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub(mirrors=[(1, 9)])

    composition.unmirror("drums", device=2, channel=5)  # not present — should not raise

    assert composition._running_patterns["drums"].mirrors == [(1, 9)]


def test_runtime_unmirror_all_clears_destinations() -> None:
    """composition.unmirror_all() clears the mirrors list."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub(
        mirrors=[(1, 9), (2, 4)]
    )

    composition.unmirror_all("drums")

    assert composition._running_patterns["drums"].mirrors == []


def test_runtime_mirror_unknown_pattern_raises() -> None:
    """Operating on a non-existent pattern raises ValueError."""

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(ValueError, match="not found"):
        composition.mirror("unknown", device=1, channel=10)

    with pytest.raises(ValueError, match="not found"):
        composition.unmirror("unknown", device=1, channel=10)

    with pytest.raises(ValueError, match="not found"):
        composition.unmirror_all("unknown")


def test_runtime_mirror_validates_channel() -> None:
    """composition.mirror() validates channel via _resolve_channel."""

    composition = subsequence.Composition(bpm=120)  # 1-indexed
    composition._running_patterns["drums"] = _running_pattern_stub()

    with pytest.raises(ValueError, match="MIDI channel must be 1-16"):
        composition.mirror("drums", device=1, channel=0)


def test_runtime_mirror_warns_on_mirror_to_self(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mirroring a pattern to its own (device, channel) logs a warning."""

    import logging

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub(
        channel=4
    )  # internal 0-indexed = 4

    with caplog.at_level(logging.WARNING):
        composition.mirror("drums", device=0, channel=5)  # 5 → 4 internal == primary

    assert any("primary destination" in record.message for record in caplog.records)


def test_decorator_warns_on_mirror_to_self(caplog: pytest.LogCaptureFixture) -> None:
    """@composition.pattern(mirrors=...) where a mirror equals the primary logs a warning.

    Composition default is 1-indexed channels.  ``channel=1`` → internal 0;
    ``channel=2`` → internal 1.  A mirror tuple is ``(device, user_channel)``
    resolved the same way.
    """

    import logging

    composition = subsequence.Composition(bpm=120)

    with caplog.at_level(logging.WARNING):
        # Primary (device=0, channel=0); mirror (device=0, channel=1) — different, no warn.
        @composition.pattern(channel=1, beats=4, mirrors=[(0, 2)])
        def ok(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass

        # Primary (device=0, channel=1); mirror (device=0, channel=1) — collision.
        @composition.pattern(channel=2, beats=4, mirrors=[(0, 2)])
        def bad(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass

    # Only the second pattern's mirror collides
    warnings = [r for r in caplog.records if "primary destination" in r.message]
    assert len(warnings) == 1


def test_runtime_unmirror_debug_log_when_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """unmirror() on a missing destination logs a debug message (not an error)."""

    import logging

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub(mirrors=[(1, 9)])

    with caplog.at_level(logging.DEBUG):
        composition.unmirror("drums", device=2, channel=5)

    assert any("no-op" in record.message for record in caplog.records)


# ── Mute interaction ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mirror_with_muted_pattern_produces_no_events(patch_midi: None) -> None:
    """A muted pattern emits nothing on either the primary or any mirror.

    Tests the full path through the sequencer: a muted ``_DecoratorPattern``
    short-circuits in ``_rebuild`` so its event collections stay empty;
    ``schedule_pattern`` then has nothing to fan out.  Worth pinning so a
    future change to mute or to the fan-out doesn't accidentally leak events
    to mirrors.
    """

    composition = subsequence.Composition(bpm=120)

    @composition.pattern(channel=1, beats=4, mirrors=[(1, 5)])
    def silent(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        p.note(60, beat=0, velocity=100, duration=0.5)

    pending = composition._pending_patterns[0]
    pattern = composition._build_pattern_from_pending(pending)

    pattern._muted = True
    pattern._rebuild()

    await composition._sequencer.schedule_pattern(pattern, start_pulse=0)

    # Sequencer queue should be empty on both destinations.
    assert composition._sequencer.event_queue == []


# ── Symbolic mirror (per-destination drum_note_map) ─────────────────────────


def test_resolve_mirrors_normalizes_three_tuple() -> None:
    """A 3-tuple mirror resolves the channel and preserves the drum map."""

    composition = subsequence.Composition(bpm=120)  # 1-indexed
    gm = {"hi_hat_closed": 42}

    @composition.pattern(channel=1, beats=4, mirrors=[(1, 10, gm)])
    def drums(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    pending = composition._pending_patterns[0]
    assert pending.mirrors == [(1, 9, gm)]  # channel 10 → 9, map preserved


def test_resolve_mirrors_rejects_non_dict_map() -> None:
    """A non-dict third element raises at decoration time."""

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(ValueError, match="drum_note_map must be a dict"):

        @composition.pattern(channel=1, beats=4, mirrors=[(1, 10, "not a dict")])  # type: ignore[list-item]
        def bad(p: "subsequence.pattern_builder.PatternBuilder") -> None:
            pass


def test_destination_pitch_helper() -> None:
    """``_destination_pitch`` covers every branch incl. drop (None) and primary_unmapped."""

    named = subsequence.pattern.Note(
        pitch=44, velocity=100, duration=6, channel=0, origin="hi_hat_closed"
    )
    unnamed = subsequence.pattern.Note(
        pitch=44, velocity=100, duration=6, channel=0, origin=None
    )
    other = subsequence.pattern.Note(
        pitch=44, velocity=100, duration=6, channel=0, origin="clap"
    )
    unmapped = subsequence.pattern.Note(
        pitch=49,
        velocity=100,
        duration=6,
        channel=0,
        origin="crash",
        primary_unmapped=True,
    )

    with_map = subsequence.sequencer._MirrorTarget(1, 5, {"hi_hat_closed": 42})
    crash_map = subsequence.sequencer._MirrorTarget(1, 5, {"crash": 49})
    no_map = subsequence.sequencer._MirrorTarget(1, 5, None)

    dp = subsequence.sequencer._destination_pitch

    # Primary uses the already-resolved pitch.
    assert dp(named, with_map, primary=True) == 44
    # Mirror + map + matching name → re-resolved.
    assert dp(named, with_map, primary=False) == 42
    # Mirror + map + name absent → DROP (not a wrong number).
    assert dp(other, with_map, primary=False) is None
    # Mirror + map + no origin → copy the literal pitch.
    assert dp(unnamed, with_map, primary=False) == 44
    # Mirror + no map (2-tuple) → copy the literal pitch.
    assert dp(named, no_map, primary=False) == 44
    # primary_unmapped: primary and 2-tuple mirrors drop it; only a mirror whose
    # map contains the name voices it.
    assert dp(unmapped, crash_map, primary=True) is None
    assert dp(unmapped, no_map, primary=False) is None
    assert dp(unmapped, crash_map, primary=False) == 49
    assert dp(unmapped, with_map, primary=False) is None  # mirror lacks "crash" → drop


@pytest.mark.asyncio
async def test_symbolic_mirror_fans_out_per_device_map(patch_midi: None) -> None:
    """The headline case: one named hit, two device-specific notes.

    A closed hi-hat is note 44 on the primary (DRM1) and 42 on the mirror (GM).
    """

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5, {"hi_hat_closed": 42})]
    )
    pattern.add_note(
        position=0, pitch=44, velocity=100, duration=12, origin="hi_hat_closed"
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = [e for e in sequencer.event_queue if e.message_type == "note_on"]
    by_device = {e.device: e for e in note_ons}

    assert by_device[0].note == 44  # primary: the DRM1's resolved note
    assert by_device[1].note == 42  # mirror: re-resolved via the GM map


@pytest.mark.asyncio
async def test_symbolic_mirror_drops_when_name_absent(patch_midi: None) -> None:
    """A name absent from the mirror's map is dropped on the mirror (not a wrong note)."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5, {"hi_hat_closed": 42})]
    )
    pattern.add_note(
        position=0, pitch=44, velocity=100, duration=12, origin="clap"
    )  # not in mirror map

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = [e for e in sequencer.event_queue if e.message_type == "note_on"]
    by_device = {e.device: e for e in note_ons}

    assert by_device[0].note == 44  # primary plays it
    assert 1 not in by_device  # mirror has no voice for "clap" → silent


@pytest.mark.asyncio
async def test_symbolic_mirror_drop_logs_debug(
    patch_midi: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A per-mirror drop is surfaced at debug level — the diagnostic for a voice
    the primary plays but a mirror's map lacks (the build-time warning only
    covers a name absent from *every* destination)."""

    import logging

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5, {"hi_hat_closed": 42})]
    )
    pattern.add_note(
        position=0, pitch=44, velocity=100, duration=12, origin="clap"
    )  # absent from the mirror map

    with caplog.at_level(logging.DEBUG):
        await sequencer.schedule_pattern(pattern, start_pulse=0)

    assert any("clap" in r.message and "no voice" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_symbolic_mirror_crash_authored_on_primary_plays_only_on_mirror(
    patch_midi: None,
) -> None:
    """End-to-end (builder → schedule): a voice the primary lacks but a mirror maps is
    silent on the primary and sounds on the mirror — the faithful-core scenario.

    Also exercises the other direction: the kick (absent from this mirror's map)
    is dropped on the mirror.
    """

    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5, {"kick": 36, "crash": 49})]
    )
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern, cycle=0, drum_note_map={"kick": 36}, default_grid=16
    )
    builder.note("kick", beat=0)
    builder.note(
        "crash", beat=0
    )  # DRM1-like primary has no crash; the GM-like mirror does

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = [e for e in sequencer.event_queue if e.message_type == "note_on"]
    primary = sorted(e.note for e in note_ons if e.device == 0)
    mirror = sorted(e.note for e in note_ons if e.device == 1)

    assert primary == [36]  # kick only — the crash has no primary voice
    assert mirror == [36, 49]  # the mirror plays both the kick and the crash


@pytest.mark.asyncio
async def test_symbolic_mirror_two_tuple_no_translation(patch_midi: None) -> None:
    """A plain 2-tuple mirror copies the number even when the note is named."""

    sequencer = subsequence.sequencer.Sequencer(
        output_device_name="Dummy MIDI", initial_bpm=120
    )
    pattern = subsequence.pattern.Pattern(
        channel=0, length=4, device=0, mirrors=[(1, 5)]
    )
    pattern.add_note(
        position=0, pitch=44, velocity=100, duration=12, origin="hi_hat_closed"
    )

    await sequencer.schedule_pattern(pattern, start_pulse=0)

    note_ons = [e for e in sequencer.event_queue if e.message_type == "note_on"]
    by_device = {e.device: e for e in note_ons}

    assert by_device[0].note == 44
    assert by_device[1].note == 44  # legacy behaviour, unchanged


def test_runtime_mirror_with_drum_note_map() -> None:
    """composition.mirror(..., drum_note_map=...) stores a 3-tuple entry."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub()
    gm = {"hi_hat_closed": 42}

    composition.mirror("drums", device=1, channel=10, drum_note_map=gm)

    assert composition._running_patterns["drums"].mirrors == [(1, 9, gm)]


def test_runtime_unmirror_ignores_map() -> None:
    """unmirror() removes a 3-tuple entry matching on (device, channel) only."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub(
        mirrors=[(1, 9, {"hi_hat_closed": 42})]
    )

    composition.unmirror("drums", device=1, channel=10)  # no map argument

    assert composition._running_patterns["drums"].mirrors == []


def test_runtime_mirror_updates_map_in_place() -> None:
    """Re-mirroring the same (device, channel) with a new map re-points it."""

    composition = subsequence.Composition(bpm=120)
    composition._running_patterns["drums"] = _running_pattern_stub()

    composition.mirror(
        "drums", device=1, channel=10, drum_note_map={"hi_hat_closed": 42}
    )
    composition.mirror(
        "drums", device=1, channel=10, drum_note_map={"hi_hat_closed": 99}
    )

    mirrors = composition._running_patterns["drums"].mirrors
    assert len(mirrors) == 1
    assert mirrors[0] == (1, 9, {"hi_hat_closed": 99})
