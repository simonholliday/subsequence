"""The top-level ``Composition`` — the object a whole piece is built on.

``Composition`` is the single entry point: it owns the clock, the patterns,
the harmony and form state, and the MIDI output.  You create one, decorate
pattern functions onto it with ``@composition.pattern``, and call ``play()``.
``HarmonyView`` and ``ScheduleContext`` here are the read-only views handed to
pattern and callback functions at run time.
"""

import asyncio
import builtins
import dataclasses
import inspect
import logging
import os
import pathlib
import random
import re
import signal
import types
import typing
import zlib
import subsequence.cadences
import subsequence.chord_graphs
import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.constants.velocity
import subsequence.display
import subsequence.harmonic_state
import subsequence.held_notes
import subsequence.keystroke
import subsequence.live_reloader
import subsequence.live_server
import subsequence.midi_utils
import subsequence.osc
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.progressions
import subsequence.sequence_utils
import subsequence.sequencer
import subsequence.voicings
import subsequence.web_ui
import subsequence.weighted_graph
import subsequence.conductor
import subsequence.form_state
import subsequence.forms
import subsequence.link_clock


logger = logging.getLogger(__name__)


# Above this whole-rig latency (ms), delay compensation is delaying every
# faster device enough that live-input feel may suffer — worth a warning.
_LATENCY_WARN_THRESHOLD_MS = 30.0


# ---------------------------------------------------------------------------
# Hotkey support — dataclasses and label derivation
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class HotkeyBinding:
    """A registered keyboard shortcut and its associated action.

    Attributes:
            key: The single character that triggers this binding.
            action: Zero-argument callable executed when the key fires.
            quantize: ``0`` = execute immediately; ``N`` = execute on the
                    next global bar divisible by *N*.
            label: Human-readable description shown by the ``?`` help key.
    """

    key: str
    action: typing.Callable[[], None]
    quantize: int
    label: str


@dataclasses.dataclass
class _PendingHotkeyAction:
    """An action that has been triggered but is waiting for its quantize boundary."""

    binding: HotkeyBinding


_HOTKEY_RESERVED = "?"
"""Key reserved for listing all active hotkeys."""


def _derive_label(action: typing.Callable[[], None]) -> str:
    """Auto-derive a display label for *action*.

    Tried in order:

    1. **Named function** — returns ``fn.__name__``.
    2. **Lambda in a ``.py`` file** — uses :func:`inspect.getsource` to extract
       the lambda body from the source line (works for compositions defined in
       files; falls back gracefully in REPLs and ``exec()`` contexts).
    3. **Fallback** — returns ``"<action>"``.

    Args:
            action: The callable registered as a hotkey action.

    Returns:
            A short, readable string suitable for the ``?`` help listing.
    """

    name: typing.Optional[str] = getattr(action, "__name__", None)
    if name and name != "<lambda>":
        return name

    # Lambda — try to extract the body from the source line.
    try:
        source = inspect.getsource(action).strip()
        match = re.search(r"lambda\b[^:]*:\s*(.+)", source)
        if match:
            body = match.group(1).strip()
            # Strip trailing kwargs that belong to the outer hotkey() call.
            body = re.sub(r"[,\s]*(quantize|label)\s*=.*", "", body)
            body = body.rstrip(" ,)")
            if body:
                return body
    except (OSError, TypeError):
        pass

    return "<action>"


def _fn_has_parameter(fn: typing.Callable, name: str) -> bool:
    """Check whether a callable accepts a parameter with the given name."""

    return name in inspect.signature(fn).parameters


@dataclasses.dataclass
class ScheduleContext:
    """
    Context object passed to ``composition.schedule()`` callbacks
    whose signature declares a first parameter (conventionally named ``p``).

    Attributes:
            cycle: How many times this callback has been called so far (0-indexed).
                       0 on the first call, including the blocking ``wait_for_initial`` run.
    """

    cycle: int


@dataclasses.dataclass
class _AdditionalOutput:
    """A MIDI output device registered via ``composition.midi_output()``.

    Attributes:
            device: The exact MIDI output port name.
            alias: Optional friendly name for device-id lookups.
            latency_ms: Physical output latency in milliseconds for delay
                    compensation (0.0 = no compensation).
    """

    device: str
    alias: typing.Optional[str] = None
    latency_ms: float = 0.0


# The one progression type (subsequence/progressions.py) — re-exported here
# because freeze() returns it and the clock walks it.  The old engine-side
# Progression dataclass (chords + trailing_history) is absorbed into it.
Progression = subsequence.progressions.Progression


class _InjectedChord:
    """
    Wraps a Chord with key context so tones() transposes correctly.
    """

    def __init__(
        self,
        chord: typing.Any,
        voice_leading_state: typing.Optional[
            subsequence.voicings.VoiceLeadingState
        ] = None,
        next_chord: typing.Optional[typing.Any] = None,
        beats_remaining: typing.Optional[float] = None,
    ) -> None:
        """
        Store the chord, optional voice leading state, and the harmony
        window's anticipation data (the chord after this one and the beats
        until it arrives), when known.
        """

        self._chord = chord
        self._voice_leading_state = voice_leading_state
        self._next_chord = next_chord
        self._beats_remaining = beats_remaining

    @property
    def next(self) -> typing.Optional["_InjectedChord"]:
        """The chord after the current one — planned and revocable.

        Sugar over the harmony window (``p.harmony.next_chord``), so
        two-parameter builders get anticipation without learning a new
        object.  ``None`` when the window has no committed next chord.
        Voice leading is not applied (the voicing belongs to the chord
        that is actually sounding).
        """

        if self._next_chord is None:
            return None

        return _InjectedChord(self._next_chord)

    @property
    def beats_remaining(self) -> typing.Optional[float]:
        """Beats until the next chord boundary (from this cycle's start), when known."""

        return self._beats_remaining

    def root_midi(self, base: int) -> int:
        """
        Return the MIDI note for this chord's root that is closest to ``base``.
        """

        # Delegate to the chord's own root_note() rather than reimplementing
        # the pitch-class offset arithmetic.
        return self._chord.root_note(base)  # type: ignore[no-any-return]

    def tones(
        self, root: int, inversion: int = 0, count: typing.Optional[int] = None
    ) -> typing.List[int]:
        """Return MIDI note numbers transposed to the correct chord root.

        When voice leading is active, the best inversion is chosen
        automatically and the ``inversion`` parameter is ignored.

        When ``count`` is set, the chord intervals cycle into higher
        octaves until ``count`` notes are produced.
        """

        midi_root = self.root_midi(root)
        intervals = self._chord.intervals()

        if self._voice_leading_state is not None:
            base = self._voice_leading_state.next(intervals, midi_root)
            if count is not None:
                n = len(base)
                base_intervals = [p - base[0] for p in base]
                return [
                    base[0] + base_intervals[i % n] + 12 * (i // n)
                    for i in range(count)
                ]
            return base

        if inversion != 0:
            intervals = subsequence.voicings.invert_chord(intervals, inversion)

        if count is not None:
            n = len(intervals)
            return [midi_root + intervals[i % n] + 12 * (i // n) for i in range(count)]

        return [midi_root + interval for interval in intervals]

    def root_note(self, root_midi: int) -> int:
        """Return the MIDI note number for the chord root nearest to *root_midi*."""

        # Delegate to root_midi(), NOT tones(): under voice leading, tones()
        # returns the smoothest INVERSION (whose bass is often not the root)
        # and advances the voicing state — a read must do neither.
        return self.root_midi(root_midi)

    def bass_note(self, root_midi: int, octave_offset: int = -1) -> int:
        """Return the chord root shifted by a number of octaves."""

        return self.root_midi(root_midi) + (12 * octave_offset)

    def intervals(self) -> typing.List[int]:
        """
        Forward to the underlying chord's intervals.
        """

        return self._chord.intervals()  # type: ignore[no-any-return]

    def name(self) -> str:
        """
        Forward to the underlying chord's name.
        """

        return self._chord.name()  # type: ignore[no-any-return]


class _HarmonyHorizon:
    """The published harmony window — realised chord spans on the absolute beat axis.

    The harmonic clock commits one span per chord boundary (decorated chords
    where the source span is spiced) and, where the future is data (a bound
    or section progression), installs a *future* lookup so ``chord_at`` can
    answer arbitrarily far ahead.  In live graph mode the window is
    ``[current, next]`` — one pre-committed step — and queries beyond it
    clamp to the last known chord with a one-time warning.

    All beats are absolute (from playback start).  Read through
    :class:`HarmonyView` inside patterns, or :meth:`Composition.current_chord`
    for the chord sounding at the playhead.
    """

    def __init__(self) -> None:
        """Start with an empty window."""

        self._spans: typing.List[typing.Tuple[float, float, typing.Any]] = []
        self._future: typing.Optional[
            typing.Callable[
                [float], typing.Optional[typing.Tuple[float, float, typing.Any]]
            ]
        ] = None
        self._planned: typing.Optional[typing.Tuple[float, float, typing.Any]] = None
        self._warned_beyond = False

    @property
    def is_empty(self) -> bool:
        """True when nothing has been committed yet (no harmony configured)."""

        return not self._spans

    def reset(self) -> None:
        """Clear everything (a fresh playback)."""

        self._spans = []
        self._future = None
        self._planned = None
        self._warned_beyond = False

    def commit(self, start: float, end: float, chord: typing.Any) -> None:
        """Commit a realised span.  A commit at an earlier start truncates the tail."""

        while self._spans and self._spans[-1][0] >= start - 1e-9:
            self._spans.pop()

        if self._spans and self._spans[-1][1] > start:
            previous_start, _, previous_chord = self._spans[-1]
            self._spans[-1] = (previous_start, start, previous_chord)

        self._spans.append((start, end, chord))

        if self._planned is not None and self._planned[0] < end:
            self._planned = None

        # Keep a bounded history so long sessions don't grow without limit.
        while len(self._spans) > 64:
            self._spans.pop(0)

    def set_planned(self, start: float, end: float, chord: typing.Any) -> None:
        """Publish the live engine's pre-committed next step."""

        self._planned = (start, end, chord)

    def set_future(
        self,
        fn: typing.Optional[
            typing.Callable[
                [float], typing.Optional[typing.Tuple[float, float, typing.Any]]
            ]
        ],
    ) -> None:
        """Install (or clear) the data-source lookup for beats beyond the committed spans."""

        self._future = fn

    def invalidate_future(self) -> None:
        """Drop everything not yet sounding — the next clock fire recomputes it.

        Called on every supported intervention: a ``harmony()`` re-call,
        ``form_jump``/``form_next``, a re-bind, a new pin.  ``next_chord``
        is planned and revocable; this is the revocation.
        """

        self._future = None
        self._planned = None

    def span_at(
        self, beat: float
    ) -> typing.Optional[typing.Tuple[float, float, typing.Any]]:
        """The realised ``(start, end, chord)`` covering *beat*, or None if unknown."""

        for start, end, chord in reversed(self._spans):
            if start - 1e-9 <= beat < end - 1e-9:
                return (start, end, chord)

        if self._spans and beat >= self._spans[-1][1] - 1e-9:
            if self._future is not None:
                found = self._future(beat)
                if found is not None:
                    return found

            if (
                self._planned is not None
                and self._planned[0] - 1e-9 <= beat < self._planned[1] - 1e-9
            ):
                return self._planned

        return None

    def chord_at(self, beat: float) -> typing.Optional[typing.Any]:
        """The chord sounding at *beat* — clamping to the last known chord beyond the window."""

        span = self.span_at(beat)

        if span is not None:
            return span[2]

        if not self._spans:
            return None

        if beat < self._spans[0][0]:
            return self._spans[0][2]

        if not self._warned_beyond:
            self._warned_beyond = True
            logger.warning(
                "chord_at(%.2f) is beyond the harmony window — clamping to the last known chord. "
                "In live graph mode only [current, next] is committed; bind a progression for a data future.",
                beat,
            )

        if self._planned is not None and beat >= self._planned[1] - 1e-9:
            return self._planned[2]

        return self._spans[-1][2]

    def boundary_after(self, beat: float) -> typing.Optional[float]:
        """The absolute beat of the next chord boundary after *beat*, when known."""

        span = self.span_at(beat)

        return None if span is None else span[1]

    def next_chord_after(self, beat: float) -> typing.Optional[typing.Any]:
        """The chord that follows the one sounding at *beat* — None when unknown (no clamping)."""

        boundary = self.boundary_after(beat)

        if boundary is None:
            return None

        following = self.span_at(boundary)

        return None if following is None else following[2]

    def latest_chord(self) -> typing.Optional[typing.Any]:
        """The most recently committed chord (compatibility accessor)."""

        return self._spans[-1][2] if self._spans else None


class HarmonyView:
    """Read-only harmony context for one pattern cycle (``p.harmony``).

    Anchored at the cycle's start beat, so all beat arguments are
    cycle-relative — ``chord_at(0)`` is the chord at the cycle's first beat
    (what the two-parameter ``chord`` convention injects), ``chord_at(3.5)``
    the chord sounding under beat 3.5 of this cycle.

    Under bound/frozen progressions the future is data and any beat
    answers; in live graph mode the window is the current chord plus one
    pre-committed step, and ``next_chord`` is *planned and revocable*.
    """

    def __init__(self, horizon: _HarmonyHorizon, origin_beat: float) -> None:
        """Anchor the view at a cycle-start beat."""

        self._horizon = horizon
        self._origin = origin_beat

    @property
    def chord(self) -> typing.Optional[typing.Any]:
        """The chord at this cycle's start (the cycle-start snapshot)."""

        return self._horizon.chord_at(self._origin)

    def chord_at(self, beat: float) -> typing.Optional[typing.Any]:
        """The chord sounding at *beat* of THIS cycle (0-based beats)."""

        return self._horizon.chord_at(self._origin + beat)

    @property
    def next_chord(self) -> typing.Optional[typing.Any]:
        """The chord after the current one — for anticipation and approach tones."""

        return self._horizon.next_chord_after(self._origin)

    def next_chord_at(self, beat: float) -> typing.Optional[typing.Any]:
        """The chord following the one sounding at *beat* of THIS cycle, when known."""

        return self._horizon.next_chord_after(self._origin + beat)

    @property
    def until_change(self) -> typing.Optional[float]:
        """Beats from the cycle start until the next chord boundary, when known."""

        boundary = self._horizon.boundary_after(self._origin)

        return None if boundary is None else boundary - self._origin


def _span_chord(span: subsequence.progressions.ChordSpan) -> typing.Any:
    """The chord a span presents to patterns — decorated where spiced, bare otherwise."""

    if span.is_decorated:
        return subsequence.progressions.DecoratedChord(span)

    return span.chord


def _bare_chord(chord_like: typing.Any) -> typing.Any:
    """The engine-currency chord under a possibly-decorated chord."""

    if isinstance(chord_like, subsequence.progressions.DecoratedChord):
        return chord_like.base

    return chord_like


async def schedule_harmonic_clock(
    sequencer: subsequence.sequencer.Sequencer,
    get_harmonic_state: typing.Callable[
        [], typing.Optional[subsequence.harmonic_state.HarmonicState]
    ],
    horizon: typing.Optional[_HarmonyHorizon] = None,
    bar_beats: float = 4.0,
    cycle_beats: int = 4,
    get_cycle_beats: typing.Optional[typing.Callable[[], int]] = None,
    get_bound_progression: typing.Optional[
        typing.Callable[[], typing.Optional["Progression"]]
    ] = None,
    get_section_progression: typing.Optional[
        typing.Callable[
            [],
            typing.Optional[
                typing.Tuple[str, int, int, typing.Optional["Progression"]]
            ],
        ]
    ] = None,
    get_pinned: typing.Optional[
        typing.Callable[[int], typing.Optional[typing.Any]]
    ] = None,
    cadence_requests: typing.Optional[typing.Dict[int, str]] = None,
    resolve_cadence: typing.Optional[
        typing.Callable[[str], typing.List[subsequence.chords.Chord]]
    ] = None,
    get_section_cadence: typing.Optional[
        typing.Callable[[str], typing.Optional[str]]
    ] = None,
    reschedule_lookahead: float = 1,
) -> None:
    """Schedule the harmonic clock — a span walker over the bound harmony sources.

    Generalises the old fixed-cycle clock: chords last as long as their
    spans say, the clock fires at ``min(next span boundary, next bar
    boundary)`` (so section bookkeeping stays bar-aligned under variable
    harmonic rhythm), and every realised span is published to *horizon*
    (the harmony window patterns read through ``p.harmony``).

    Priority chain per chord boundary: **section progression >
    composition-bound progression > live ``step()``**.  A bound progression
    loops on exhaustion when no live engine is configured (or when it
    contains a :class:`~subsequence.progressions.PitchSet`); with a live
    engine, exhaustion falls through to live stepping — the frozen-replay
    bridge.  In live mode the engine pre-commits one step so the window
    always holds ``[current, next]``.

    ``get_harmonic_state``, ``get_bound_progression``, and ``get_pinned``
    are evaluated on every tick so mid-playback calls to ``harmony()``,
    re-binds, and new pins take effect immediately.  ``get_section_progression``
    returns ``(name, index, bars, Progression|None)`` for the current section
    (``index`` increments on every entry, so verse→verse re-entry resets
    correctly) or ``None`` when no form is active.

    ``cadence_requests`` is the request-hook seam: a mutable ``{bar: name}``
    dict (shared with ``Composition.request_cadence``) the live walk steers
    toward — at the first boundary with a pending request, the remaining
    changes up to its bar are planned as a constrained walk pinned to the
    cadence formula (resolved by ``resolve_cadence``) and then committed
    one boundary at a time.  ``get_section_cadence`` turns a section entry
    into a request arriving at that section's final bar (live sections
    only).  Requests whose bar passes unserved expire with a warning.

    The clock fires ``reschedule_lookahead`` beats before each boundary —
    raised by the caller to the maximum pattern lookahead, so the window
    always covers a pattern's next cycle before it rebuilds.

    ``horizon`` may be omitted for direct use without a :class:`Composition`
    (a private window is created — ``p.harmony`` inside a Composition needs
    the composition's own horizon).  ``get_cycle_beats``, when given, is
    re-read at every boundary so a mid-playback ``harmony(cycle_beats=…)``
    re-call takes effect like the other getter-based parameters; the plain
    ``cycle_beats`` value is the fixed fallback.
    """

    if horizon is None:
        horizon = _HarmonyHorizon()

    def _cycle_beats_now() -> float:
        return float(get_cycle_beats() if get_cycle_beats is not None else cycle_beats)

    pulses_per_beat = sequencer.pulses_per_beat

    state: typing.Dict[str, typing.Any] = {
        "next_change": 0.0,  # absolute beat of the next chord boundary
        "last_section_index": None,
        "section_anchor": 0.0,  # beat the current section entered
        "section_exhausted": False,
        "bound_anchor": 0.0,  # beat the bound progression was first walked from
        "bound_seen": None,  # identity of the bound progression last walked
        "bound_exhausted": False,
        "planned": None,  # the live engine's pre-committed next chord
        "cadence_queue": [],  # planned approach chords (None = step live at that boundary)
    }

    def _plan_cadence_request(
        beat: float, hs: subsequence.harmonic_state.HarmonicState
    ) -> None:
        """Compile the nearest pending cadence request into the approach queue.

        A live freeze-ahead: a constrained walk from the engine's current
        chord to the request's bar, pinned to the cadence formula at the
        tail, drawn through the engine's real weights on the play stream.
        The engine's state is snapshot-restored — chords commit one by one
        as their boundaries actually sound.  An unwalkable formula falls
        back to fiat (live steps up to the approach, the formula committed
        at its bars), loudly.
        """

        if not cadence_requests or resolve_cadence is None:
            return

        cb = _cycle_beats_now()
        target_bar = min(cadence_requests)
        target_beat = (target_bar - 1) * bar_beats

        if target_beat < beat - 1e-9:
            return  # stale; the expiry pass warns and drops it

        name = cadence_requests.pop(target_bar)

        try:
            formula = resolve_cadence(name)
        except (ValueError, TypeError) as error:
            logger.warning(
                f"cadence request {name!r} at bar {target_bar} cannot resolve: {error}"
            )
            return

        remaining = (target_beat - beat) / cb
        steps = (
            int(remaining + 1e-9) + 1
        )  # chord changes from here to the arrival, inclusive

        if abs(remaining - round(remaining)) > 1e-9:
            logger.warning(
                f"cadence request {name!r}: bar {target_bar} does not land on a chord "
                f"boundary ({cb:g}-beat cycles) — the arrival sounds at the boundary before it"
            )

        tail = list(formula[-steps:])

        if steps < len(formula):
            logger.warning(
                f"cadence request {name!r} at bar {target_bar}: only {steps} chord change(s) "
                f"before the arrival — approaching with the formula's tail alone"
            )

        length = steps + 1  # walk position 1 is the chord sounding now
        pins = {
            length - len(tail) + 1 + index: chord for index, chord in enumerate(tail)
        }

        saved_history = list(hs.history)
        saved_current = hs.current_chord

        def _commit(chosen: subsequence.chords.Chord) -> None:
            hs.current_chord = chosen

        try:
            walked = subsequence.sequence_utils.constrained_walk(
                hs.graph,
                hs.current_chord,
                length,
                rng=hs.rng,
                pins=pins,
                weight_modifier=hs._transition_weight,
                before_choice=hs._record_transition_source,
                after_choice=_commit,
            )
        except ValueError as error:
            logger.warning(
                f"cadence request {name!r} at bar {target_bar} is not walkable from "
                f"{saved_current.name()} ({error}) — the arrival lands by fiat"
            )
            state["cadence_queue"] = [None] * (steps - len(tail)) + tail
            return
        finally:
            hs.history = saved_history
            hs.current_chord = saved_current

        state["cadence_queue"] = list(walked[1:])

    def _data_future(
        progression: "Progression",
        anchor: float,
        loops: bool,
    ) -> typing.Callable[
        [float], typing.Optional[typing.Tuple[float, float, typing.Any]]
    ]:
        """A horizon future fn computing spans arithmetically from a data source."""

        def future(
            beat: float,
        ) -> typing.Optional[typing.Tuple[float, float, typing.Any]]:
            offset = beat - anchor

            if offset < -1e-9:
                return None

            if not loops and offset >= progression.length - 1e-9:
                return None

            span, span_start, span_end = progression.span_at(offset)
            cycle_base = anchor + (offset // progression.length) * progression.length
            start = cycle_base + span_start
            end = cycle_base + span_end

            chord = _span_chord(span)

            if get_pinned is not None:
                pinned = get_pinned(int(start // bar_beats) + 1)
                if pinned is not None:
                    chord = pinned

            return (start, end, chord)

        return future

    def advance(beat: float) -> typing.Optional[float]:
        """Prepare the boundary at *beat*; return beats to the next fire (or None to stop)."""

        hs = get_harmonic_state()
        initial = beat == 0.0 and horizon.is_empty

        # --- Section bookkeeping (every fire is bar-aligned or a span boundary,
        # and the form clock fired first at this pulse, so the info is current).
        section_progression: typing.Optional["Progression"] = None

        if get_section_progression is not None:
            info = get_section_progression()
            if info is not None:
                _section_name, section_index, section_bars, section_progression = info

                if section_index != state["last_section_index"]:
                    state["last_section_index"] = section_index
                    state["section_anchor"] = beat
                    state["section_exhausted"] = False
                    state["next_change"] = (
                        beat  # a section entry forces a chord decision
                    )
                    horizon.invalidate_future()
                    state["planned"] = None

                    # Restore the NIR context that was current when this
                    # progression was frozen, so every replay starts alike.
                    if (
                        section_progression is not None
                        and section_progression.trailing_history
                        and hs is not None
                    ):
                        hs.history = list(section_progression.trailing_history)

                    # A registered section cadence becomes a bar request: the
                    # arrival lands on this section's final bar.  Live sections
                    # only — bound chords are data and cannot be steered.
                    if (
                        get_section_cadence is not None
                        and cadence_requests is not None
                        and section_progression is None
                        and section_bars > 0
                    ):
                        section_cadence_name = get_section_cadence(_section_name)
                        if section_cadence_name is not None:
                            entry_bar = int(beat // bar_beats) + 1
                            cadence_requests.setdefault(
                                entry_bar + section_bars - 1, section_cadence_name
                            )

        # Cadence requests expire when their bar passes unserved — harmony was
        # data-bound the whole approach, or the request arrived too late.
        if cadence_requests:
            for expired_bar in [
                b for b in cadence_requests if (b - 1) * bar_beats < beat - 1e-9
            ]:
                expired_name = cadence_requests.pop(expired_bar)
                logger.warning(
                    f"cadence request {expired_name!r} at bar {expired_bar} expired unserved — "
                    "the bar passed while harmony was data-bound, or the request arrived too late"
                )

        bound_progression = (
            get_bound_progression() if get_bound_progression is not None else None
        )

        if (
            bound_progression is not None
            and state["bound_seen"] is not bound_progression
        ):
            # First sighting (or a re-bind): anchor the walk here and forget exhaustion.
            state["bound_seen"] = bound_progression
            state["bound_anchor"] = beat
            state["bound_exhausted"] = False
            horizon.invalidate_future()

        chord_boundary = beat >= state["next_change"] - 1e-9

        if not chord_boundary and get_pinned is not None:
            # Fiat inside a longer span: a pinned bar forces its chord at the
            # bar line, overriding the sounding span until the next change.
            pinned_now = get_pinned(int(beat // bar_beats) + 1)

            if pinned_now is not None and horizon.chord_at(beat) is not pinned_now:
                bare_pin = _bare_chord(pinned_now)

                if hs is not None and isinstance(bare_pin, subsequence.chords.Chord):
                    hs.commit_chord(bare_pin)

                horizon.commit(beat, state["next_change"], pinned_now)

        if chord_boundary:
            chord_like: typing.Optional[typing.Any] = None
            span_beats: typing.Optional[float] = None
            from_live = False

            # Priority 1: the current section's progression.
            if section_progression is not None and not state["section_exhausted"]:
                offset = beat - state["section_anchor"]
                loops = hs is None or section_progression.loops_on_exhaustion

                if offset >= section_progression.length - 1e-9 and not loops:
                    state["section_exhausted"] = True  # fall through to live stepping
                else:
                    span, span_start, span_end = section_progression.span_at(offset)
                    chord_like = _span_chord(span)
                    span_beats = span_end - (offset % section_progression.length)
                    horizon.set_future(
                        _data_future(
                            section_progression, state["section_anchor"], loops
                        )
                    )

            # Priority 2: the composition-bound progression.
            if (
                chord_like is None
                and bound_progression is not None
                and not state["bound_exhausted"]
            ):
                offset = beat - state["bound_anchor"]
                loops = hs is None or bound_progression.loops_on_exhaustion

                if offset >= bound_progression.length - 1e-9 and not loops:
                    state["bound_exhausted"] = (
                        True  # the frozen-replay bridge: live from here
                    )
                else:
                    span, span_start, span_end = bound_progression.span_at(offset)
                    chord_like = _span_chord(span)
                    span_beats = span_end - (offset % bound_progression.length)
                    horizon.set_future(
                        _data_future(bound_progression, state["bound_anchor"], loops)
                    )

            # Priority 3: live graph stepping.
            if chord_like is None:
                if hs is None:
                    return None  # nothing left to drive the clock

                if initial:
                    chord_like = (
                        hs.current_chord
                    )  # the tonic sounds first; no step at beat 0
                else:
                    if not state["cadence_queue"]:
                        _plan_cadence_request(beat, hs)

                    queued: typing.Optional[typing.Any] = None

                    if state["cadence_queue"]:
                        queued = state["cadence_queue"].pop(0)

                    if queued is not None:
                        # A planned approach supersedes the pre-committed step.
                        state["planned"] = None
                        chord_like = queued
                    else:
                        if state["planned"] is None:
                            state["planned"] = hs.plan_next()
                        chord_like = state["planned"]
                        state["planned"] = None

                span_beats = _cycle_beats_now()
                from_live = True
                horizon.set_future(None)

            # Pins are fiat — they override whatever the source produced.
            if get_pinned is not None:
                pinned = get_pinned(int(beat // bar_beats) + 1)
                if pinned is not None:
                    chord_like = pinned

            assert (
                span_beats is not None
            )  # every branch above either set it or returned

            # Sync the engine so freeze()/NIR/live fall-through stay coherent.
            bare = _bare_chord(chord_like)

            if hs is not None and isinstance(bare, subsequence.chords.Chord):
                if initial:
                    hs.current_chord = bare
                elif from_live or bare is not hs.current_chord:
                    hs.commit_chord(bare)

            horizon.commit(beat, beat + span_beats, chord_like)
            state["next_change"] = beat + span_beats

            # Live mode pre-commits one step so the window holds [current, next].
            # A planned cadence approach already knows its next chord — publish
            # it without drawing (a fiat gap, queue head None, plans normally).
            if from_live and hs is not None:
                if state["cadence_queue"] and state["cadence_queue"][0] is not None:
                    horizon.set_planned(
                        state["next_change"],
                        state["next_change"] + _cycle_beats_now(),
                        state["cadence_queue"][0],
                    )
                else:
                    state["planned"] = hs.plan_next()
                    horizon.set_planned(
                        state["next_change"],
                        state["next_change"] + _cycle_beats_now(),
                        state["planned"],
                    )

        # Fire again at the earlier of the next chord change and the next bar
        # line — bar fires keep section bookkeeping aligned under long spans.
        next_bar = (beat // bar_beats) * bar_beats + bar_beats
        if next_bar <= beat + 1e-9:
            next_bar = beat + bar_beats

        next_fire = min(float(state["next_change"]), next_bar)

        return max(next_fire - beat, 1.0 / pulses_per_beat)

    def advance_pulse(boundary_pulse: int) -> typing.Optional[float]:
        """The sequencer-facing callback: pulses in, beats out."""

        return advance(boundary_pulse / pulses_per_beat)

    # Populate the window for beat 0 synchronously, BEFORE patterns first
    # build, then schedule the walker from the first boundary it reported.
    first_interval = advance(0.0)

    if first_interval is None:
        return

    await sequencer.schedule_callback_sequence(
        callback=advance_pulse,
        start_pulse=int(first_interval * pulses_per_beat),
        reschedule_lookahead=reschedule_lookahead,
    )


def _make_safe_callback(
    fn: typing.Callable, accepts_context: bool = False, start_cycle: int = 0
) -> typing.Callable[[int], None]:
    """Wrap a user function as a fire-and-forget callback that never blocks the clock.

    If *accepts_context* is True, ``fn`` is called with a :class:`ScheduleContext`
    whose ``cycle`` field increments on every invocation.
    """

    is_async = inspect.iscoroutinefunction(fn)
    cycle_count: typing.List[int] = [
        start_cycle
    ]  # mutable cell so the closure can mutate it

    async def _execute(cycle: int) -> None:
        """Run the user function with error handling and optional threading."""

        ctx = ScheduleContext(cycle=cycle)

        try:
            if is_async:
                await (fn(ctx) if accepts_context else fn())

            else:
                loop = asyncio.get_running_loop()
                call = (lambda: fn(ctx)) if accepts_context else fn
                await loop.run_in_executor(None, call)

        except Exception as exc:
            logger.warning(
                f"Scheduled task {getattr(fn, '__name__', repr(fn))!r} failed: {exc}"
            )

    def wrapper(pulse: int) -> None:
        """Spawn the task in the background without blocking the sequencer."""

        # Capture the cycle number synchronously before any async yield so that
        # even if multiple pulses fire before the event loop runs, each task
        # receives the correct cycle value it was triggered at.
        current_cycle = cycle_count[0]
        cycle_count[0] += 1
        asyncio.create_task(_execute(current_cycle))

    return wrapper


async def schedule_task(
    sequencer: subsequence.sequencer.Sequencer,
    fn: typing.Callable,
    cycle_beats: int,
    reschedule_lookahead: int = 1,
    defer: bool = False,
) -> None:
    """Schedule a non-blocking repeating task on the sequencer's beat clock.

    If ``fn`` declares a first parameter named ``p``, it is called with a
    :class:`ScheduleContext` on every invocation (same behaviour as
    ``composition.schedule()``).

    When *defer* is True the backshift fire at pulse 0 is skipped; the first
    call happens one full *cycle_beats* later.  Direct API users who need the
    equivalent of ``initial=True`` can simply ``await fn()`` themselves before
    calling this function.
    """

    accepts_ctx = _fn_has_parameter(fn, "p")
    wrapped = _make_safe_callback(fn, accepts_context=accepts_ctx)
    start_pulse = int(cycle_beats * sequencer.pulses_per_beat) if defer else 0

    await sequencer.schedule_callback_repeating(
        callback=wrapped,
        interval_beats=cycle_beats,
        start_pulse=start_pulse,
        reschedule_lookahead=reschedule_lookahead,
    )


async def schedule_form(
    sequencer: subsequence.sequencer.Sequencer,
    form_state: subsequence.form_state.FormState,
    reschedule_lookahead: float = 1,
    on_bar: typing.Optional[typing.Callable[[int, bool], None]] = None,
    get_form_state: typing.Optional[
        typing.Callable[[], typing.Optional[subsequence.form_state.FormState]]
    ] = None,
) -> None:
    """Schedule the form state to advance each bar.

    Emits a ``"section"`` event on the sequencer's emitter at play start
    and on every section change (one lookahead-beat early, like every form
    decision), carrying the new :class:`~subsequence.form_state.SectionInfo`
    (``None`` when the form finishes).  ``on_bar`` is the boundary hook —
    called once per bar with ``(boundary_pulse, section_changed)`` after the
    form advances; the transition machinery rides it.

    ``get_form_state``, when given, is re-read every bar — so a mid-playback
    ``form()`` re-bind advances the NEW form state from the next bar instead
    of silently driving the abandoned object forever.  ``form_state`` is the
    fixed fallback for direct use.
    """

    lookahead_pulses = int(reschedule_lookahead * sequencer.pulses_per_beat)

    def _current_form_state() -> typing.Optional[subsequence.form_state.FormState]:
        return get_form_state() if get_form_state is not None else form_state

    # Log and announce the initial section.
    initial_form = _current_form_state()
    initial_section = (
        initial_form.get_section_info() if initial_form is not None else None
    )
    if initial_section:
        logger.info(f"Form: {initial_section.name}")
    sequencer.events.emit_sync("section", initial_section)

    if on_bar is not None:
        on_bar(0, True)  # the first bar is a boundary too (a 1-bar opener can end)

    def advance_form(pulse: int) -> None:
        """Advance the form by one bar, logging and announcing section changes."""

        fs = _current_form_state()

        if fs is None:
            if on_bar is not None:
                on_bar(pulse + lookahead_pulses, False)
            return

        section_changed = fs.advance()

        if section_changed:
            section = fs.get_section_info()
            if section:
                logger.info(f"Form: {section.name}")
            else:
                logger.info("Form: finished")
            sequencer.events.emit_sync("section", section)

        if on_bar is not None:
            # Fixed callbacks fire lookahead-early; the bar line itself is
            # lookahead pulses ahead of the fire pulse.
            on_bar(pulse + lookahead_pulses, section_changed)

    # Form advances once per bar based on the global time signature.
    _BEATS_PER_BAR: int = sequencer.time_signature[0]
    first_bar_pulse = int(_BEATS_PER_BAR * sequencer.pulses_per_beat)

    await sequencer.schedule_callback_repeating(
        callback=advance_form,
        interval_beats=_BEATS_PER_BAR,
        start_pulse=first_bar_pulse,
        reschedule_lookahead=reschedule_lookahead,
    )


async def schedule_patterns(
    sequencer: subsequence.sequencer.Sequencer,
    patterns: typing.Iterable[subsequence.pattern.Pattern],
    start_pulse: int = 0,
) -> None:
    """
    Schedule a collection of repeating patterns from a shared start pulse.
    """

    for pattern in patterns:
        await sequencer.schedule_pattern_repeating(pattern, start_pulse=start_pulse)


async def run_until_stopped(sequencer: subsequence.sequencer.Sequencer) -> None:
    """
    Run the sequencer until a stop signal is received.
    """

    logger.info("Playing sequence. Press Ctrl+C to stop.")

    await sequencer.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        """
        Signal handler to request a clean shutdown.
        """

        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows: add_signal_handler is Unix-only.
            # Fall back to signal.signal() for SIGINT (Ctrl+C); skip SIGTERM.
            if sig == signal.SIGINT:
                signal.signal(sig, lambda s, f: _request_stop())

    assert sequencer.task is not None, "Sequencer task should exist after start()"
    await asyncio.wait(
        [asyncio.create_task(stop_event.wait()), sequencer.task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    await sequencer.stop()


@dataclasses.dataclass
class _Transition:
    """One declarative boundary rule registered by ``Composition.transition()``.

    Attributes:
            before: The incoming section name the rule fires before, or ``"*"``
                    for any *different* section.
            fill: A Motif (anything with ``.events``/``.length``) to play in the
                    final bar.
            channel: Resolved 0-indexed channel for the fill.
            beat: Beat offset of the fill within the final bar.
            mute: Pattern names to mute over the boundary approach.
            beats: Mute window in beats (rounded UP to whole bars — muting is
                    bar-granular).
            drum_note_map: Explicit drum map for the fill (otherwise borrowed
                    from a registered pattern on the same channel).
            device: Output device (index, name, or None) for the fill — kept raw and
                    resolved when the fill fires, since device names are not known until
                    play() opens the ports.
    """

    before: str
    fill: typing.Optional[typing.Any] = None
    channel: typing.Optional[int] = None
    beat: float = 0.0
    mute: typing.Optional[typing.List[str]] = None
    beats: typing.Optional[float] = None
    drum_note_map: typing.Optional[typing.Dict[str, int]] = None
    device: subsequence.midi_utils.DeviceId = None


class _PendingPattern:
    """
    Holds decorator arguments and builder function until play() is called.
    """

    def __init__(
        self,
        builder_fn: typing.Callable,
        channel: int,
        length: float,
        default_grid: int,
        drum_note_map: typing.Optional[typing.Dict[str, int]],
        cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
        nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
        reschedule_lookahead: float = 1,
        voice_leading: bool = False,
        device: int = 0,
        raw_device: subsequence.midi_utils.DeviceId = None,
        mirrors: typing.Optional[
            typing.Iterable[subsequence.pattern.MirrorSpec]
        ] = None,
        min_energy: typing.Optional[float] = None,
    ) -> None:
        """
        Store pattern registration details for deferred scheduling.

        *raw_device* holds the original ``DeviceId`` passed to ``pattern()``
        (``None``, ``int``, or ``str``).  When it is a string, ``device``
        starts at 0 as a placeholder and ``_resolve_pending_devices()`` in
        ``_run()`` replaces it with the correct integer index once all output
        devices have been opened.  When it is ``None`` or an ``int``, ``device``
        is already final and ``raw_device`` is not consulted again.

        *mirrors* is the list of additional ``(device_idx, channel_0_indexed)``
        destinations resolved at decoration time.  Empty list = no mirroring.
        """

        self.builder_fn = builder_fn
        self.channel = channel
        self.length = length
        self.default_grid = default_grid
        self.drum_note_map = drum_note_map
        self.cc_name_map = cc_name_map
        self.nrpn_name_map = nrpn_name_map
        self.reschedule_lookahead = reschedule_lookahead
        self.voice_leading = voice_leading
        self.device = device
        self.raw_device: subsequence.midi_utils.DeviceId = raw_device
        self.mirrors: typing.List[subsequence.pattern.MirrorSpec] = (
            list(mirrors) if mirrors else []
        )
        self.min_energy = min_energy


class _PendingScheduled:
    """Holds a user function and cycle interval for deferred scheduling."""

    def __init__(
        self,
        fn: typing.Callable,
        cycle_beats: int,
        reschedule_lookahead: int,
        wait_for_initial: bool = False,
        defer: bool = False,
    ) -> None:
        """Store the function and scheduling parameters."""

        self.fn = fn
        self.cycle_beats = cycle_beats
        self.reschedule_lookahead = reschedule_lookahead
        self.wait_for_initial = wait_for_initial
        self.defer = defer


def _live_blocked(name: str) -> typing.Callable:
    """Return a function that raises ``RuntimeError`` when called.

    Substituted for built-ins that would block the async event loop
    (``help``, ``input``, ``breakpoint``, ``exit``, ``quit``).  Used by
    ``Composition._build_live_namespace`` to populate the safe builtins
    dict for both the file watcher and the TCP eval server.
    """

    def _raise(*args: typing.Any, **kwargs: typing.Any) -> None:
        raise RuntimeError(
            f"{name}() is not available in live mode - it would block the sequencer."
        )

    _raise.__name__ = name
    _raise.__qualname__ = name

    return _raise


class Composition:
    """
    The top-level controller for a musical piece.

    The ``Composition`` object manages the global clock (Sequencer), the harmonic
    progression (HarmonicState), the song structure (subsequence.form_state.FormState), and all MIDI patterns.
    It serves as the main entry point for defining your music.

    Typical workflow:

    1. Initialize ``Composition`` with BPM and Key.
    2. Define harmony and form (optional).
    3. Register patterns using the ``@composition.pattern`` decorator.
    4. Call ``composition.play()`` to start the music.
    """

    def __init__(
        self,
        output_device: typing.Optional[str] = None,
        bpm: float = 120,
        time_signature: typing.Tuple[int, int] = (4, 4),
        key: typing.Optional[str] = None,
        scale: typing.Optional[str] = None,
        seed: typing.Optional[int] = None,
        record: bool = False,
        record_filename: typing.Optional[str] = None,
        zero_indexed_channels: bool = False,
        latency_ms: float = 0.0,
    ) -> None:
        """
        Initialize a new composition.

        Parameters:
                output_device: The exact name of the MIDI output port to use,
                        as reported by ``mido.get_output_names()``. Matching is
                        strict — the string must equal an entry in that list
                        verbatim. On Linux/ALSA, names include the client and
                        port IDs (e.g.
                        ``"Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"``); the
                        trailing ``:client:port`` digits are assigned in
                        connection order and can change between reboots or when
                        a virtual port is recreated. To look up the current
                        names::

                            import mido
                            for n in mido.get_output_names(): print(n)

                        If ``None``, Subsequence auto-discovers — uses the only
                        available device, or prompts to choose if several exist.
                bpm: Initial tempo in beats per minute (default 120).
                time_signature: The metre as ``(beats, unit)``, default ``(4, 4)``.
                        Sets the bar length everywhere bars matter: ``bars=`` pattern
                        lengths, ``p.bar``/``p.signal()``, form advancement and
                        transitions, and pinned-chord bar numbers.
                key: The root key of the piece (e.g., "C", "F#", "Bb").
                        Required if you plan to use ``harmony()``.
                scale: The scale/mode of the piece (e.g. "minor", "dorian",
                        or any registered scale name).  Used to resolve scale
                        degrees in motifs; defaults to major (ionian) when unset.
                seed: An optional integer for deterministic randomness. When set,
                        every random decision (chord choices, drum probability, etc.)
                        will be identical on every run.
                record: When True, record all MIDI events to a file.
                record_filename: Optional filename for the recording (defaults to timestamp).
                zero_indexed_channels: When False (default), MIDI channels use
                        1-based numbering (1-16) matching instrument labelling.
                        Channel 10 is drums, the way musicians and hardware panels
                        show it. When True, channels use 0-based numbering (0-15)
                        matching the raw MIDI protocol.
                latency_ms: Physical output latency of the primary device in
                        milliseconds, for delay compensation (default 0.0, must be
                        non-negative). Set this when the primary output sounds late
                        (e.g. a software sampler) so Subsequence delays faster
                        devices to line everything up. See ``midi_output()`` for
                        additional devices.

        Example:
                ```python
                comp = subsequence.Composition(bpm=128, key="Eb", seed=123)
                ```
        """

        if latency_ms < 0:
            raise ValueError(f"latency_ms must be non-negative — got {latency_ms}")

        self.output_device = output_device
        self.bpm = bpm
        self.time_signature = time_signature
        self.key = key
        self.scale = scale
        self._seed: typing.Optional[int] = seed
        self._zero_indexed_channels: bool = zero_indexed_channels
        self._output_latency_ms: float = latency_ms

        # Determinism plumbing: named-stream derivation state.  Build-time
        # consumers draw per-call-salted streams (freeze:1, harmony:2, ...) so
        # adding one call never shifts another's stream; play-time pattern
        # streams are name-keyed in _build_pattern_from_pending.
        self._freeze_count: int = 0
        self._harmony_count: int = 0
        self._form_count: int = 0
        self._reroll_nonces: typing.Dict[str, int] = {}
        self._locked_names: typing.Set[str] = set()

        self._sequencer = subsequence.sequencer.Sequencer(
            output_device_name=output_device,
            initial_bpm=bpm,
            time_signature=time_signature,
            record=record,
            record_filename=record_filename,
        )

        self._harmonic_state: typing.Optional[
            subsequence.harmonic_state.HarmonicState
        ] = None
        self._harmony_cycle_beats: typing.Optional[int] = None
        self._harmony_style: typing.Optional[str] = None
        # The style (name or ChordGraph) from the most recent style-configuring
        # harmony() call — reused by parameter-only re-calls.
        self._last_harmony_style: typing.Optional[
            typing.Union[str, subsequence.chord_graphs.ChordGraph]
        ] = None
        self._harmony_reschedule_lookahead: float = 1
        self._section_progressions: typing.Dict[str, Progression] = {}
        self._bound_progression: typing.Optional[Progression] = None
        self._pinned_chords: typing.Dict[int, typing.Any] = {}
        self._cadence_requests: typing.Dict[int, str] = {}
        self._section_cadences: typing.Dict[str, str] = {}
        self._harmony_horizon = _HarmonyHorizon()
        # True once the span-walking clock is registered for this playback —
        # lets a first mid-playback harmony() call start it exactly once.
        self._harmonic_clock_started: bool = False
        self._section_motifs: typing.Dict[
            typing.Tuple[str, typing.Optional[str]], typing.Any
        ] = {}
        self._energy_map: typing.Dict[
            str, typing.Union[float, typing.Tuple[float, float]]
        ] = {}
        self._form_has_payload: bool = False
        self._form_key: typing.Optional[str] = None
        self._form_scale: typing.Optional[str] = None
        # Cache of section progressions resolved against an effective key/scale
        # (key-relative section harmony re-keys per occurrence; resolution is a
        # pure function of (content, key, scale), so this is just memoisation).
        self._resolved_section_cache: typing.Dict[
            typing.Tuple[str, typing.Optional[str], typing.Optional[str]], Progression
        ] = {}
        self._transitions: typing.List[_Transition] = []
        self._transition_muted: typing.Set[str] = set()
        self._pending_patterns: typing.List[_PendingPattern] = []
        # Names of patterns declared by the most recent live-reload exec (added by
        # pattern()/layer() as they run); the deletion diff in _apply_source_async
        # compares this against the same source's PREVIOUS exec.
        self._declared_names: typing.Set[str] = set()
        # Per-source declaration history: source label/path → the names it
        # declared last time it was exec'd.  The deletion diff unregisters only
        # names a source used to declare and no longer does — never patterns
        # registered by the wrapper script or by another watched source.
        self._source_declared: typing.Dict[str, typing.Set[str]] = {}
        self._pending_scheduled: typing.List[_PendingScheduled] = []
        self._form_state: typing.Optional[subsequence.form_state.FormState] = None
        self._builder_bar: int = 0
        self._display: typing.Optional[subsequence.display.Display] = None
        self._live_server: typing.Optional[subsequence.live_server.LiveServer] = None
        self._live_reloader: typing.Optional[subsequence.live_reloader.LiveReloader] = (
            None
        )
        self._is_live: bool = False
        self._running_patterns: typing.Dict[str, typing.Any] = {}
        self._input_device: typing.Optional[str] = None
        self._input_device_alias: typing.Optional[str] = None
        self._clock_follow: bool = False
        self._clock_output: bool = False
        self._cc_mappings: typing.List[typing.Dict[str, typing.Any]] = []
        self._cc_forwards: typing.List[typing.Dict[str, typing.Any]] = []
        # Held-note input config from note_input() (None = not declared).
        self._note_input: typing.Optional[typing.Dict[str, typing.Any]] = None
        # Additional output devices registered with midi_output() after construction.
        self._additional_outputs: typing.List[_AdditionalOutput] = []
        # Additional input devices: (device_name: str, alias: Optional[str], clock_follow: bool)
        self._additional_inputs: typing.List[
            typing.Tuple[str, typing.Optional[str], bool]
        ] = []
        # Maps alias/name → output device index (populated in _run after all devices are opened).
        self._output_device_names: typing.Dict[str, int] = {}
        # Maps alias/name → input device index (populated in _run after all input devices are opened).
        self._input_device_names: typing.Dict[str, int] = {}
        self.data: typing.Dict[str, typing.Any] = {}
        self._osc_server: typing.Optional[subsequence.osc.OscServer] = None
        self.conductor = subsequence.conductor.Conductor()
        self._web_ui_enabled: bool = False
        self._web_ui_http_host: str = "127.0.0.1"
        self._web_ui_ws_host: str = "127.0.0.1"
        self._web_ui_server: typing.Optional[subsequence.web_ui.WebUI] = None
        self._link_quantum: typing.Optional[float] = None

        # Hotkey state — populated by hotkeys() and hotkey().
        self._hotkeys_enabled: bool = False
        self._hotkey_bindings: typing.Dict[str, HotkeyBinding] = {}
        self._pending_hotkey_actions: typing.List[_PendingHotkeyAction] = []
        self._keystroke_listener: typing.Optional[
            subsequence.keystroke.KeystrokeListener
        ] = None

        # Tuning state — populated by tuning().
        self._tuning: typing.Optional[typing.Any] = None  # subsequence.tuning.Tuning
        self._tuning_bend_range: float = 2.0
        self._tuning_channels: typing.Optional[typing.List[int]] = None
        self._tuning_reference_note: int = 60
        self._tuning_exclude_drums: bool = True

    def _resolve_device_id(self, device: subsequence.midi_utils.DeviceId) -> int:
        """Resolve an output device id (None/int/str) to an integer index.

        ``None`` → 0 (primary device).  ``int`` → returned as-is.
        ``str`` → looked up in ``_output_device_names``; logs a warning and
        returns 0 if the name is unknown (called after all devices are opened
        in ``_run()``).
        """
        if device is None:
            return 0
        if isinstance(device, int):
            return device
        idx = self._output_device_names.get(device)
        if idx is None:
            logger.warning(
                f"Unknown output device name '{device}' — routing to device 0. "
                f"Available names: {list(self._output_device_names.keys())}"
            )
            return 0
        return idx

    def _resolve_input_device_id(
        self, device: subsequence.midi_utils.DeviceId
    ) -> typing.Optional[int]:
        """Resolve an input device id (None/int/str) to an integer index.

        ``None`` → ``None`` (matches any input device — existing behaviour).
        ``int`` → returned as-is.  ``str`` → looked up in ``_input_device_names``;
        logs a warning and returns ``-1`` if the name is unknown — an index no
        real device carries, so the mapping matches NOTHING (returning None
        here would silently fail OPEN and listen to every device).
        Called after all input devices are opened in ``_run()``.
        """
        if device is None:
            return None
        if isinstance(device, int):
            return device
        idx = self._input_device_names.get(device)
        if idx is None:
            logger.warning(
                f"Unknown input device name '{device}' — mapping will be ignored. "
                f"Available names: {list(self._input_device_names.keys())}"
            )
            return -1
        return idx

    def _resolve_pending_devices(self) -> None:
        """Resolve name-based device ids on pending patterns now that all output devices are open."""
        for pending in self._pending_patterns:
            if isinstance(pending.raw_device, str):
                pending.device = self._resolve_device_id(pending.raw_device)

    async def _activate_new_pending_patterns(self) -> None:
        """Build and schedule any pending patterns whose names are not yet running.

        Used by ``LiveReloader._reload_async`` to bring NEW patterns added
        in a live reload into rotation mid-flight.  Existing patterns
        hot-swap via the decorator (their ``_builder_fn`` is replaced in
        place); only patterns whose names are not yet in ``_running_patterns``
        need this graduation step.

        Newly-scheduled patterns start at the current sequencer pulse —
        they'll generate events from now onward, and the next reschedule
        will fire at the same offset as their primary cycle.
        """

        # Resolve any deferred string-device names against the now-open
        # device registry (no-op for int/None devices).
        self._resolve_pending_devices()

        # Dedupe by name, last declaration wins — re-declaring a pattern in a
        # reloaded source must not schedule two copies.
        new_by_name: typing.Dict[str, _PendingPattern] = {}

        for pending in self._pending_patterns:
            if pending.builder_fn.__name__ not in self._running_patterns:
                new_by_name[pending.builder_fn.__name__] = pending

        new_pending = list(new_by_name.values())

        if not new_pending:
            return

        current_pulse = self._sequencer.pulse_count

        for pending in new_pending:
            pattern = self._build_pattern_from_pending(
                pending, start_pulse=current_pulse
            )
            await self._sequencer.schedule_pattern_repeating(
                pattern, start_pulse=current_pulse
            )
            self._running_patterns[pending.builder_fn.__name__] = pattern

            logger.info(
                f"Live-reload: scheduled new pattern '{pending.builder_fn.__name__}'"
            )

        # Prune graduated (and stale duplicate) declarations: leaving them in
        # _pending_patterns resurrected deleted patterns on every later reload.
        self._pending_patterns = [
            pending
            for pending in self._pending_patterns
            if pending.builder_fn.__name__ not in self._running_patterns
        ]

    def _resolve_channel(self, channel: int) -> int:
        """
        Convert a user-supplied MIDI channel to the 0-indexed value used internally.

        When ``zero_indexed_channels`` is False (default), the channel is
        validated as 1-16 and decremented by one. When True (0-indexed), the
        channel is validated as 0-15 and returned unchanged.
        """

        if self._zero_indexed_channels:
            if not 0 <= channel <= 15:
                raise ValueError(
                    f"MIDI channel must be 0-15 (zero_indexed_channels=True), got {channel}"
                )
            return channel
        else:
            if not 1 <= channel <= 16:
                raise ValueError(f"MIDI channel must be 1-16, got {channel}")
            return channel - 1

    def _resolve_mirrors(
        self,
        mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]],
        primary: typing.Optional[typing.Tuple[int, int]] = None,
    ) -> typing.List[subsequence.pattern.MirrorSpec]:
        """
        Validate and normalise a list of mirror destinations.

        Each entry is a 2- or 3-element sequence — ``(device_idx, channel)`` or
        ``(device_idx, channel, drum_note_map)`` — as a tuple, list, or any such
        iterable.  ``channel`` is expressed in the user's channel-numbering
        convention (1-16 by default, 0-15 when ``zero_indexed_channels=True``);
        this method converts it to canonical 0-indexed form and rejects
        malformed entries.  The optional ``drum_note_map`` is preserved verbatim
        so the sequencer can re-resolve mirrored drum names per device.

        String device names are NOT supported here; users wanting a named
        device should pass the integer index returned from ``midi_output()``.

        If ``primary=(device, channel)`` is supplied (canonical 0-indexed
        form), a mirror entry whose ``(device, channel)`` matches it triggers a
        ``logger.warning`` — this is almost always a user error (every event
        would double-fire on the same destination).  The optional map is ignored
        for this comparison.  Skipped when ``primary`` is ``None``, since the
        runtime API call site supplies its own check.
        """

        if mirrors is None:
            return []

        resolved: typing.List[subsequence.pattern.MirrorSpec] = []

        for entry in mirrors:
            # Accept any 2- or 3-element iterable (tuple, list, etc.) — config
            # files and JSON sources naturally produce lists.  Validate shape at
            # decoration time so bad inputs surface here instead of producing
            # inscrutable failures inside the sequencer.
            try:
                items = list(entry)
            except TypeError:
                raise ValueError(
                    f"Mirror entry must be a (device, channel[, drum_note_map]) tuple — got {entry!r}"
                )

            if len(items) not in (2, 3):
                raise ValueError(
                    f"Mirror entry must have 2 or 3 elements (device, channel[, drum_note_map]) — got {entry!r}"
                )

            device = items[0]
            channel = items[1]
            drum_map = items[2] if len(items) == 3 else None

            if not isinstance(device, int) or isinstance(device, bool):
                raise ValueError(
                    f"Mirror device must be an integer index — got {type(device).__name__} ({device!r})"
                )

            if not isinstance(channel, int) or isinstance(channel, bool):
                raise ValueError(
                    f"Mirror channel must be an integer — got {type(channel).__name__} ({channel!r})"
                )

            if drum_map is not None and not isinstance(drum_map, dict):
                raise ValueError(
                    f"Mirror drum_note_map must be a dict or None — got {type(drum_map).__name__} ({drum_map!r})"
                )

            resolved_channel = self._resolve_channel(channel)

            if primary is not None and (device, resolved_channel) == primary:
                logger.warning(
                    f"Mirror destination {(device, resolved_channel)} matches the pattern's primary destination "
                    f"— every event will double-fire on this (device, channel).  This is almost "
                    f"certainly unintended."
                )

            resolved_entry: subsequence.pattern.MirrorSpec = (
                (device, resolved_channel)
                if drum_map is None
                else (device, resolved_channel, drum_map)
            )
            resolved.append(resolved_entry)

        return resolved

    @property
    def harmonic_state(
        self,
    ) -> typing.Optional[subsequence.harmonic_state.HarmonicState]:
        """The active ``HarmonicState``, or ``None`` if ``harmony()`` has not been called."""
        return self._harmonic_state

    def current_chord(self) -> typing.Optional[typing.Any]:
        """The chord sounding at the playhead, or ``None`` without harmony.

        Reads the harmony window at the current pulse, so it stays accurate
        under variable harmonic rhythm and clock lookahead (the engine's
        ``current_chord`` flips *lookahead* beats early — this does not).
        Falls back to the engine's chord before playback starts.  The chord
        may be a decorated wrapper (``Am9``, ``C/G``) when the sounding span
        is spiced; it duck-types the ``Chord`` voicing protocol either way.
        """

        if not self._harmony_horizon.is_empty:
            beat = self._sequencer.pulse_count / self._sequencer.pulses_per_beat
            chord = self._harmony_horizon.chord_at(beat)
            if chord is not None:
                return chord

        if self._harmonic_state is not None:
            return self._harmonic_state.get_current_chord()

        return None

    def _effective_key_scale(
        self,
        section_info: typing.Optional["subsequence.form_state.SectionInfo"],
    ) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
        """Resolve the key and scale in force, by the key-source precedence.

        The layered chain, key and scale resolved **independently** so a
        section can move the tonic, the mode, or both:
        ``Section.key`` > form key (``form(key=)`` / ``Form(key=)``) >
        ``Composition.key``, and likewise for scale.  This is the one place
        the tier order lives; every placement site routes through it so the
        section key reaches every compositional element uniformly (the
        three-intent model: only *key-relative* content reads this — absolute
        content ignores it, chord-relative content tracks the chord).
        """

        key: typing.Optional[str] = None
        scale: typing.Optional[str] = None

        if section_info is not None:
            key = section_info.key
            scale = section_info.scale

        if key is None:
            key = self._form_key
        if key is None:
            key = self.key

        if scale is None:
            scale = self._form_scale
        if scale is None:
            scale = self.scale

        return key, scale

    def _resolve_section_progression(
        self,
        info: "subsequence.form_state.SectionInfo",
    ) -> typing.Optional[Progression]:
        """Resolve a section's bound progression against its effective key/scale.

        Concrete progressions (names, ``PitchSet``, frozen captures) are
        returned unchanged.  Key-relative ones resolve against the section's
        effective key+scale — memoised per ``(name, key, scale)`` so a stable
        section reuses one realisation and span identity is stable across
        ticks.  If no key is resolvable at this moment the section is skipped
        (returns ``None`` → falls through to the bound/live source) with a
        warning; the authoritative check runs at :meth:`play`/:meth:`render`.
        """

        raw = self._section_progressions.get(info.name)

        if raw is None or raw.is_concrete:
            return raw

        key, scale = self._effective_key_scale(info)

        if key is None:
            logger.warning(
                "section_chords(%r) is key-relative but no key resolves for this section — "
                "skipping (the chords fall through to the live/bound source)",
                info.name,
            )
            return None

        cache_key = (info.name, key, scale)
        cached = self._resolved_section_cache.get(cache_key)

        if cached is not None:
            return cached

        try:
            resolved = raw.resolve(key, scale or "ionian")
        except ValueError as error:
            # A degree out of range for the effective scale, or an unknown
            # scale — never let it escape the clock callback (that would kill
            # harmony for the rest of playback).  Skip the section; the _run
            # pre-flight catches the common case far earlier.
            logger.warning(
                "section_chords(%r) cannot resolve against %s %s (%s) — skipping; "
                "the chords fall through to the live/bound source",
                info.name,
                key,
                scale or "ionian",
                error,
            )
            return None

        self._resolved_section_cache[cache_key] = resolved
        return resolved

    @property
    def form_state(self) -> typing.Optional["subsequence.form_state.FormState"]:
        """The active ``subsequence.form_state.FormState``, or ``None`` if ``form()`` has not been called."""
        return self._form_state

    @property
    def sequencer(self) -> subsequence.sequencer.Sequencer:
        """The underlying ``Sequencer`` instance."""
        return self._sequencer

    @property
    def running_patterns(self) -> typing.Dict[str, typing.Any]:
        """The currently active patterns, keyed by name."""
        return self._running_patterns

    @property
    def builder_bar(self) -> int:
        """Current bar index used by pattern builders."""
        return self._builder_bar

    def _require_harmonic_state(self) -> subsequence.harmonic_state.HarmonicState:
        """Return the active HarmonicState, raising ValueError if none is configured."""
        if self._harmonic_state is None:
            raise ValueError(
                "harmony() must be called before this action — "
                "no harmonic state has been configured."
            )
        return self._harmonic_state

    def _coerce_progression(self, source: typing.Any, what: str) -> Progression:
        """Coerce a Progression / element list / preset name and resolve it against the key.

        Binding freezes one realisation (the value type's identity), so
        key-relative content resolves here, at bind time, against the
        composition's key and scale.  Used by the *global* bound progression
        (``harmony(progression=)``) — which is not section-scoped, so it has
        nothing to re-key against.
        """

        value = (
            source
            if isinstance(source, Progression)
            else subsequence.progressions.progression(source)
        )

        if not value.is_concrete:
            if self.key is None:
                raise ValueError(
                    f"{what} contains key-relative chords (degrees/romans) — "
                    "set key= on the Composition so they can resolve"
                )
            value = value.resolve(self.key, self.scale or "ionian")

        return value

    def _coerce_section_progression(self, source: typing.Any) -> Progression:
        """Coerce a section progression, keeping key-relative content UNRESOLVED.

        Section harmony re-keys per occurrence (the section/form/composition
        key in force when the section plays), so a key-relative progression is
        stored relative and resolved late, in the clock, against the section's
        effective key+scale — unlike the global bound progression, which
        freezes at bind.  Concrete content (chord names, frozen captures,
        ``PitchSet``) is already absolute and never moves.
        """

        return (
            source
            if isinstance(source, Progression)
            else subsequence.progressions.progression(source)
        )

    def harmony(
        self,
        style: typing.Optional[
            typing.Union[str, subsequence.chord_graphs.ChordGraph]
        ] = None,
        cycle_beats: int = 4,
        dominant_7th: bool = True,
        gravity: float = 1.0,
        nir_strength: float = 0.5,
        minor_turnaround_weight: float = 0.0,
        root_diversity: float = subsequence.harmonic_state.DEFAULT_ROOT_DIVERSITY,
        reschedule_lookahead: float = 1,
        progression: typing.Optional[typing.Any] = None,
    ) -> None:
        """
        Configure the harmonic logic and chord change intervals.

        Two sources, combinable: a **bound progression** (``progression=`` — a
        :class:`Progression` value, an element list like ``[1, 6, 3, "bVII7"]``,
        or chord names) walked span by span on the global clock; and/or a
        **graph style** stepping live chords.  With only a progression bound,
        it loops on exhaustion; with a style configured too, exhaustion falls
        through to live stepping (the frozen-replay bridge).  Calling with
        neither argument keeps today's default live engine
        (``style="functional_major"``).

        Parameters:
                style: The harmonic style to use. Built-in: "functional_major"
                        (alias "diatonic_major"), "hooktheory_major" (alias
                        "pop_major"), "turnaround", "aeolian_minor",
                        "phrygian_minor", "lydian_major", "dorian_minor",
                        "chromatic_mediant", "suspended", "mixolydian", "whole_tone",
                        "diminished". See README for full descriptions.
                cycle_beats: How many beats each live chord lasts (default 4).
                        Bound progressions carry their own harmonic rhythm in their
                        spans, so this applies to live stepping only.  A re-call
                        during playback takes effect from the next chord boundary;
                        a FIRST harmony() call mid-playback starts the clock itself.
                dominant_7th: Whether to include V7 chords (default True).
                gravity: Key gravity (0.0 to 1.0). High values stay closer to the root chord.
                nir_strength: Melodic inertia (0.0 to 1.0). Influences chord movement
                        expectations.
                minor_turnaround_weight: For "turnaround" style, influences major vs minor feel.
                root_diversity: Root-repetition damping (0.0 to 1.0). Each recent
                        chord sharing a candidate's root reduces the weight to 40% at
                        the default (0.4). Set to 1.0 to disable.
                reschedule_lookahead: How many beats in advance to calculate the
                        next chord.
                progression: A progression to bind to the global clock.  Key-
                        relative content resolves now, against the composition key
                        and scale (binding freezes one realisation).

        Example:
                ```python
                # A moody minor progression that changes every 8 beats
                comp.harmony(style="aeolian_minor", cycle_beats=8, gravity=0.4)

                # Manual harmony driving everything — loops forever
                comp.harmony(progression=subsequence.progression([1, 6, 3, 7]))
                ```
        """

        if style is None and progression is None:
            # A parameter-only re-call (gravity=, cycle_beats=, ...) keeps the
            # configured style — defaulting unconditionally here would silently
            # replace e.g. aeolian_minor with functional_major.
            style = (
                self._last_harmony_style
                if self._last_harmony_style is not None
                else "functional_major"
            )

        if style is not None:
            if self.key is None:
                raise ValueError(
                    "Cannot configure harmony without a key - set key in the Composition constructor"
                )

            preserved_history: typing.List[subsequence.chords.Chord] = []
            preserved_current: typing.Optional[subsequence.chords.Chord] = None

            if self._harmonic_state is not None:
                preserved_history = self._harmonic_state.history.copy()
                preserved_current = self._harmonic_state.current_chord

            # Per-call salted build stream (harmony:1, harmony:2, ...): a re-call
            # gets its own deterministic stream while history and current chord
            # are preserved above, and adding a re-call never shifts any other
            # consumer's stream.
            self._harmony_count += 1

            self._harmonic_state = subsequence.harmonic_state.HarmonicState(
                key_name=self.key,
                graph_style=style,
                include_dominant_7th=dominant_7th,
                key_gravity_blend=gravity,
                nir_strength=nir_strength,
                minor_turnaround_weight=minor_turnaround_weight,
                root_diversity=root_diversity,
                rng=self._stream(f"harmony:{self._harmony_count}"),
            )

            if preserved_history:
                self._harmonic_state.history = preserved_history
            if (
                preserved_current is not None
                and self._harmonic_state.graph.get_transitions(preserved_current)
            ):
                self._harmonic_state.current_chord = preserved_current

            self._harmony_style = style if isinstance(style, str) else None
            self._last_harmony_style = style

        if progression is not None:
            self._bound_progression = self._coerce_progression(
                progression, "harmony(progression=)"
            )

        self._harmony_cycle_beats = cycle_beats
        self._harmony_reschedule_lookahead = reschedule_lookahead

        # A re-call invalidates whatever the horizon had planned.
        self._harmony_horizon.invalidate_future()

        # A FIRST harmony() call mid-playback must start the clock itself —
        # _run() only schedules clocks for sources it can see at play() time.
        # (Re-calls need nothing here: the clock reads its sources through
        # getters on every tick.)
        loop = self._sequencer._event_loop

        if loop is not None and loop.is_running() and not self._harmonic_clock_started:
            try:
                on_loop = asyncio.get_running_loop() is loop
            except RuntimeError:
                on_loop = False

            if on_loop:
                loop.create_task(self._start_harmonic_clock())
            else:
                asyncio.run_coroutine_threadsafe(self._start_harmonic_clock(), loop)

    async def _start_harmonic_clock(
        self,
        bar_beats: typing.Optional[float] = None,
        clock_lookahead: typing.Optional[float] = None,
    ) -> None:
        """Register the span-walking harmonic clock (idempotent per playback).

        Called from ``_run()`` when a harmony source exists at play time, and
        from ``harmony()`` when the FIRST source arrives mid-playback.
        ``bar_beats``/``clock_lookahead`` default to a fresh computation for
        the mid-playback path; ``_run()`` passes the values it validated.
        """

        if self._harmonic_clock_started:
            return

        self._harmonic_clock_started = True

        if bar_beats is None:
            bar_beats = float(self.time_signature[0])

        if clock_lookahead is None:
            lookaheads = [
                pattern.reschedule_lookahead
                for pattern in self._running_patterns.values()
            ]
            clock_lookahead = min(
                bar_beats,
                max(
                    1.0,
                    float(self._harmony_reschedule_lookahead),
                    float(max(lookaheads, default=1)),
                ),
            )

        def _get_section_progression() -> typing.Optional[
            typing.Tuple[str, int, int, typing.Optional[Progression]]
        ]:
            """Return (section_name, section_index, bars, Progression|None) for the current section, or None.

            The progression is resolved against the section's effective
            key/scale here (key-relative section harmony re-keys per
            occurrence); concrete content passes through unchanged.
            """
            if self._form_state is None:
                return None
            info = self._form_state.get_section_info()
            if info is None:
                return None
            prog = self._resolve_section_progression(info)
            return (info.name, info.index, info.bars, prog)

        def _resolve_cadence_formula(
            name: str,
        ) -> typing.List[subsequence.chords.Chord]:
            """Resolve a cadence formula against the composition key and scale, at plan time."""
            hs = self._harmonic_state
            key_pc = (
                subsequence.chords.key_name_to_pc(self.key)
                if self.key is not None
                else (hs.key_root_pc if hs is not None else 0)
            )
            spec = subsequence.cadences.cadence_formula(name)
            return [
                subsequence.progressions.resolve_constraint(
                    element, key_pc, self._constraint_scale(), f"cadence {name!r}"
                )
                for element in spec.formula
            ]

        await schedule_harmonic_clock(
            sequencer=self._sequencer,
            get_harmonic_state=lambda: self._harmonic_state,
            horizon=self._harmony_horizon,
            bar_beats=bar_beats,
            cycle_beats=self._harmony_cycle_beats or 4,
            get_cycle_beats=lambda: self._harmony_cycle_beats or 4,
            get_bound_progression=lambda: self._bound_progression,
            get_section_progression=_get_section_progression,
            get_pinned=self._resolve_pin,
            cadence_requests=self._cadence_requests,
            resolve_cadence=_resolve_cadence_formula,
            get_section_cadence=self._section_cadences.get,
            reschedule_lookahead=clock_lookahead,
        )

    def _constraint_scale(self) -> str:
        """The scale that hybrid-constraint ints resolve against.

        The composition's own scale when set; otherwise inferred from the
        harmony style (``aeolian_minor`` → minor, matching
        :meth:`Progression.generate`'s documented inference), falling back
        to ionian.  Roman strings carry their quality and never need it.
        """

        if self.scale is not None:
            return self.scale

        return subsequence.progressions._STYLE_SCALES.get(
            self._harmony_style or "", "ionian"
        )

    def freeze(
        self,
        bars: int,
        end: typing.Optional[typing.Any] = None,
        pins: typing.Optional[typing.Dict[int, typing.Any]] = None,
        avoid: typing.Optional[typing.Sequence[typing.Any]] = None,
        cadence: typing.Optional[str] = None,
    ) -> "Progression":
        """Capture a chord progression from the live harmony engine.

        Runs the harmony engine forward by *bars* chord changes, records each
        chord, and returns it as a :class:`Progression` that can be bound to a
        form section with :meth:`section_chords`.

        The engine state **advances** — successive ``freeze()`` calls produce a
        continuing compositional journey so section progressions feel like parts
        of a whole rather than isolated islands.

        The hybrid constraints compile into the walk: ``end=`` fixes the last
        bar ("end on V at bar 8"), ``pins=`` fix any 1-based bar, ``avoid=``
        excludes chords throughout.  Specs follow the progression-element
        grammar (ints where diatonic, roman/name strings where chromatic) and
        resolve against the composition key and scale.  A backward
        feasibility pass guarantees satisfiability before any chord is drawn;
        the forward walk keeps the engine's real history-dependent weighting.
        Bar 1 is always the engine's current chord — the journey continues —
        so ``pins={1: ...}`` may only name it redundantly.

        Parameters:
                bars: Number of chords to capture (one per harmony cycle).
                end: The chord at the final bar — ``end="V"`` is the cadential
                        major dominant in minor.
                pins: ``{bar: chord}`` — 1-based fiat positions.
                avoid: Chords excluded from the walk.
                cadence: A cadence name (``"strong"``/``"soft"``/``"open"``/
                        ``"fakeout"``, theory aliases accepted) — its formula pins
                        the final bars, so the walk approaches the close.
                        Conflicts with ``end=`` or pins on those bars.

        Returns:
                A :class:`Progression` with the captured chords and trailing
                history for NIR continuity.

        Raises:
                ValueError: If :meth:`harmony` has not been called first, or the
                        constraints are contradictory or unsatisfiable.

        Example::

                composition.harmony(style="functional_major", cycle_beats=4)
                verse  = composition.freeze(8, end="V")   # the verse sets up the chorus
                chorus = composition.freeze(4)            # next 4 chords, continuing on
                composition.section_chords("verse",  verse)
                composition.section_chords("chorus", chorus)
        """

        hs = self._require_harmonic_state()

        if bars < 1:
            raise ValueError("bars must be at least 1")

        if cadence is not None:
            pins = subsequence.progressions.cadence_pins(cadence, bars, pins, end)
            end = None

        scale = self._constraint_scale()
        key_pc = (
            subsequence.chords.key_name_to_pc(self.key)
            if self.key is not None
            else hs.key_root_pc
        )

        resolved_pins = {
            position: subsequence.progressions.resolve_constraint(
                spec, key_pc, scale, f"pins[{position}]"
            )
            for position, spec in (pins or {}).items()
        }
        resolved_end = (
            subsequence.progressions.resolve_constraint(end, key_pc, scale, "end")
            if end is not None
            else None
        )
        resolved_avoid = [
            subsequence.progressions.resolve_constraint(spec, key_pc, scale, "avoid")
            for spec in (avoid or [])
        ]

        if 1 in resolved_pins and resolved_pins[1] != hs.current_chord:
            raise ValueError(
                f"pins[1]={resolved_pins[1].name()} conflicts with the engine's current chord "
                f"({hs.current_chord.name()}) — bar 1 of a freeze continues the journey; "
                "pin a later bar, or use pin_chord() for playback fiat"
            )

        # Per-call salted stream (freeze:1, freeze:2, ...): each call's draws
        # are independent of every other consumer, so frozen progressions are
        # reproducible WITHOUT play() and adding a call cannot shift a
        # neighbour's output.  Engine state still advances normally — chord
        # continuity comes from current_chord/history, randomness from the
        # salted stream (swap-and-restore keeps hs.rng for play untouched).
        self._freeze_count += 1
        stream = self._stream(f"freeze:{self._freeze_count}")
        saved_rng = hs.rng

        if stream is not None:
            hs.rng = stream

        try:
            # The kernel with the engine's own hooks is draw-for-draw the old
            # step() loop when unconstrained — one walk path for both.
            def _commit(chosen: subsequence.chords.Chord) -> None:
                hs.current_chord = chosen

            collected = subsequence.sequence_utils.constrained_walk(
                hs.graph,
                hs.current_chord,
                bars,
                rng=hs.rng,
                pins=resolved_pins,
                end=resolved_end,
                avoid=resolved_avoid,
                weight_modifier=hs._transition_weight,
                before_choice=hs._record_transition_source,
                after_choice=_commit,
            )

            # Advance past the last captured chord so the next freeze() call or
            # live playback does not duplicate it.
            hs.step()

        finally:
            hs.rng = saved_rng

        span_beats = float(self._harmony_cycle_beats or 4)

        return Progression(
            spans=tuple(
                subsequence.progressions.ChordSpan(chord=chord, beats=span_beats)
                for chord in collected
            ),
            trailing_history=tuple(hs.history),
        )

    def section_chords(self, section_name: str, progression: typing.Any) -> None:
        """Bind a :class:`Progression` to a named form section.

        Every time *section_name* plays, the harmonic clock walks the
        progression's spans instead of calling the live engine.  Sections
        without a bound progression continue generating live chords.

        Accepts a :class:`Progression` value (from :meth:`freeze`, the
        ``progression()`` factory, or hand-built) or anything the factory
        accepts — an element list like ``[1, 6, 3, "bVII7"]`` or chord
        names.

        **Key-relative content re-keys per occurrence.**  A progression
        written in degrees or romans is *key-relative* content: it resolves
        late, each time the section plays, against that section's effective
        key and scale (``Section.key`` > form key > composition key, with
        mode following the same chain).  So a ``Section(key="A")`` plays the
        same numbered progression a tone higher — its chords and its degrees
        share one tonic.  *Absolute* content — chord names (``"Am"``),
        :class:`~subsequence.progressions.PitchSet`, and frozen captures from
        :meth:`freeze` — names exact chords and is never transposed by a key.

        On exhaustion mid-section the progression loops when no graph style
        is configured (and always when it contains a ``PitchSet``); with a
        live engine, exhaustion **falls through to live stepping in the
        COMPOSITION key** — the live graph engine does not transpose for a
        section (a stateful walk does not modulate mid-stream), so a
        re-keyed section that runs out of written chords hands off to
        composition-key harmony.  Bind a full-length progression (or set
        ``at_end``/loop intent) if you need the whole section in its key.

        Parameters:
                section_name: Name of the section as defined in :meth:`form`.
                progression: The progression to bind.

        Raises:
                ValueError: If a graph-based form has been configured and
                        *section_name* is not one of its sections.  List and generator
                        forms yield names lazily, so they cannot be validated here.
                        (A key-relative progression with no resolvable key for the
                        section is caught at :meth:`play`/:meth:`render`, once the
                        form's keys are known.)

        Example::

                composition.section_chords("verse",  verse_progression)
                composition.section_chords("chorus", [1, 6, 3, 7])
                # "bridge" is not bound — it generates live chords
        """

        if (
            self._form_state is not None
            and self._form_state._section_bars is not None
            and section_name not in self._form_state._section_bars
        ):
            known = ", ".join(sorted(self._form_state._section_bars))
            raise ValueError(
                f"Section '{section_name}' not found in form. Known sections: {known}"
            )

        self._section_progressions[section_name] = self._coerce_section_progression(
            progression
        )
        self._resolved_section_cache = {}
        self._harmony_horizon.invalidate_future()

    def pin_chord(self, bar: int, chord: typing.Optional[typing.Any]) -> None:
        """Force the chord sounding at a bar — fiat over live generation.

        Whatever the harmonic source (live walk, bound progression, section
        progression) produces for *bar*, the pinned chord overrides it.
        Pass ``None`` to remove a pin.

        Parameters:
                bar: 1-based bar number (the musician count).
                chord: A chord name, int degree, roman string, ``Chord``,
                        ``PitchSet``, or ``None`` to unpin.  A **key-relative** spec
                        (int degree, roman) re-keys like section harmony: it resolves
                        late, against the effective key of the section sounding at
                        that bar (so ``pin_chord(8, "V")`` is the dominant of
                        wherever bar 8 lands).  A **concrete** spec (name, ``Chord``,
                        ``PitchSet``) is absolute and never moves.

        Example::

                composition.pin_chord(8, "E7")    # the turnaround lands on E7
                composition.pin_chord(8, "V")     # the dominant of bar 8's section
                composition.pin_chord(8, None)    # let it walk again
        """

        if not isinstance(bar, int) or isinstance(bar, bool) or bar < 1:
            raise ValueError(f"bars are 1-based ints, got {bar!r}")

        if chord is None:
            self._pinned_chords.pop(bar, None)
        else:
            # Store the parsed span — relative pins resolve late (per section)
            # at the clock; concrete pins are absolute.
            span = subsequence.progressions.parse_element(
                chord, beats=float(self.time_signature[0])
            )

            if not span.is_concrete:
                # Raise early only when no key is resolvable for this bar — the
                # bar's own section (sequence forms) may supply one even with no
                # composition/form key.
                probe_info = (
                    self._form_state.section_info_at_bar(bar)
                    if self._form_state is not None
                    else None
                )
                probe_key, _ = self._effective_key_scale(probe_info)
                if probe_key is None:
                    raise ValueError(
                        "pin_chord with a key-relative spec (degree/roman) needs a key — set key= on "
                        "the Composition, a form key, or a Section.key for that bar (the pin re-keys "
                        "to the section's effective key)"
                    )

            self._pinned_chords[bar] = span

        self._harmony_horizon.invalidate_future()

    def _resolve_pin(self, bar: int) -> typing.Optional[typing.Any]:
        """Resolve a stored pin to a chord-like, re-keying relative pins per section.

        Concrete pins return their chord directly; key-relative pins resolve
        against the effective key of the section sounding now (the clock
        reads this as it reaches each bar).  Returns ``None`` (no pin / a
        relative pin with no resolvable key, warned) so the clock falls
        through to its normal source.
        """

        span = self._pinned_chords.get(bar)

        if span is None:
            return None

        if span.is_concrete:
            return _span_chord(span)

        # Key the pin to the section that OWNS this bar (the clock's lookahead
        # can project a pin into a later, differently-keyed section while the
        # playhead is still earlier) — fall back to the playhead section where
        # a per-bar section is not computable (graph/generator forms).
        info: typing.Optional["subsequence.form_state.SectionInfo"] = None
        if self._form_state is not None:
            info = self._form_state.section_info_at_bar(bar)
            if info is None:
                info = self._form_state.get_section_info()

        key, scale = self._effective_key_scale(info)

        if key is None:
            logger.warning(
                "pin_chord(%d, ...) is key-relative but no key resolves for that bar — ignoring the pin",
                bar,
            )
            return None

        return _span_chord(
            span.resolve(subsequence.chords.key_name_to_pc(key), scale or "ionian")
        )

    def request_cadence(
        self, cadence: str = "strong", bar: typing.Optional[int] = None
    ) -> None:
        """Ask the live engine to approach a cadence arriving at a bar.

        The request hook: where :meth:`pin_chord` is fiat, this is a
        *steered approach* — at the next chord boundary the clock plans the
        remaining changes up to *bar* as a constrained walk through the
        engine's real weights, pinned to the cadence formula at the tail
        (``"strong"`` arrives V→I, ``"soft"`` IV→I, ``"open"`` IV→V,
        ``"fakeout"`` V→vi; theory aliases accepted).  The chords still
        commit one boundary at a time, so the journey continues through the
        close.

        One-shot: the request is consumed when planned.  Live harmony only —
        bound/section progressions are data and cannot be steered; a request
        whose bar passes unserved expires with a warning.  If the formula is
        not walkable from where the harmony stands, the arrival lands by
        fiat (loudly).  Ask at least a pattern-lookahead ahead: patterns may
        already have rendered against the previously planned chord.

        Parameters:
                cadence: The cadence name.
                bar: The 1-based bar the cadence's final chord arrives at
                        (required; in practice ≥ 2 — bar 1 cannot be approached).

        Example::

                composition.request_cadence("open", bar=16)    # hang on V at bar 16
        """

        spec = subsequence.cadences.cadence_formula(cadence)

        if bar is None or not isinstance(bar, int) or isinstance(bar, bool) or bar < 1:
            raise ValueError(
                f"request_cadence needs bar= — the 1-based bar the cadence arrives at (got {bar!r})"
            )

        self._cadence_requests[bar] = spec.name
        self._harmony_horizon.invalidate_future()

    def section_cadence(
        self, section_name: str, cadence: typing.Optional[str] = "strong"
    ) -> None:
        """Close every pass of a section with a cadence — the standing request.

        Each time *section_name* is entered, the clock registers a
        :meth:`request_cadence` arriving at the section's final bar, so the
        harmony approaches the close as the section ends.  Live harmony
        only: a section with bound chords (:meth:`section_chords`) is data
        and ignores the registration — its closes are written, not steered.
        Pass ``None`` to unregister.

        Example::

                composition.form([("verse", 8), ("chorus", 8)])
                composition.section_cadence("verse", "open")     # every verse hangs on V
                composition.section_cadence("chorus", "strong")  # every chorus lands home
        """

        if cadence is None:
            self._section_cadences.pop(section_name, None)
            return

        spec = subsequence.cadences.cadence_formula(cadence)
        self._section_cadences[section_name] = spec.name

    def section_motifs(
        self, section_name: str, value: typing.Any, part: typing.Optional[str] = None
    ) -> None:
        """Bind a Motif or Phrase to a named form section (per optional part).

        Patterns read the binding back with ``p.section_motif(part)`` (or use
        the one-call :meth:`phrase_part`); a section with no binding for the
        part is silent for that part — bind material or don't, no fallback
        guessing.  Re-binding is idempotent, so the call is safe in a live
        file: re-executing on save is the desired rebind.

        Parameters:
                section_name: Name of the section as defined in :meth:`form`.
                value: A ``Motif`` or ``Phrase`` (anything exposing
                        ``.length``/``.slice`` places).
                part: Optional part label, so one section can carry several
                        bindings (``"lead"``, ``"bass"``, ...).

        Raises:
                ValueError: If a graph-based form has been configured and
                        *section_name* is not one of its sections.

        Example::

                composition.section_motifs("verse",  verse_line,  part="lead")
                composition.section_motifs("chorus", chorus_line, part="lead")
        """

        if not hasattr(value, "length") or not hasattr(value, "slice"):
            raise TypeError(
                f"section_motifs() binds Motif/Phrase values (.length/.slice) — got {type(value).__name__}"
            )

        if (
            self._form_state is not None
            and self._form_state._section_bars is not None
            and section_name not in self._form_state._section_bars
        ):
            known = ", ".join(sorted(self._form_state._section_bars))
            raise ValueError(
                f"Section '{section_name}' not found in form. Known sections: {known}"
            )

        self._section_motifs[(section_name, part)] = value

    def on_event(
        self, event_name: str, callback: typing.Callable[..., typing.Any]
    ) -> None:
        """
        Register a callback for a sequencer event (e.g., "bar", "start", "stop").
        """

        self._sequencer.on_event(event_name, callback)

    # -----------------------------------------------------------------------
    # Hotkey API
    # -----------------------------------------------------------------------

    def hotkeys(self, enabled: bool = True) -> None:
        """Enable or disable the global hotkey listener.

        Must be called **before** :meth:`play` to take effect.  When enabled, a
        background thread reads single keystrokes from stdin without requiring
        Enter.  The ``?`` key is always reserved and lists all active bindings.

        Hotkeys have zero impact on playback when disabled — the listener
        thread is never started.

        Args:
            enabled: ``True`` (default) to enable hotkeys; ``False`` to disable.

        Example::

            composition.hotkeys()
            composition.hotkey("a", lambda: composition.form_jump("chorus"))
            composition.play()
        """

        self._hotkeys_enabled = enabled

    def hotkey(
        self,
        key: str,
        action: typing.Callable[[], None],
        quantize: int = 0,
        label: typing.Optional[str] = None,
    ) -> None:
        """Register a single-key shortcut that fires during playback.

        The listener must be enabled first with :meth:`hotkeys`.

        Most actions — form jumps, ``composition.data`` writes, and
        :meth:`tweak` calls — should use ``quantize=0`` (the default).  Their
        musical effect is naturally delayed to the next pattern rebuild cycle,
        which provides automatic musical quantization without extra configuration.

        Use ``quantize=N`` for actions where you want an explicit bar-boundary
        guarantee, such as :meth:`mute` / :meth:`unmute`.

        The ``?`` key is reserved and cannot be overridden.

        Args:
            key: A single character trigger (e.g. ``"a"``, ``"1"``, ``" "``).
            action: Zero-argument callable to execute.
            quantize: ``0`` = execute immediately (default).  ``N`` = execute
                on the next global bar number divisible by *N*.
            label: Display name for the ``?`` help listing.  Auto-derived from
                the function name or lambda body if omitted.

        Raises:
            ValueError: If ``key`` is the reserved ``?`` character, or if
                ``key`` is not exactly one character.

        Example::

            composition.hotkeys()

            # Immediate — musical effect happens at next pattern rebuild
            composition.hotkey("a", lambda: composition.form_jump("chorus"))
            composition.hotkey("1", lambda: composition.data.update({"mode": "chill"}))

            # Explicit 4-bar phrase boundary
            composition.hotkey("s", lambda: composition.mute("drums"), quantize=4)

            # Named function — label is derived automatically
            def drop_to_breakdown ():
                composition.form_jump("breakdown")
                composition.mute("lead")

            composition.hotkey("d", drop_to_breakdown)

            composition.play()
        """

        if len(key) != 1:
            raise ValueError(f"hotkey key must be a single character, got {key!r}")

        if key == _HOTKEY_RESERVED:
            raise ValueError(
                f"'{_HOTKEY_RESERVED}' is reserved for listing active hotkeys."
            )

        derived = label if label is not None else _derive_label(action)

        self._hotkey_bindings[key] = HotkeyBinding(
            key=key,
            action=action,
            quantize=quantize,
            label=derived,
        )

    def form_jump(self, section_name: str) -> None:
        """Jump the form to a named section immediately.

        Delegates to :meth:`subsequence.form_state.FormState.jump_to`.  Only works when the
        composition uses graph-mode form (a dict passed to :meth:`form`).

        The musical effect is heard at the *next pattern rebuild cycle* — already-
        queued MIDI notes are unaffected.  This natural delay means ``form_jump``
        is effective without needing explicit quantization.

        Args:
            section_name: The section to jump to.

        Raises:
            ValueError: If no form is configured, or the form is not in graph
                mode, or *section_name* is unknown.

        Example::

            composition.hotkey("c", lambda: composition.form_jump("chorus"))
        """

        if self._form_state is None:
            raise ValueError(
                "form_jump() requires a form to be configured via composition.form()."
            )

        self._form_state.jump_to(section_name)

        # The harmony horizon planned against the old section — revoke it.
        self._harmony_horizon.invalidate_future()

    def form_next(self, section_name: str) -> None:
        """Queue the next section — takes effect when the current section ends.

        Unlike :meth:`form_jump`, this does not interrupt the current section.
        The queued section replaces the automatically pre-decided next section
        and takes effect at the natural section boundary.  The performer can
        change their mind by calling ``form_next`` again before the boundary.

        Delegates to :meth:`subsequence.form_state.FormState.queue_next`.  Only works when the
        composition uses graph-mode form (a dict passed to :meth:`form`).

        Args:
            section_name: The section to queue.

        Raises:
            ValueError: If no form is configured, or the form is not in graph
                mode, or *section_name* is unknown.

        Example::

            composition.hotkey("c", lambda: composition.form_next("chorus"))
        """

        if self._form_state is None:
            raise ValueError(
                "form_next() requires a form to be configured via composition.form()."
            )

        self._form_state.queue_next(section_name)

        # The harmony horizon planned against the old continuation — revoke it.
        self._harmony_horizon.invalidate_future()

    def _list_hotkeys(self) -> None:
        """Log all active hotkey bindings (triggered by the ``?`` key).

        Output appears via the standard logger so it scrolls cleanly above
        the :class:`~subsequence.display.Display` status line.
        """

        lines = ["Active hotkeys:"]
        for key in sorted(self._hotkey_bindings):
            b = self._hotkey_bindings[key]
            quant_str = "immediate" if b.quantize == 0 else f"quantize={b.quantize}"
            lines.append(f"  {key}  \u2192  {b.label}  ({quant_str})")
        lines.append(f"  ?  \u2192  list hotkeys")
        logger.info("\n".join(lines))

    def _process_hotkeys(self, bar: int) -> None:
        """Drain pending keystrokes and execute due actions.

        Called on every ``"bar"`` event by the sequencer when hotkeys are
        enabled.  Handles both immediate (``quantize=0``) and quantized actions.

        Both kinds run here, on the bar-event callback (the event loop): the
        keystroke listener thread only enqueues keypresses (``drain()``), it
        never executes actions.  Immediate (``quantize=0``) bindings fire as soon
        as the key is drained; quantized ones wait for their next boundary.

        Args:
            bar: The current global bar number from the sequencer.
        """

        if self._keystroke_listener is None:
            return

        # Process newly arrived keys.
        for key in self._keystroke_listener.drain():
            if key == _HOTKEY_RESERVED:
                self._list_hotkeys()
                continue

            binding = self._hotkey_bindings.get(key)
            if binding is None:
                continue

            if binding.quantize == 0:
                # Immediate — execute now (we're on the bar-event callback,
                # which is safe for all mutation methods).
                try:
                    binding.action()
                    logger.info(f"Hotkey '{key}' \u2192 {binding.label}")
                except Exception as exc:
                    logger.warning(f"Hotkey '{key}' action raised: {exc}")
            else:
                # Defer until the next quantize boundary.
                self._pending_hotkey_actions.append(
                    _PendingHotkeyAction(binding=binding)
                )

        # Fire any pending actions whose bar boundary has arrived.
        still_pending: typing.List[_PendingHotkeyAction] = []

        for pending in self._pending_hotkey_actions:
            if bar % pending.binding.quantize == 0:
                try:
                    pending.binding.action()
                    logger.info(
                        f"Hotkey '{pending.binding.key}' \u2192 {pending.binding.label} "
                        f"(bar {bar})"
                    )
                except Exception as exc:
                    logger.warning(
                        f"Hotkey '{pending.binding.key}' action raised: {exc}"
                    )
            else:
                still_pending.append(pending)

        self._pending_hotkey_actions = still_pending

    @property
    def seed(self) -> typing.Optional[int]:
        """
        The composition's random seed, or None when unseeded.

        When set, every random decision derives deterministically from this
        value through named streams (see ``seed_for()``), so the same script
        produces the same music on every run.  Assign to set it::

                comp.seed = 42

        (Formerly the method ``comp.seed(42)`` — the call form is a hard
        break per the pre-1.0 rename policy.)
        """

        return self._seed

    @seed.setter
    def seed(self, value: typing.Optional[int]) -> None:
        """Set the composition seed (``comp.seed = 42``)."""

        self._seed = value

    def _stream_seed(self, name: str) -> typing.Optional[int]:
        """
        Derive the effective integer seed for a named random stream.

        The derivation is ``zlib.crc32(f"{seed}:{name}")`` — crc32 rather
        than ``hash()`` because it is stable across processes — plus the
        per-name nonce when ``reroll()`` has been called.  Returns None when
        the composition is unseeded.
        """

        if self._seed is None:
            return None

        nonce = self._reroll_nonces.get(name, 0)
        key = f"{self._seed}:{name}" if nonce == 0 else f"{self._seed}:{name}:{nonce}"
        return zlib.crc32(key.encode())

    def _stream(self, name: str) -> typing.Optional[random.Random]:
        """A fresh ``random.Random`` for a named stream, or None when unseeded."""

        stream_seed = self._stream_seed(name)
        return None if stream_seed is None else random.Random(stream_seed)

    def seed_for(self, name: str) -> typing.Optional[int]:
        """
        Surface the effective derived seed for a named stream.

        Works for pattern names and equally for any name you invent for a
        standalone value generator (``seed=composition.seed_for("hook")``),
        so its randomness keys off the composition seed without sharing any
        other consumer's stream.  Reflects ``reroll()`` nonces.  Returns None
        when the composition is unseeded.

        Example:
                ```python
                hook_seed = composition.seed_for("hook")
                ```
        """

        return self._stream_seed(name)

    def reroll(self, name: str) -> None:
        """
        Deal a named stream a fresh deterministic seed — try a new variation.

        Bumps the per-name nonce and prints the new effective seed.  The
        nonce lives only in this process, so the printed seed is what lets a
        variation you like survive a restart: note it down, or ``lock()`` the
        name to pin it for the session.  Refuses on locked names.

        Parameters:
                name: The stream name — usually a pattern name.

        Example:
                ```python
                comp.reroll("lead")    # prints: reroll('lead') -> effective seed ...
                ```
        """

        if name in self._locked_names:
            print(
                f"reroll('{name}') refused: '{name}' is locked - call unlock('{name}') first"
            )
            return

        self._reroll_nonces[name] = self._reroll_nonces.get(name, 0) + 1
        effective = self._stream_seed(name)

        if effective is None:
            print(f"reroll('{name}'): composition has no seed - randomness is unseeded")
            return

        running = self._running_patterns.get(name)

        if running is not None and hasattr(running, "_rng"):
            running._rng = random.Random(effective)

        print(
            f"reroll('{name}') -> effective seed {effective} (nonce {self._reroll_nonces[name]})"
        )

    def lock(self, name: str) -> None:
        """
        Pin a named stream: keep its current effective seed and realization.

        Engine-side state, so it survives live reload (it is never a builder
        swap): a locked pattern re-deals its stream from the same effective
        seed on every rebuild, so every cycle realizes identically, and
        ``reroll()`` refuses with a message until ``unlock()``.

        Parameters:
                name: The stream name — usually a pattern name.
        """

        self._locked_names.add(name)

    def unlock(self, name: str) -> None:
        """Release a ``lock()``: the stream runs free and ``reroll()`` works again."""

        self._locked_names.discard(name)

    def tuning(
        self,
        source: typing.Optional[typing.Union[str, "os.PathLike"]] = None,
        *,
        cents: typing.Optional[typing.List[float]] = None,
        ratios: typing.Optional[typing.List[float]] = None,
        equal: typing.Optional[int] = None,
        bend_range: float = 2.0,
        channels: typing.Optional[typing.List[int]] = None,
        reference_note: int = 60,
        exclude_drums: bool = True,
    ) -> None:
        """Set a global microtonal tuning for the composition.

        The tuning is applied automatically after each pattern rebuild (before
        the pattern is scheduled).  Drum patterns (those registered with a
        ``drum_note_map``) are excluded by default.

        Supply exactly one of the source parameters:

        - ``source``: path to a Scala ``.scl`` file.
        - ``cents``: list of cent offsets for degrees 1..N (degree 0 = 0.0 is implicit).
        - ``ratios``: list of frequency ratios (e.g., ``[9/8, 5/4, 4/3, 3/2, 2]``).
        - ``equal``: integer for N-tone equal temperament (e.g., ``equal=19``).

        For polyphonic parts, supply a ``channels`` pool.  Notes are spread
        across those MIDI channels so each can carry an independent pitch bend.
        The synth must be configured to match ``bend_range`` (its pitch-bend range
        setting in semitones).

        Parameters:
                source: Path to a ``.scl`` file.
                cents: Cent offsets for scale degrees 1..N.
                ratios: Frequency ratios for scale degrees 1..N.
                equal: Number of equal divisions of the period.
                bend_range: Synth pitch-bend range in semitones (default ±2).
                channels: Channel pool for polyphonic rotation.
                reference_note: MIDI note mapped to scale degree 0 (default 60 = C4).
                exclude_drums: When True (default), skip patterns that have a
                    ``drum_note_map`` (they use fixed GM pitches, not tuned ones).

        Example:
                ```python
                # Quarter-comma meantone from a Scala file
                comp.tuning("meanquar.scl")

                # Just intonation from ratios
                comp.tuning(ratios=[9/8, 5/4, 4/3, 3/2, 5/3, 15/8, 2])

                # 19-TET, monophonic
                comp.tuning(equal=19, bend_range=2.0)

                # 31-TET with channel rotation for polyphony (channels 1-6)
                comp.tuning("31tet.scl", channels=[0, 1, 2, 3, 4, 5])
                ```
        """
        import subsequence.tuning as _tuning_mod

        given = sum(x is not None for x in [source, cents, ratios, equal])
        if given == 0:
            raise ValueError(
                "composition.tuning() requires one of: source, cents, ratios, or equal"
            )
        if given > 1:
            raise ValueError("composition.tuning() accepts only one source parameter")

        if source is not None:
            t = _tuning_mod.Tuning.from_scl(source)
        elif cents is not None:
            t = _tuning_mod.Tuning.from_cents(cents)
        elif ratios is not None:
            t = _tuning_mod.Tuning.from_ratios(ratios)
        else:
            t = _tuning_mod.Tuning.equal(equal)  # type: ignore[arg-type]

        self._tuning = t
        self._tuning_bend_range = bend_range
        self._tuning_channels = channels
        self._tuning_reference_note = reference_note
        self._tuning_exclude_drums = exclude_drums

    def display(
        self, enabled: bool = True, grid: bool = False, grid_scale: float = 1.0
    ) -> None:
        """
        Enable or disable the live terminal dashboard.

        When enabled, Subsequence uses a safe logging handler that allows a
        persistent status line (BPM, Key, Bar, Section, Chord) to stay at
        the bottom of the terminal while logs scroll above it.

        Parameters:
                enabled: Whether to show the display (default True).
                grid: When True, render an ASCII grid visualisation of all
                        running patterns above the status line. The grid updates
                        once per bar, showing which steps have notes and at what
                        velocity.
                grid_scale: Horizontal zoom factor for the grid (default
                        ``1.0``).  Higher values add visual columns between
                        grid steps, revealing micro-timing from swing and groove.
                        Snapped to the nearest integer internally for uniform
                        marker spacing.
        """

        if enabled:
            self._display = subsequence.display.Display(
                self, grid=grid, grid_scale=grid_scale
            )
        else:
            self._display = None

    def web_ui(self, http_host: str = "127.0.0.1", ws_host: str = "127.0.0.1") -> None:
        """
        Enable the realtime Web UI Dashboard.

        When enabled, Subsequence instantiates a WebSocket server that broadcasts
        the current state, signals, and active patterns (with high-res timing and
        note data) to any connected browser clients.

        Both servers bind to localhost by default.  Pass ``http_host`` / ``ws_host``
        (e.g. "0.0.0.0") to opt into LAN exposure — the dashboard is read-only but
        broadcasts full composition state, so only do so on a trusted network.
        """

        self._web_ui_enabled = True
        self._web_ui_http_host = http_host
        self._web_ui_ws_host = ws_host

    def midi_input(
        self, device: str, clock_follow: bool = False, name: typing.Optional[str] = None
    ) -> None:
        """
        Configure a MIDI input device for external sync and MIDI messages.

        May be called multiple times to register additional input devices.
        The first call sets the primary input (device 0).  Subsequent calls
        add additional input devices (device 1, 2, …).  Only one device may
        have ``clock_follow=True``.

        Parameters:
                device: The name of the MIDI input port.
                clock_follow: If True, Subsequence will slave its clock to incoming
                        MIDI Ticks. It will also follow MIDI Start/Stop/Continue
                        commands. Only one device can have this enabled at a time.
                name: Optional alias for use with ``cc_map(input_device=…)`` and
                        ``cc_forward(input_device=…)``.  When omitted, the raw device
                        name is used.

        Example:
                ```python
                # Single controller (unchanged usage)
                comp.midi_input("Scarlett 2i4", clock_follow=True)

                # Multiple controllers
                comp.midi_input("Arturia KeyStep", name="keys")
                comp.midi_input("Faderfox EC4", name="faders")
                ```
        """

        if clock_follow:
            if self.is_clock_following:
                raise ValueError(
                    "Only one input device can be configured to follow external clock (clock_follow=True)"
                )

        if self._input_device is None:
            # First call: set primary input device (device 0)
            self._input_device = device
            self._input_device_alias = name
            self._clock_follow = clock_follow
        else:
            # Subsequent calls: register additional input devices
            self._additional_inputs.append((device, name, clock_follow))

    def midi_output(
        self, device: str, name: typing.Optional[str] = None, latency_ms: float = 0.0
    ) -> int:
        """
        Register an additional MIDI output device.

        The first output device is always the one passed to
        ``Composition(output_device=…)`` — that is device 0.
        Each call to ``midi_output()`` adds the next device (1, 2, …).

        Parameters:
                device: The exact name of the MIDI output port, as reported
                        by ``mido.get_output_names()``. Matching is strict —
                        partial names and substrings are rejected. See
                        ``Composition.__init__`` for the lookup snippet and a
                        note on ALSA name stability on Linux.
                name: Optional alias for use with ``pattern(device=…)``,
                        ``cc_forward(output_device=…)``, etc.  When omitted, the raw
                        device name is used.
                latency_ms: Physical output latency of this device in
                        milliseconds, for delay compensation (default 0.0, must be
                        non-negative). Set this when the device sounds late (e.g. a
                        software sampler) so Subsequence delays faster devices to
                        line everything up.

        Returns:
                The integer device index assigned (1, 2, 3, …).

        Example:
                ```python
                comp = subsequence.Composition(bpm=120, output_device="MOTU Express")

                # Returns 1 — use as device=1 or device="integra"
                comp.midi_output("Roland Integra", name="integra")

                # A software sampler that sounds 20ms late
                comp.midi_output("Subsample", name="sampler", latency_ms=20)

                @comp.pattern(channel=1, beats=4, device="integra")
                def strings (p):
                        p.note(60, beat=0)
                ```
        """

        if latency_ms < 0:
            raise ValueError(f"latency_ms must be non-negative — got {latency_ms}")

        idx = 1 + len(self._additional_outputs)  # device 0 is always the primary
        self._additional_outputs.append(
            _AdditionalOutput(device=device, alias=name, latency_ms=latency_ms)
        )
        return idx

    def _warn_if_high_latency(self) -> None:
        """Warn if delay compensation adds a large whole-rig latency.

        The slowest device defines the alignment point — every faster device is
        delayed up to that amount — so a large maximum means the whole rig
        responds late to live input.  Emitted once at startup.
        """

        candidates: typing.List[typing.Tuple[str, float]] = [
            ("primary output", self._output_latency_ms)
        ]
        candidates += [
            (out.alias or out.device, out.latency_ms)
            for out in self._additional_outputs
        ]

        slow_name, max_ms = max(candidates, key=lambda c: c[1])

        if max_ms > _LATENCY_WARN_THRESHOLD_MS:
            logger.warning(
                "Device latency compensation: '%s' is the slowest at %.0fms, so faster "
                "devices are delayed up to %.0fms to stay aligned — live-input feel may suffer.",
                slow_name,
                max_ms,
                max_ms,
            )

    def clock_output(self, enabled: bool = True) -> None:
        """
        Send MIDI timing clock to connected hardware.

        When enabled, Subsequence acts as a MIDI clock master and sends
        standard clock messages on the output port: a Start message (0xFA)
        when playback begins, a Clock tick (0xF8) on every pulse (24 PPQN),
        and a Stop message (0xFC) when playback ends.

        This allows hardware synthesizers, drum machines, and effect units to
        slave their tempo to Subsequence automatically.

        **Note:** Clock output is automatically disabled when ``midi_input()``
        is called with ``clock_follow=True``, to prevent a clock feedback loop.

        Parameters:
                enabled: Whether to send MIDI clock (default True).

        Example:
                ```python
                comp = subsequence.Composition(bpm=120, output_device="...")
                comp.clock_output()   # hardware will follow Subsequence tempo
                ```
        """

        self._clock_output = enabled

    def link(self, quantum: float = 4.0) -> "Composition":
        """
        Enable Ableton Link tempo and phase synchronisation.

        When enabled, Subsequence joins the local Link session and slaves its
        clock to the shared network tempo and beat phase.  All other Link-enabled
        apps on the same LAN — Ableton Live, iOS synths, other Subsequence
        instances — will automatically stay in time.

        Playback starts on the next bar boundary aligned to the Link quantum,
        so downbeats stay in sync across all participants.

        Requires the ``link`` optional extra::

            pip install subsequence[link]

        Parameters:
                quantum: Beat cycle length.  ``4.0`` (default) = one bar in 4/4 time.
                         Change this if your composition uses a different meter.

        Example::

            comp = subsequence.Composition(bpm=120, key="C")
            comp.link()          # join the Link session
            comp.play()

            # On another machine / instance:
            comp2 = subsequence.Composition(bpm=120)
            comp2.link()         # tempo and phase will lock to comp
            comp2.play()

        Note:
            ``set_bpm()`` proposes the new tempo to the Link network when Link
            is active.  The network-authoritative tempo is applied on the next
            pulse, so there may be a brief lag before the change is visible.
        """

        # Eagerly check that aalink is installed — fail early with a clear message.
        subsequence.link_clock._require_aalink()

        self._link_quantum = quantum
        return self

    def cc_map(
        self,
        cc: int,
        data_key: str,
        channel: typing.Optional[int] = None,
        min_val: float = 0.0,
        max_val: float = 1.0,
        input_device: subsequence.midi_utils.DeviceId = None,
    ) -> None:
        """
        Map an incoming MIDI CC to a ``composition.data`` key.

        When the composition receives a CC message on the configured MIDI
        input port, the value is scaled from the CC range (0–127) to
        *[min_val, max_val]* and stored in ``composition.data[data_key]``.

        This lets hardware knobs, faders, and expression pedals control live
        parameters without writing any callback code.

        **Requires** ``midi_input()`` to be called first to open an input port.

        Parameters:
                cc: MIDI Control Change number (0–127).
                data_key: The ``composition.data`` key to write.
                channel: If given, only respond to CC messages on this channel.
                        Uses the same numbering convention as ``pattern()`` (1-16
                        by default, or 0-15 with ``zero_indexed_channels=True``).
                        ``None`` matches any channel (default).
                min_val: Scaled minimum — written when CC value is 0 (default 0.0).
                max_val: Scaled maximum — written when CC value is 127 (default 1.0).
                input_device: Only respond to CC messages from this input device
                        (index or name).  ``None`` responds to any input device (default).

        Example:
                ```python
                comp.midi_input("Arturia KeyStep")
                comp.cc_map(74, "filter_cutoff")           # knob → 0.0–1.0
                comp.cc_map(7, "volume", min_val=0, max_val=127)  # volume fader

                # Multi-device: only listen to CC 74 from the "faders" controller
                comp.cc_map(74, "filter", input_device="faders")
                ```
        """

        resolved_channel = (
            self._resolve_channel(channel) if channel is not None else None
        )

        self._cc_mappings.append(
            {
                "cc": cc,
                "data_key": data_key,
                "channel": resolved_channel,
                "min_val": min_val,
                "max_val": max_val,
                "input_device": input_device,  # resolved to int index in _run()
            }
        )

    def note_input(
        self,
        channel: typing.Optional[int] = None,
        release_ms: float = 30.0,
        latch: bool = False,
        input_device: subsequence.midi_utils.DeviceId = None,
    ) -> None:
        """Track notes held on a MIDI keyboard for live arpeggiation.

        Incoming note-on/note-off messages build a live "currently held" set
        that any pattern reads via ``p.held_notes()`` — typically fed straight
        to ``p.arpeggio()``.  The composition still authors the rhythm and
        motion; the player's hands supply the pitch set.  This is a live
        *performance* layer over the deterministic, seeded composition: when
        rendering headlessly there is no input, so ``p.held_notes()`` is empty
        and seeded output is unchanged.

        **Requires** ``midi_input()`` to be called first to open an input port.

        Parameters:
                channel: If given, only track notes on this channel.  Uses the same
                        numbering convention as ``pattern()`` (1-16 by default, or 0-15
                        with ``zero_indexed_channels=True``).  ``None`` tracks any
                        channel (default).
                release_ms: How long (milliseconds) a released note keeps counting
                        as held.  This smooths the momentary all-keys-up gap during a
                        hand-position change so the arp does not drop to silence.
                        Default 30.0; set 0.0 to release instantly.  Ignored when
                        ``latch`` is True.
                latch: When True, the held set persists after you lift your hands
                        until you play a new chord (the first key after every key is up
                        replaces it) — like a hardware arp's latch.
                input_device: Only track notes from this input device (index or
                        name).  ``None`` tracks any input device (default).

        Example:
                ```python
                comp.midi_input("Arturia KeyStep")
                comp.note_input(channel=1, release_ms=30)

                @comp.pattern(channel=6, beats=4)
                def arp (p):
                    p.arpeggio(p.held_notes(), direction="up")  # rests when silent
                ```
        """

        if self._note_input is not None:
            raise RuntimeError(
                "only one note_input source is supported — named multi-source is not yet available"
            )

        resolved_channel = (
            self._resolve_channel(channel) if channel is not None else None
        )

        self._note_input = {
            "channel": resolved_channel,
            "release_ms": release_ms,
            "latch": latch,
            "input_device": input_device,  # resolved to int index in _run()
        }

    @staticmethod
    def _make_cc_forward_transform(
        output: typing.Union[str, typing.Callable],
        cc: int,
        output_channel: typing.Optional[int],
    ) -> typing.Callable:
        """Build a transform callable from a preset string or user-supplied callable.

        The returned callable has signature ``(value: int, channel: int) -> Optional[mido.Message]``
        where ``channel`` is the 0-indexed incoming channel.
        """

        import mido as _mido

        def _out_ch(incoming: int) -> int:
            return output_channel if output_channel is not None else incoming

        if callable(output):
            if output_channel is None:
                return output

            def _wrapped(value: int, channel: int) -> typing.Optional[typing.Any]:
                msg = output(value, channel)

                if msg is None:
                    return None

                # copy() re-channels without rebuilding: reconstructing from
                # __dict__ passed 'type' twice and raised TypeError on every
                # message, so callable+output_channel never forwarded anything.
                return msg.copy(channel=output_channel)

            return _wrapped

        if output == "cc":

            def _cc_identity(value: int, channel: int) -> typing.Any:
                return _mido.Message(
                    "control_change", channel=_out_ch(channel), control=cc, value=value
                )

            return _cc_identity

        if output.startswith("cc:"):
            try:
                target_cc = int(output[3:])
            except ValueError:
                raise ValueError(
                    f"cc_forward(): invalid preset '{output}' — expected 'cc:N' where N is 0–127"
                )
            if not 0 <= target_cc <= 127:
                raise ValueError(
                    f"cc_forward(): CC number {target_cc} out of range 0–127"
                )

            def _cc_remap(value: int, channel: int) -> typing.Any:
                return _mido.Message(
                    "control_change",
                    channel=_out_ch(channel),
                    control=target_cc,
                    value=value,
                )

            return _cc_remap

        if output == "pitchwheel":

            def _pitchwheel(value: int, channel: int) -> typing.Any:
                pitch = int(value / 127 * 16383) - 8192
                return _mido.Message(
                    "pitchwheel", channel=_out_ch(channel), pitch=pitch
                )

            return _pitchwheel

        raise ValueError(
            f"cc_forward(): unknown preset '{output}'. "
            "Use 'cc', 'cc:N' (e.g. 'cc:74'), 'pitchwheel', or a callable."
        )

    def cc_forward(
        self,
        cc: int,
        output: typing.Union[str, typing.Callable],
        *,
        channel: typing.Optional[int] = None,
        output_channel: typing.Optional[int] = None,
        mode: str = "instant",
        input_device: subsequence.midi_utils.DeviceId = None,
        output_device: subsequence.midi_utils.DeviceId = None,
    ) -> None:
        """
        Forward an incoming MIDI CC to the MIDI output in real-time.

        Unlike ``cc_map()`` which writes incoming CC values to ``composition.data``
        for use at pattern rebuild time, ``cc_forward()`` routes the signal
        directly to the MIDI output — bypassing the pattern cycle entirely.

        Both ``cc_map()`` and ``cc_forward()`` may be registered for the same CC
        number; they operate independently.

        Parameters:
                cc: Incoming CC number to listen for (0–127).
                output: What to send. Either a **preset string**:

                        - ``"cc"`` — identity forward, same CC number and value.
                        - ``"cc:N"`` — forward as CC number N (e.g. ``"cc:74"``).
                        - ``"pitchwheel"`` — scale 0–127 to -8192..8191 and send as pitch bend.

                        Or a **callable** with signature
                        ``(value: int, channel: int) -> Optional[mido.Message]``.
                        Return a fully formed ``mido.Message`` to send, or ``None`` to suppress.
                        ``channel`` is 0-indexed (the incoming channel).
                channel: If given, only respond to CC messages on this channel.
                        Uses the same numbering convention as ``cc_map()``.
                        ``None`` matches any channel (default).
                output_channel: Override the output channel. ``None`` uses the
                        incoming channel. Uses the same numbering convention as ``pattern()``.
                input_device: Only respond to CC from this input device — an index,
                        a registered name, or ``None`` for any input (default), the
                        same convention as ``cc_map()``.
                output_device: Send to this output device — an index, a registered
                        name, or ``None`` for the primary output (default).
                mode: Dispatch mode:

                        - ``"instant"`` *(default)* — send immediately on the MIDI input
                          callback thread. Lowest latency (~1–5 ms). Instant forwards are
                          **not** recorded when recording is enabled.
                        - ``"queued"`` — inject into the sequencer event queue and send at
                          the next pulse boundary (~0–20 ms at 120 BPM). Queued forwards
                          **are** recorded when recording is enabled.

        Example:
                ```python
                comp.midi_input("Arturia KeyStep")

                # CC 1 → CC 1 (identity, instant)
                comp.cc_forward(1, "cc")

                # CC 1 → pitch bend on channel 1, queued (recordable)
                comp.cc_forward(1, "pitchwheel", output_channel=1, mode="queued")

                # CC 1 → CC 74, custom channel
                comp.cc_forward(1, "cc:74", output_channel=2)

                # Custom transform — remap CC range 0–127 to CC 74 range 40–100
                import subsequence.midi as midi
                comp.cc_forward(1, lambda v, ch: midi.cc(74, int(v / 127 * 60) + 40, channel=ch))

                # Forward AND map to data simultaneously — both active on the same CC
                comp.cc_map(1, "mod_wheel")
                comp.cc_forward(1, "cc:74")
                ```
        """

        if not 0 <= cc <= 127:
            raise ValueError(f"cc_forward(): cc {cc} out of range 0–127")

        if mode not in ("instant", "queued"):
            raise ValueError(
                f"cc_forward(): mode must be 'instant' or 'queued', got '{mode}'"
            )

        resolved_in_channel = (
            self._resolve_channel(channel) if channel is not None else None
        )
        resolved_out_channel = (
            self._resolve_channel(output_channel)
            if output_channel is not None
            else None
        )

        transform = self._make_cc_forward_transform(output, cc, resolved_out_channel)

        self._cc_forwards.append(
            {
                "cc": cc,
                "channel": resolved_in_channel,
                "output_channel": resolved_out_channel,
                "mode": mode,
                "transform": transform,
                "input_device": input_device,  # resolved to int index in _run()
                "output_device": output_device,  # resolved to int index in _run()
            }
        )

    def live(self, port: int = 5555) -> None:
        """
        Enable the live coding eval server.

        This allows you to connect to a running composition using the
        ``subsequence.live_client`` REPL and hot-swap pattern code or
        modify variables in real-time.

        Security:
                The server executes arbitrary Python in this process — it is **not** a
                sandbox.  It binds to localhost only and is opt-in, but any process on
                the same machine that can reach the port gains full code execution here.
                Do not enable it on shared or multi-user hosts, and never expose the
                port to a network.

        Parameters:
                port: The TCP port to listen on (default 5555).
        """

        self._live_server = subsequence.live_server.LiveServer(self, port=port)
        self._is_live = True

    def watch(
        self, path: typing.Union[str, pathlib.Path], poll_interval: float = 0.25
    ) -> None:
        """Watch a Python file and reload it into the composition on every save.

        The watched file is exec'd into a namespace with ``composition`` and
        ``subsequence`` available.  ``@composition.pattern`` decorators inside
        the file hot-swap their corresponding running patterns in place;
        patterns whose function bodies have been deleted from the file are
        unregistered automatically on the next reload (notes stopped,
        removed from the running-pattern set).

        An **initial synchronous load** happens here — if the file has a
        ``SyntaxError`` or doesn't exist at this moment, the exception
        propagates so the user knows immediately.  Subsequent reloads
        happen on the composition's event loop and tolerate transient
        errors (logged, skipped).

        Call BEFORE ``composition.play()``.  Reloads happen on the
        composition's event loop, so all mutations are thread-safe.

        See the "Live coding via file watching" section of the README for
        the recommended wrapper-script + live-file split.

        Parameters:
                path: Path to the Python file to watch.
                poll_interval: Seconds between ``mtime`` polls (default 0.25 s).

        Example::

                # live_init.py — runs once
                composition = subsequence.Composition(bpm=120, key="E")
                composition.harmony(style="aeolian_minor")
                composition.watch("live_patterns.py")
                composition.play()
        """

        # Required for the decorator hot-swap path to fire on re-decoration.
        self._is_live = True

        # Detect the single-file workflow: if watch() is called from inside
        # the very file being watched, the outer Python script execution will
        # already register the patterns (the decorators sit at module level
        # below ``watch(__file__)``).  In that case, _load_initial's re-exec
        # would double-register every pattern, so skip it.  For the two-file
        # workflow (path != caller's __file__) the initial exec is essential
        # — it's the only way the watched file's patterns ever reach the
        # composition.
        caller_file = self._caller_module_file()
        self_watch = False
        if caller_file is not None:
            try:
                self_watch = (
                    pathlib.Path(caller_file).resolve() == pathlib.Path(path).resolve()
                )
            except OSError:
                self_watch = False

        self._live_reloader = subsequence.live_reloader.LiveReloader(
            composition=self,
            path=path,
            poll_interval=poll_interval,
            skip_initial_exec=self_watch,
        )
        self._live_reloader.start()

    @staticmethod
    def _caller_module_file() -> typing.Optional[str]:
        """Return ``__file__`` of the module that invoked the caller, if available.

        Walks one frame up the call stack — the immediate caller is
        ``watch()``, so ``f_back`` is the user's code.  Returns the
        module-level ``__file__`` of that frame's globals; ``None`` when
        the caller has no ``__file__`` (REPL, exec'd context, etc.).
        """

        frame = inspect.currentframe()
        if frame is None or frame.f_back is None or frame.f_back.f_back is None:
            return None
        # f_back = watch(); f_back.f_back = user code calling watch().
        return frame.f_back.f_back.f_globals.get("__file__")

    def load_patterns(
        self,
        source: str,
        source_label: str = "<string>",
    ) -> None:
        """Compile and apply a pattern-source string to the composition.

        Equivalent to one ``watch()`` reload triggered by save, but with the
        source presented in-memory rather than on disk.  Useful for web /
        REST handlers that accept pattern uploads from a trusted contributor,
        or for one-shot session loads with no file backing.

        Behaviour mirrors ``watch()``:

        * The source is exec'd into a fresh namespace with ``composition``
          and ``subsequence`` in scope.
        * ``@composition.pattern`` decorators in the source hot-swap their
          corresponding running patterns in place.
        * Patterns currently running but **not** declared in the source are
          unregistered — the source is treated as the full new truth.
        * If the composition is already playing, the swap happens on the
          event loop thread; the call blocks until it completes.
        * If the composition has not yet called ``play()``, the source runs
          on the caller's thread; decorators populate ``_pending_patterns``
          and ``play()`` picks them up in the usual way.

        Errors are raised so the caller can act on them:

        * ``SyntaxError`` if ``source`` fails to compile.
        * The exception raised inside ``exec()`` for any runtime error.
        * ``RuntimeError`` if called from inside the composition's own
          event loop thread (would deadlock — see Threading below).

        In either failure case, existing composition state is preserved —
        the diff-and-unregister phase is skipped if exec raised, so a
        half-broken upload cannot tear down working patterns.

        Threading:
                Designed to be called from a thread DIFFERENT from the
                composition's event loop — typically a web-handler worker.
                Cannot be called from inside the loop itself (a pattern
                callback, an asyncio task spawned by the composition).  From
                there, ``await composition._apply_source_async(...)`` directly.

        SECURITY WARNING: ``exec()`` is not sandboxed.  The source has full
        Python access in this process.  Only pass source from trusted
        senders.  The built-in blocklist (``help``, ``input``, ``breakpoint``,
        ``exit``, ``quit``) prevents calls that would stall the event loop;
        it is not a security boundary.

        Parameters:
                source:       Python source declaring ``@composition.pattern``
                        functions.
                source_label: Identifier used in compile errors and tracebacks
                        (appears as the filename in ``SyntaxError`` and ``__file__``-
                        style traceback lines).  Default ``"<string>"``.
        """

        # Required for the decorator hot-swap path to fire on re-decoration.
        self._is_live = True

        # Compile on the caller's thread so SyntaxError comes back fast,
        # before any cross-thread scheduling.
        compiled = compile(source, source_label, "exec")
        namespace = self._build_live_namespace(source_label=source_label)

        loop = self._sequencer._event_loop

        if loop is not None and loop.is_running():
            # Refuse to deadlock: calling load_patterns() from inside the
            # composition's own event loop (e.g. from a pattern callback or
            # an asyncio task spawned by the composition) would have us
            # block waiting for a coroutine that can only run when this
            # thread yields.  Tell the caller exactly what to do instead.
            try:
                current_loop: typing.Optional[asyncio.AbstractEventLoop] = (
                    asyncio.get_running_loop()
                )
            except RuntimeError:
                current_loop = None

            if current_loop is loop:
                raise RuntimeError(
                    "load_patterns() cannot be called from inside the composition's "
                    "event loop thread — it would deadlock waiting for the "
                    "scheduled coroutine to run on the very thread that's blocked. "
                    "From a worker thread, call it normally.  From an async "
                    "coroutine already on the loop, "
                    "`await composition._apply_source_async(compile(source, label, 'exec'), "
                    "composition._build_live_namespace())` instead."
                )

            # Composition is playing — mutation must happen on the loop thread.
            # future.result() blocks the caller until the coroutine finishes
            # and re-raises any exception it threw.
            future = asyncio.run_coroutine_threadsafe(
                self._apply_source_async(compiled, namespace, source_key=source_label),
                loop=loop,
            )
            future.result()

        else:
            # Pre-play: no event loop yet.  Decorators populate
            # _pending_patterns; play() graduates them in the usual way.
            # Diff-and-unregister is unnecessary here — nothing is running,
            # but RECORD what this source declares so a later post-play
            # reload under the same label can tear down its deletions.
            self._declared_names = set()
            exec(compiled, namespace)
            self._source_declared[source_label] = set(self._declared_names)

    async def _apply_source_async(
        self,
        compiled: types.CodeType,
        namespace: typing.Dict[str, typing.Any],
        source_key: str = "<live>",
    ) -> None:
        """Execute pre-compiled live source against the running composition.

        Runs on the event loop thread.  Performs ``exec()``, graduates any
        newly-decorated patterns into ``_running_patterns``, then unregisters
        any patterns that *this source* declared on its previous exec but no
        longer declares (keyed by ``source_key`` — a watched file's path or a
        ``load_patterns`` label).  Patterns registered by the wrapper script
        or by another source are never this source's to tear down.

        Raises whatever ``exec()`` raises.  When that happens, the diff-and-
        unregister phase is skipped — the namespace is incomplete, so any
        patterns the source failed to reach would be misinterpreted as
        deletions and torn down.

        Called from two places:

        * ``Composition.load_patterns()`` via ``run_coroutine_threadsafe``.
        * ``LiveReloader._reload_async`` directly (already on the loop).
        """

        # Track which patterns the source declares this exec.  pattern() and
        # layer() add their (resolved) names to _declared_names as they run, so
        # this covers decorated patterns AND layer()/merged patterns — the latter
        # have no module-level callable to match against by name, which is why the
        # old namespace-based diff tore layers down on every reload.
        self._declared_names = set()

        # Bail before any state mutation if exec raises — propagates to
        # the caller (load_patterns re-raises; LiveReloader catches + logs).
        exec(compiled, namespace)

        # Graduate newly-decorated patterns from _pending_patterns into
        # _running_patterns so they start firing on the next reschedule.
        # Patterns that hot-swapped via the decorator/layer path don't appear
        # in _pending_patterns and don't need this step.
        await self._activate_new_pending_patterns()

        # Detect deletions: a name THIS source declared last time but not this
        # time has been removed by the user and should be torn down.  (An
        # unknown source — first exec — tears down nothing: patterns running
        # from the wrapper script or another source are not ours to remove.)
        # Decorators/layer() do NOT remove from _running_patterns when a
        # definition disappears from the source.
        previous = self._source_declared.get(source_key)

        if previous is not None:
            for name in previous - self._declared_names:
                if name in self._running_patterns:
                    self.unregister(name)

        self._source_declared[source_key] = set(self._declared_names)

    def _build_live_namespace(
        self, source_label: str = "<live>"
    ) -> typing.Dict[str, typing.Any]:
        """Build a fresh namespace dict for exec'ing live source.

        Provides ``composition`` (this Composition), ``subsequence`` (the
        package), and a safe builtins set with ``help``, ``input``,
        ``breakpoint``, ``exit``, ``quit`` blocked.

        Also injects two dunder globals that make the single-file live-coding
        workflow ergonomic:

        * ``__name__ = "__live_reload__"`` — so ``if __name__ == "__main__":``
          blocks in the watched file are *skipped* during live reload.  The
          same file run directly with ``python my_session.py`` sees
          ``__name__ == "__main__"`` and runs setup; saves trigger reload
          with ``__name__ == "__live_reload__"``, skipping setup and only
          re-running pattern definitions.
        * ``__file__ = source_label`` — so ``composition.watch(__file__)``
          and any user code referencing ``__file__`` works inside the live
          namespace.  Set to the file path for ``LiveReloader``, the
          user-supplied ``source_label`` for ``Composition.load_patterns``,
          and ``"<live>"`` for ``LiveServer``.

        Single source of truth: ``live_reloader`` (file watching),
        ``live_server`` (TCP REPL), and ``load_patterns`` (string source)
        all call this so live source sees the same environment from any
        entry point.

        The blocklist prevents calls that would stall the async event loop
        running the sequencer.  It is **not** a security sandbox — exec'd
        code can still do anything Python allows.

        Parameters:
                source_label: Value to bind to ``__file__`` in the namespace.
                        Defaults to ``"<live>"``.
        """

        import subsequence  # local import: this module is imported during subsequence init

        safe_builtins = {name: getattr(builtins, name) for name in dir(builtins)}

        blocked = {"help", "input", "breakpoint", "exit", "quit"}

        for name in blocked:
            safe_builtins[name] = _live_blocked(name)

        return {
            "__builtins__": safe_builtins,
            "__name__": "__live_reload__",
            "__file__": source_label,
            "composition": self,
            "subsequence": subsequence,
        }

    def osc(
        self,
        receive_port: int = 9000,
        send_port: int = 9001,
        send_host: str = "127.0.0.1",
        receive_host: str = "0.0.0.0",
    ) -> None:
        """
        Enable bi-directional Open Sound Control (OSC).

        Subsequence will listen for commands (like ``/bpm`` or ``/mute``) and
        broadcast its internal state (like ``/chord`` or ``/bar``) over UDP.

        Parameters:
                receive_port: Port to listen for incoming OSC messages (default 9000).
                send_port: Port to send state updates to (default 9001).
                send_host: The IP address to send updates to (default "127.0.0.1").
                receive_host: Interface to listen on (default "0.0.0.0" — all
                        interfaces, so external OSC controllers on the LAN can reach it).
                        The listener can change tempo, mute patterns, and write data, so on
                        an untrusted network restrict it with ``receive_host="127.0.0.1"``.
        """

        self._osc_server = subsequence.osc.OscServer(
            self,
            receive_port=receive_port,
            send_port=send_port,
            send_host=send_host,
            receive_host=receive_host,
        )

    def osc_map(self, address: str, handler: typing.Callable) -> None:
        """
        Register a custom OSC handler.

        Must be called after :meth:`osc` has been configured.

        Parameters:
                address: OSC address pattern to match (e.g. ``"/my/param"``).
                handler: Callable invoked with ``(address, *args)`` when a
                        matching message arrives.

        Example::

                composition.osc()

                def on_intensity (address, value):
                        composition.data["intensity"] = float(value)

                composition.osc_map("/intensity", on_intensity)
        """

        if self._osc_server is None:
            raise RuntimeError("Call composition.osc() before composition.osc_map()")

        self._osc_server.map(address, handler)

    def set_bpm(self, bpm: float) -> None:
        """
        Instantly change the tempo.

        Parameters:
                bpm: The new tempo in beats per minute.

        When Ableton Link is active, this proposes the new tempo to the Link
        network instead of applying it locally.  The network-authoritative tempo
        is picked up on the next pulse.
        """

        self._sequencer.set_bpm(bpm)

        if not self.is_clock_following and self._link_quantum is None:
            self.bpm = bpm

    def target_bpm(self, bpm: float, bars: int, shape: str = "linear") -> None:
        """
        Smoothly ramp the tempo to a target value over a number of bars.

        Parameters:
                bpm: Target tempo in beats per minute.
                bars: Duration of the transition in bars.
                shape: Easing curve name.  Defaults to ``"linear"``.
                       ``"ease_in_out"`` or ``"s_curve"`` are recommended for natural-
                       sounding tempo changes.  See :mod:`subsequence.easing` for all
                       available shapes.

        Example:
                ```python
                # Accelerate to 140 BPM over the next 8 bars with a smooth S-curve
                comp.target_bpm(140, bars=8, shape="ease_in_out")
                ```

        Note:
                Ignored while Ableton Link is active — the shared session tempo is
                authoritative.  Use ``set_bpm()`` to propose a tempo to the Link network.
        """

        self._sequencer.set_target_bpm(bpm, bars, shape)

    def live_info(self) -> typing.Dict[str, typing.Any]:
        """
        Return a dictionary containing the current state of the composition.

        Includes BPM, key, current bar, active section, current chord,
        running patterns, and custom data.
        """

        section_info = None
        if self._form_state is not None:
            section = self._form_state.get_section_info()
            if section is not None:
                section_info = {
                    "name": section.name,
                    "bar": section.bar,
                    "bars": section.bars,
                    "progress": section.progress,
                }

        chord_name = None
        sounding_chord = self.current_chord()
        if sounding_chord is not None:
            chord_name = sounding_chord.name()

        pattern_list = []
        channel_offset = 0 if self._zero_indexed_channels else 1
        for name, pat in self._running_patterns.items():
            pattern_list.append(
                {
                    "name": name,
                    "channel": pat.channel + channel_offset,
                    "length": pat.length,
                    "cycle": pat._cycle_count,
                    "muted": pat._muted,
                    "tweaks": dict(pat._tweaks),
                }
            )

        return {
            "bpm": self._sequencer.current_bpm,
            "key": self.key,
            "bar": self._builder_bar,
            "section": section_info,
            "chord": chord_name,
            "patterns": pattern_list,
            "input_device": self._input_device,
            "clock_follow": self.is_clock_following,
            "data": self.data,
        }

    def mute(self, name: str) -> None:
        """
        Mute a running pattern by name.

        The pattern continues to 'run' and increment its cycle count in
        the background, but it will not produce any MIDI notes until unmuted.

        Parameters:
                name: The function name of the pattern to mute.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        # The performer takes ownership: if a transition's approach window had
        # muted this pattern, drop it from that set so the section boundary
        # does not silently unmute it ("performer mutes win").
        self._transition_muted.discard(name)

        self._running_patterns[name]._muted = True
        logger.info(f"Muted pattern: {name}")

    def unmute(self, name: str) -> None:
        """
        Unmute a previously muted pattern.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        # Symmetric ownership claim: an explicit unmute means the transition
        # machinery should no longer manage this pattern at the boundary.
        self._transition_muted.discard(name)

        self._running_patterns[name]._muted = False
        logger.info(f"Unmuted pattern: {name}")

    def unregister(self, name: str) -> None:
        """Fully remove a running pattern from rotation.

        Unlike ``mute()`` (which keeps the pattern alive but silent),
        ``unregister()`` tears the pattern down entirely.  It sets
        ``pattern._removed = True`` so the sequencer's reschedule loop
        skips re-adding it on the next pulse; sends ``note_off`` for any
        of the pattern's currently-sounding notes on the primary
        destination AND on every mirror destination (so drones and
        sustaining notes stop immediately); and removes the entry from
        ``_running_patterns`` so it no longer appears in ``live_info()``,
        the terminal grid, or any other consumer that enumerates running
        patterns.

        Already-queued events in the sequencer's event queue play out —
        note_offs are paired with their note_ons at queue time, so notes
        end at their natural duration; only drones rely on the targeted
        ``_stop_pattern_notes`` pass.

        Idempotent: silently logs a ``debug`` and returns if the pattern
        is already absent.  Useful from both the live REPL
        (``composition.live()``) and the file watcher
        (``composition.watch()``), which calls this for any pattern
        removed from the watched file between reloads.

        Parameters:
                name: Function name of the pattern to remove.
        """

        if name not in self._running_patterns:
            logger.debug(f"unregister() no-op: pattern '{name}' not running")
            return

        pattern = self._running_patterns[name]

        # Mark for removal first so the reschedule loop sees the flag even if
        # it fires concurrently with the note-off pass below.
        pattern._removed = True

        # Stop sustaining notes (including drones) on every destination this
        # pattern outputs to.  Fire-and-forget across threads via the event
        # loop; ``_stop_pattern_notes`` acquires the queue lock internally.
        if self._sequencer._event_loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._sequencer._stop_pattern_notes(pattern),
                loop=self._sequencer._event_loop,
            )

        def _finalise_removal() -> None:
            self._running_patterns.pop(name, None)

            # Forget any pending (not-yet-graduated) declaration too, so a
            # later live reload cannot resurrect the pattern.
            self._pending_patterns = [
                pending
                for pending in self._pending_patterns
                if pending.builder_fn.__name__ != name
            ]

            logger.info(f"Unregistered pattern: {name}")

        # The running-patterns dict is iterated by the display, web UI, and
        # reschedule loop on the event loop thread — mutate it there when this
        # call arrives from another thread (e.g. the live TCP server).
        loop = self._sequencer._event_loop

        try:
            on_loop = loop is not None and asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False

        if loop is not None and loop.is_running() and not on_loop:
            loop.call_soon_threadsafe(_finalise_removal)
        else:
            _finalise_removal()

    def mirror(
        self,
        name: str,
        device: int,
        channel: int,
        drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
    ) -> None:
        """
        Add a mirror destination to a running pattern.

        Every note, CC, pitch bend, NRPN/RPN, program change, SysEx, and drone
        event the pattern emits will also be sent to ``(device, channel)``,
        starting from the next cycle rebuild.  Idempotent on ``(device, channel)``
        — calling with the same destination twice does not double-fan; calling
        again with a different ``drum_note_map`` re-points it in place.

        Parameters:
                name: Function name of the pattern to mirror.
                device: Output device index (the integer returned from
                        ``midi_output()``; 0 = primary device).
                channel: MIDI channel using this composition's numbering convention
                        (1-16 by default; 0-15 if ``zero_indexed_channels=True``).
                drum_note_map: Optional per-destination drum map.  When set, mirrored
                        drum hits are re-resolved by name through it, so a named voice
                        lands on this device's own note number — see the README
                        "MIDI mirroring" section.

        Bandwidth: each mirror adds another full copy of the pattern's events.
        See the README "MIDI mirroring" section for the tradeoffs.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        resolved_channel = self._resolve_channel(channel)
        prefix = (device, resolved_channel)
        entry: subsequence.pattern.MirrorSpec = (
            prefix
            if drum_note_map is None
            else (device, resolved_channel, drum_note_map)
        )

        pattern = self._running_patterns[name]

        # Mirror-to-self check: comparing the (device, channel) prefix against the
        # live pattern's resolved destination.  Unlike the decorator path this is
        # always concrete.
        if prefix == (pattern.device, pattern.channel):
            logger.warning(
                f"Mirror destination {prefix} matches '{name}'s primary destination "
                f"— every event will double-fire on this (device, channel).  This is almost "
                f"certainly unintended."
            )

        # Idempotent on (device, channel): replace any existing entry for the same
        # destination (so its map can be re-pointed), else append.
        existing_index = next(
            (idx for idx, e in enumerate(pattern.mirrors) if (e[0], e[1]) == prefix),
            None,
        )
        if existing_index is None:
            pattern.mirrors.append(entry)
            logger.info(
                f"Mirror added: {name} -> device={device}, channel={resolved_channel}"
            )
        elif pattern.mirrors[existing_index] != entry:
            pattern.mirrors[existing_index] = entry
            logger.info(
                f"Mirror updated: {name} -> device={device}, channel={resolved_channel}"
            )
        else:
            logger.debug(
                f"Mirror already present on {name}: device={device}, channel={resolved_channel}"
            )

    def unmirror(self, name: str, device: int, channel: int) -> None:
        """
        Remove a single mirror destination from a running pattern.

        Matches on ``(device, channel)`` only — any attached ``drum_note_map`` is
        ignored.  Idempotent: silently does nothing if the destination is not
        currently mirrored.  The change applies on the next cycle rebuild.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        resolved_channel = self._resolve_channel(channel)
        prefix = (device, resolved_channel)

        pattern = self._running_patterns[name]

        filtered = [e for e in pattern.mirrors if (e[0], e[1]) != prefix]
        if len(filtered) != len(pattern.mirrors):
            pattern.mirrors[:] = filtered
            logger.info(
                f"Mirror removed: {name} -> device={device}, channel={resolved_channel}"
            )
        else:
            logger.debug(
                f"unmirror() no-op on {name}: device={device}, channel={resolved_channel} not in mirrors"
            )

    def unmirror_all(self, name: str) -> None:
        """
        Remove every mirror destination from a running pattern.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        pattern = self._running_patterns[name]

        if pattern.mirrors:
            pattern.mirrors.clear()
            logger.info(f"All mirrors cleared on pattern: {name}")

    def tweak(self, name: str, **kwargs: typing.Any) -> None:
        """Override parameters for a running pattern.

        Values set here are available inside the pattern's builder
        function via ``p.param()``.  They persist across rebuilds
        until explicitly changed or cleared.  Changes take effect
        on the next rebuild cycle.

        Parameters:
                name: The function name of the pattern.
                ``**kwargs``: Parameter names and their new values.

        Example (from the live REPL)::

                composition.tweak("bass", pitches=[48, 52, 55, 60])
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        self._running_patterns[name]._tweaks.update(kwargs)
        logger.info(f"Tweaked pattern '{name}': {list(kwargs.keys())}")

    def clear_tweak(self, name: str, *param_names: str) -> None:
        """Remove tweaked parameters from a running pattern.

        If no parameter names are given, all tweaks for the pattern
        are cleared and every ``p.param()`` call reverts to its
        default.

        Parameters:
                name: The function name of the pattern.
                *param_names: Specific parameter names to clear.  If
                        omitted, all tweaks are removed.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        if not param_names:
            self._running_patterns[name]._tweaks.clear()
            logger.info(f"Cleared all tweaks for pattern '{name}'")
        else:
            for param_name in param_names:
                self._running_patterns[name]._tweaks.pop(param_name, None)
            logger.info(f"Cleared tweaks for pattern '{name}': {list(param_names)}")

    def get_tweaks(self, name: str) -> typing.Dict[str, typing.Any]:
        """Return a copy of the current tweaks for a running pattern.

        Parameters:
                name: The function name of the pattern.
        """

        if name not in self._running_patterns:
            raise ValueError(
                f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}"
            )

        return dict(self._running_patterns[name]._tweaks)

    def schedule(
        self,
        fn: typing.Callable,
        cycle_beats: int,
        reschedule_lookahead: int = 1,
        wait_for_initial: bool = False,
        defer: bool = False,
    ) -> None:
        """
        Register a custom function to run on a repeating beat-based cycle.

        Subsequence automatically runs synchronous functions in a thread pool
        so they don't block the timing-critical MIDI clock. Async functions
        are run directly on the event loop.

        Parameters:
                fn: The function to call.
                cycle_beats: How often to call it (e.g., 4 = every bar).
                reschedule_lookahead: How far in advance to schedule the next call.
                wait_for_initial: If True, run the function once during startup
                        and wait for it to complete before playback begins. This
                        ensures ``composition.data`` is populated before patterns
                        first build. Implies ``defer=True`` for the repeating
                        schedule.
                defer: If True, skip the pulse-0 fire and defer the first
                        repeating call to just before the second cycle boundary.

        Raises:
                RuntimeError: If called after ``play()`` has started — scheduled
                        tasks register at startup, so a late registration would be
                        silently ignored otherwise.
        """

        if self._sequencer.running:
            raise RuntimeError(
                "schedule() must be called before play() - scheduled tasks register at startup"
            )

        self._pending_scheduled.append(
            _PendingScheduled(
                fn, cycle_beats, reschedule_lookahead, wait_for_initial, defer
            )
        )

    def form(
        self,
        sections: typing.Union[
            "subsequence.forms.Form",
            typing.List[typing.Any],
            typing.Iterator[typing.Tuple[str, int]],
            typing.Dict[
                str,
                typing.Tuple[int, typing.Optional[typing.List[typing.Tuple[str, int]]]],
            ],
        ],
        loop: bool = False,
        start: typing.Optional[str] = None,
        at_end: str = "stop",
        key: typing.Optional[str] = None,
        scale: typing.Optional[str] = None,
    ) -> None:
        """
        Define the structure (sections) of the composition.

        You can define form in four ways:

        1. **Form value**: a frozen :class:`~subsequence.forms.Form` of
           :class:`~subsequence.forms.Section` values — the payload home
           (energy, key per section); editable, navigable.
        2. **Sequence (List)**: a fixed order of ``(name, bars)`` tuples
           or Sections (lists coerce — they are the same form).
        3. **Graph (Dict)**: dynamic transitions based on weights.
        4. **Generator**: a Python generator that yields ``(name, bars)`` pairs.

        Form-value and list forms are **navigable**: ``form_jump()`` and
        ``form_next()`` work on them (the jump lands on the next occurrence
        of the name, wrapping).

        Re-binding ``form()`` during playback takes effect at the next bar —
        the clock reads the current form state on every bar, so the new form
        advances from there (its first section plays from its first bar).

        Parameters:
                sections: The form definition (Form, List, Dict, or Generator).
                loop: Sugar for ``at_end="loop"``.
                start: The section to start with (Graph mode only).
                at_end: What happens when a sequence form runs out —
                        ``"stop"`` (the form finishes and patterns see no section;
                        default), ``"hold"`` (the final section repeats until
                        navigated away from), or ``"loop"`` (start over).  Graphs
                        end via their terminal sections instead.
                key: A form-level key — the **form tier** of the key-source
                        chain (``Section.key`` overrides it; it overrides the
                        composition key).  Re-anchors key-relative content for the
                        whole form.  When *sections* is a ``Form`` value carrying its
                        own ``key``, that value is used unless this argument overrides.
                scale: A form-level scale/mode, paired with ``key``.

        Example:
                ```python
                # A simple pop structure
                comp.form([
                        ("verse", 8),
                        ("chorus", 8),
                        ("verse", 8),
                        ("chorus", 16)
                ])

                # The same structure with payloads, held open at the end
                S = subsequence.Section
                comp.form(subsequence.Form([
                        S("verse", 8, energy=0.5), S("chorus", 8, energy=0.9),
                ]), at_end="hold")
                ```
        """

        # Seed FormState at form() time (per-call salt) so build-time walks —
        # the frozen clones form_freeze will take — are deterministic without
        # play(); the play-time stream is re-dealt name-keyed in _run().
        self._form_count += 1

        self._form_state = subsequence.form_state.FormState(
            sections,
            loop=loop,
            start=start,
            rng=self._stream(f"form:{self._form_count}"),
            at_end=at_end,
        )

        # A Form value carries energy payloads — that counts as an energy
        # source for the min_energy registration check in _run().
        self._form_has_payload = isinstance(sections, subsequence.forms.Form) or (
            isinstance(sections, list)
            and any(
                isinstance(element, subsequence.forms.Section) for element in sections
            )
        )

        # Form-tier key/scale: an explicit argument wins; otherwise a Form
        # value's own key/scale seeds the tier.  Re-binding the form drops any
        # stale per-section resolution cache.
        if isinstance(sections, subsequence.forms.Form):
            self._form_key = key if key is not None else sections.key
            self._form_scale = scale if scale is not None else sections.scale
        else:
            self._form_key = key
            self._form_scale = scale

        self._resolved_section_cache = {}

    def form_freeze(
        self, sections: typing.Optional[int] = None
    ) -> "subsequence.forms.Form":
        """Freeze the graph form's walk into an editable :class:`~subsequence.forms.Form`.

        Walks a **clone** of the live form state — the same RNG state, so the
        frozen path is exactly the path the live graph would have played —
        and returns it as a Form value: inspect it, edit it
        (``path.replace(3, bars=16)``), and rebind it with
        ``composition.form(path, at_end=...)``.  The live form state is
        untouched (rebinding replaces it).

        Parameters:
                sections: Number of sections to freeze.  Without it, the walk
                        runs until a terminal section; a graph with no terminal
                        sections requires ``sections=`` explicitly.

        Raises:
                ValueError: If no graph form is bound (a list form is already a
                        frozen sequence), the form has already finished, or the walk
                        cannot terminate.

        Example::

                composition.form({...}, start="intro")
                path = composition.form_freeze()          # the walk, frozen
                composition.form(path, at_end="stop")     # rebind the editable value
        """

        fs = self._form_state

        if fs is None or fs._graph is None or fs._section_bars is None:
            raise ValueError(
                "form_freeze() freezes a graph form's walk — call form() with a dict first "
                "(a list form is already a frozen sequence)"
            )

        if fs._current is None:
            raise ValueError("the form has already finished — nothing left to freeze")

        if sections is not None and sections < 1:
            raise ValueError("sections must be at least 1")

        if sections is None and not fs._terminal_sections:
            raise ValueError(
                "this graph has no terminal section, so the walk would never end — "
                "pass sections=n to bound it"
            )

        # Clone the RNG state: the frozen walk reproduces the live form's
        # future draws without consuming them.
        rng = random.Random()
        rng.setstate(fs._rng.getstate())

        walked = [fs._current]
        next_name = fs._next_section_name  # already decided by the live state

        while next_name is not None:
            if sections is not None and len(walked) >= sections:
                break
            if sections is None and len(walked) >= 10000:
                raise ValueError(
                    "form_freeze() walked 10000 sections without reaching a terminal — "
                    "the terminals look unreachable; pass sections=n to bound the walk"
                )

            walked.append(
                subsequence.forms.Section(
                    name=next_name, bars=fs._section_bars[next_name]
                )
            )
            next_name = (
                None
                if next_name in fs._terminal_sections
                else fs._graph.choose_next(next_name, rng)
            )

        # Carry the form-tier key/scale onto the frozen value so a freeze →
        # rebind round-trip is lossless (an explicit form(key=) on rebind
        # still overrides).
        return subsequence.forms.Form(
            walked, key=self._form_key, scale=self._form_scale
        )

    def energy(
        self,
        energies: typing.Dict[str, typing.Union[float, typing.Tuple[float, float]]],
    ) -> None:
        """Set per-section energy — the arranging dial, as one plain dict.

        ``{"verse": 0.5, "chorus": 0.9, "build": (0.3, 1.0)}`` — a float is
        the section's level; a ``(start, end)`` tuple interpolates across the
        section (a build).  Patterns read ``p.energy`` (0.5 when nothing is
        configured) and gate themselves, or declare ``min_energy=`` on
        ``pattern()`` for automatic muting.

        The dict **overrides** any energy payload carried by bound
        :class:`~subsequence.forms.Section` values — it is the later,
        performance-level dial.  Re-calling replaces the whole mapping
        (idempotent, live-reload friendly).

        Example::

                composition.energy({"intro": 0.2, "verse": 0.55, "drop": 0.95})
        """

        validated: typing.Dict[
            str, typing.Union[float, typing.Tuple[float, float]]
        ] = {}

        for name, value in energies.items():
            if isinstance(value, tuple):
                if len(value) != 2:
                    raise ValueError(
                        f"energy ramp for {name!r} must be (start, end), got {value!r}"
                    )
                start_level, end_level = float(value[0]), float(value[1])
                for level in (start_level, end_level):
                    if not 0.0 <= level <= 1.0:
                        raise ValueError(
                            f"energy for {name!r} must be 0.0–1.0, got {value!r}"
                        )
                validated[name] = (start_level, end_level)
            else:
                level = float(value)
                if not 0.0 <= level <= 1.0:
                    raise ValueError(
                        f"energy for {name!r} must be 0.0–1.0, got {value!r}"
                    )
                validated[name] = level

        self._energy_map = validated

    def _current_energy(
        self, info: typing.Optional[subsequence.form_state.SectionInfo]
    ) -> float:
        """Resolve the energy for a section snapshot.

        Priority: the ``energy()`` dict (ramps interpolate by section
        progress) > the bound Section payload > 0.5.
        """

        if info is None:
            return 0.5

        spec = self._energy_map.get(info.name)

        if spec is None:
            return info.energy

        if isinstance(spec, tuple):
            start_level, end_level = spec

            # A build reaches its declared end ON the final bar, so the ramp spans
            # bar 0 → bar (bars-1).  (info.progress is bar/bars, which would top
            # out one bar short and never deliver end.)  A one-bar section sits at
            # the destination level.
            span = info.bars - 1
            fraction = info.bar / span if span > 0 else 1.0

            return start_level + (end_level - start_level) * fraction

        return spec

    def on_section(self, callback: typing.Callable[..., typing.Any]) -> None:
        """Register a callback fired on every section change.

        The callback receives the new :class:`~subsequence.form_state.SectionInfo`
        (or ``None`` when the form finishes).  It fires from the form clock,
        one lookahead-beat **early** — in time to affect the new section's
        first patterns — and once at play start for the opening section.

        Example::

                composition.on_section(lambda info: print(f"now: {info.name if info else 'end'}"))
        """

        self.on_event("section", callback)

    def transition(
        self,
        before: str,
        fill: typing.Optional[typing.Any] = None,
        channel: typing.Optional[int] = None,
        beat: float = 0.0,
        mute: typing.Optional[typing.List[str]] = None,
        beats: typing.Optional[float] = None,
        drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
        device: subsequence.midi_utils.DeviceId = None,
    ) -> None:
        """Declare boundary material — the automatic fill or mute, one line.

        ``before`` names the incoming section (``"chorus"``), or ``"*"`` for
        any *different* section (repeats don't fire it).  Two actions,
        combinable:

        - ``fill=`` (+ ``channel=``, ``beat=``): a Motif played in the last
          bar before the boundary, starting at ``beat`` of that bar.  Drum
          names resolve through ``drum_note_map=`` if given, otherwise the
          map is borrowed from a registered pattern on the same channel.
        - ``mute=`` (+ ``beats=``): pattern names muted over the approach
          and unmuted at the boundary.  Muting is **bar-granular** (the
          existing rule), so ``beats`` rounds up to whole bars.  Performer
          mutes win: a pattern you muted yourself stays muted.

        Transitions stack — call once per rule.  Registration is additive
        and idempotent per identical rule.

        Example::

                composition.transition(before="*", fill=FILL, channel=10, beat=2.0)
                composition.transition(before="drop", mute=["pads"], beats=4)
        """

        if fill is None and mute is None:
            raise ValueError(
                "transition() needs fill= and/or mute= — it declares what happens at the boundary"
            )

        if fill is not None:
            if channel is None:
                raise ValueError(
                    "transition(fill=) needs channel= — the fill must land somewhere"
                )
            if not hasattr(fill, "events") or not hasattr(fill, "length"):
                raise TypeError(
                    f"fill must be a Motif-like value with .events/.length, got {type(fill).__name__}"
                )

        if mute is not None and beats is None:
            beats = float(self.time_signature[0])  # one bar by default

        rule = _Transition(
            before=before,
            fill=fill,
            channel=self._resolve_channel(channel) if channel is not None else None,
            beat=float(beat),
            mute=list(mute) if mute is not None else None,
            beats=beats,
            drum_note_map=drum_note_map,
            device=device,  # resolved at fire time — names aren't known until play()
        )

        if rule not in self._transitions:
            self._transitions.append(rule)

    def _transition_drum_map(
        self, channel: typing.Optional[int]
    ) -> typing.Optional[typing.Dict[str, int]]:
        """Borrow a drum map from a registered pattern on the same channel."""

        if channel is None:
            return None

        for pending in self._pending_patterns:
            if pending.channel == channel and pending.drum_note_map:
                return pending.drum_note_map

        for running in self._running_patterns.values():
            candidate = getattr(running, "_drum_note_map", None)
            if running.channel == channel and candidate:
                return typing.cast(typing.Dict[str, int], candidate)

        return None

    def _fire_fill(self, rule: _Transition, start_pulse: int) -> None:
        """Build a transition fill as a one-shot pattern and schedule it."""

        assert rule.fill is not None and rule.channel is not None

        drum_map = (
            rule.drum_note_map
            if rule.drum_note_map is not None
            else self._transition_drum_map(rule.channel)
        )

        pattern = subsequence.pattern.Pattern(
            channel=rule.channel,
            length=float(rule.fill.length),
            device=self._resolve_device_id(rule.device),
        )

        harmony_view: typing.Optional[HarmonyView] = None
        if not self._harmony_horizon.is_empty:
            harmony_view = HarmonyView(
                self._harmony_horizon, start_pulse / self._sequencer.pulses_per_beat
            )

        # The fill sounds in the outgoing section's final bar, so a degree-
        # bearing fill resolves against THAT section's effective key/scale —
        # previously it took the composition key, ignoring the section.
        fill_section = self._form_state.get_section_info() if self._form_state else None
        fill_key, fill_scale = self._effective_key_scale(fill_section)

        builder = subsequence.pattern_builder.PatternBuilder(
            pattern=pattern,
            cycle=0,
            drum_note_map=drum_map,
            section=fill_section,
            bar=self._builder_bar,
            conductor=self.conductor,
            rng=self._stream(f"transition:{rule.before}:{start_pulse}")
            or random.Random(),
            tweaks={},
            default_grid=16,
            data=self.data,
            key=fill_key,
            scale=fill_scale,
            time_signature=self.time_signature,
            harmony=harmony_view,
        )

        try:
            builder.motif(rule.fill)
        except Exception:
            logger.exception(
                "transition fill failed to build — the boundary plays without it"
            )
            return

        self._schedule_one_shot(pattern, start_pulse)

    def _check_transitions(self, boundary_pulse: int, section_changed: bool) -> None:
        """The form clock's boundary hook: fire fills, manage approach mutes.

        Called once per bar (lookahead-early, with the bar-line pulse).
        Fill rules fire when the current bar is the section's last before a
        matching boundary; mute rules close over the approach window
        (rounded up to whole bars — muting is bar-granular) and reopen at
        the boundary.  Performer mutes are never touched.
        """

        if section_changed and self._transition_muted:
            # The boundary arrived — restore only what we muted ourselves.
            for name in self._transition_muted:
                running = self._running_patterns.get(name)
                if running is not None:
                    running._muted = False
            self._transition_muted.clear()

        if not self._transitions or self._form_state is None:
            return

        info = self._form_state.get_section_info()

        if info is None or info.next_section is None:
            return

        bar_beats = float(self.time_signature[0])
        bars_remaining = info.bars - info.bar

        for rule in self._transitions:
            if rule.before == "*":
                if info.next_section == info.name:
                    continue  # a repeat is not a boundary
            elif info.next_section != rule.before:
                continue

            if rule.fill is not None and bars_remaining == 1:
                self._fire_fill(
                    rule,
                    boundary_pulse
                    + int(round(rule.beat * self._sequencer.pulses_per_beat)),
                )

            if rule.mute:
                window_beats = rule.beats if rule.beats is not None else bar_beats
                window_bars = max(
                    1, int((window_beats + bar_beats - 1e-9) // bar_beats)
                )

                if bars_remaining <= window_bars:
                    for name in rule.mute:
                        running = self._running_patterns.get(name)
                        if running is None or name in self._transition_muted:
                            continue
                        if running._muted:
                            continue  # the performer's mute — not ours to manage
                        running._muted = True
                        self._transition_muted.add(name)

    @staticmethod
    def _resolve_length(
        beats: typing.Optional[float],
        bars: typing.Optional[float],
        steps: typing.Optional[float],
        step_duration: typing.Optional[float],
        default: float = 4.0,
        beats_per_bar: int = 4,
    ) -> typing.Tuple[float, int]:
        """
        Resolve the beat_length and default_grid from the duration parameters.

        Two modes:

        - **Duration mode** (no ``step_duration``): specify ``beats=`` or ``bars=``.
          ``beats=4`` = 4 quarter notes; ``bars=2`` = 8 beats.
        - **Step mode** (with ``step_duration``): specify ``steps=`` and ``step_duration=``.
          ``steps=6, step_duration=dur.SIXTEENTH`` = 6 sixteenth notes = 1.5 beats.

        Constraints:

        - ``beats`` and ``bars`` are mutually exclusive.
        - ``steps`` requires ``step_duration``; ``step_duration`` requires ``steps``.
        - ``steps`` cannot be combined with ``beats`` or ``bars``.

        Returns:
                (beat_length, default_grid) — beat_length in beats (quarter notes);
                default_grid the number of grid steps (16th-notes in beat mode, or the
                explicit ``steps`` value directly in step mode).
        """

        if beats is not None and bars is not None:
            raise ValueError("Specify only one of beats= or bars=")

        if steps is not None and (beats is not None or bars is not None):
            raise ValueError("steps= cannot be combined with beats= or bars=")

        if step_duration is not None and steps is None:
            raise ValueError(
                "step_duration= requires steps= (e.g. steps=6, step_duration=dur.SIXTEENTH)"
            )

        if steps is not None:
            if step_duration is None:
                raise ValueError(
                    "steps= requires step_duration= (e.g. step_duration=dur.SIXTEENTH)"
                )
            return steps * step_duration, int(steps)

        if bars is not None:
            raw = bars * beats_per_bar
        elif beats is not None:
            raw = beats
        else:
            raw = default

        return raw, round(raw / subsequence.constants.durations.SIXTEENTH)

    def pattern(
        self,
        channel: int,
        beats: typing.Optional[float] = None,
        bars: typing.Optional[float] = None,
        steps: typing.Optional[float] = None,
        step_duration: typing.Optional[float] = None,
        drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
        cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
        nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
        reschedule_lookahead: float = 1,
        voice_leading: bool = False,
        device: subsequence.midi_utils.DeviceId = None,
        mirrors: typing.Optional[
            typing.Iterable[subsequence.pattern.MirrorSpec]
        ] = None,
        min_energy: typing.Optional[float] = None,
    ) -> typing.Callable:
        """
        Register a function as a repeating MIDI pattern.

        The decorated function will be called once per cycle to 'rebuild' its
        content. This allows for generative logic that evolves over time.

        Two ways to specify pattern length:

        - **Duration mode** (default): use ``beats=`` or ``bars=``.
          The grid defaults to sixteenth-note resolution.
        - **Step mode**: use ``steps=`` paired with ``step_duration=``.
          The grid equals the step count, so ``p.hit_steps()`` indices map
          directly to steps.

        Parameters:
                channel: MIDI channel. By default uses 1-based numbering (1-16).
                        Set ``zero_indexed_channels=True`` on the ``Composition`` to use
                        0-based numbering (0-15), matching the raw MIDI protocol, instead.
                beats: Duration in beats (quarter notes). ``beats=4`` = 1 bar.
                bars: Duration in bars (uses the composition's time signature — 4 beats each in 4/4). ``bars=2`` = 8 beats.
                steps: Step count for step mode. Requires ``step_duration=``.
                step_duration: Duration of one step in beats (e.g. ``dur.SIXTEENTH``).
                        Requires ``steps=``.
                drum_note_map: Optional mapping for drum instruments.
                cc_name_map: Optional mapping of CC names to MIDI CC numbers.
                        Enables string-based CC names in ``p.cc()`` and ``p.cc_ramp()``.
                nrpn_name_map: Optional mapping of NRPN parameter names (strings) to
                        14-bit parameter numbers (0–16383).  Enables string-based names
                        in ``p.nrpn()`` and ``p.nrpn_ramp()`` — typically a
                        device-specific dictionary (e.g. Sequential Take 5's
                        ``Osc1FreqFine`` → 9).
                reschedule_lookahead: Beats in advance to compute the next cycle.
                voice_leading: If True, chords in this pattern will automatically
                        use inversions that minimize voice movement.
                mirrors: Optional list of additional ``(device, channel)`` destinations
                        to duplicate every event from this pattern onto.  Notes, CCs, pitch
                        bend, NRPN/RPN bursts, program changes, SysEx, and drone events are
                        all mirrored; OSC events are not (OSC is not bound to a MIDI port).
                        ``device`` is the integer index returned by ``midi_output()`` (0 =
                        primary).  ``channel`` follows this composition's channel-numbering
                        convention.  See also ``mirror()`` / ``unmirror()`` for live toggling.
                min_energy: Automatic energy gating — the pattern is silent while
                        the current section's energy (``composition.energy()`` dict,
                        or the bound Section payload) is below this threshold.
                        Composes with ``mute()``: a performer mute always wins.

        Example:
                ```python
                @comp.pattern(channel=1, beats=4)
                def chords (p):
                        p.chord([60, 64, 67], beat=0, velocity=80, duration=3.9)

                @comp.pattern(channel=1, bars=2)
                def long_phrase (p):
                        ...

                @comp.pattern(channel=1, steps=6, step_duration=dur.SIXTEENTH)
                def riff (p):
                        p.sequence(steps=[0, 1, 3, 5], pitches=60)
                ```
        """

        channel = self._resolve_channel(channel)

        beat_length, default_grid = self._resolve_length(
            beats, bars, steps, step_duration, beats_per_bar=self.time_signature[0]
        )

        # Resolve device string name to index if possible now; otherwise store
        # the raw DeviceId and resolve it in _run() once all devices are open.
        resolved_device: subsequence.midi_utils.DeviceId = device

        # Mirror-to-self check is only reliable when the primary device is a
        # concrete integer at decoration time.  ``None`` resolves to device 0
        # downstream, so we treat it as 0 here too.  Strings are deferred to
        # ``_run()`` and we skip the check for them.
        primary: typing.Optional[typing.Tuple[int, int]]
        if isinstance(resolved_device, str):
            primary = None
        else:
            primary = (resolved_device if resolved_device is not None else 0, channel)
        resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

        def decorator(fn: typing.Callable) -> typing.Callable:
            """
            Wrap the builder function and register it as a pending pattern.
            During live sessions, hot-swap an existing pattern's builder instead.
            """

            # Record this declaration so the live-reload deletion diff knows the
            # pattern is still present in the source (see _apply_source_async).
            self._declared_names.add(fn.__name__)

            # Hot-swap: if we're live and a pattern with this name exists, replace its builder.
            if self._is_live and fn.__name__ in self._running_patterns:
                running = self._running_patterns[fn.__name__]
                running._builder_fn = fn
                running._wants_chord = _fn_has_parameter(fn, "chord")
                logger.info(f"Hot-swapped pattern: {fn.__name__}")
                return fn

            # Names key the seeded stream, mutes, tweaks, and reroll/lock — a
            # duplicate means two scheduled copies sharing one stream with
            # only one reachable by name.  Warn loudly at registration.
            if any(
                existing.builder_fn.__name__ == fn.__name__
                for existing in self._pending_patterns
            ):
                logger.warning(
                    f"Duplicate pattern name '{fn.__name__}': both copies will be "
                    f"scheduled, they share one seeded stream, and only one is "
                    f"reachable by name — rename one of them."
                )

            pending = _PendingPattern(
                builder_fn=fn,
                channel=channel,  # already resolved to 0-indexed
                length=beat_length,
                default_grid=default_grid,
                drum_note_map=drum_note_map,
                cc_name_map=cc_name_map,
                nrpn_name_map=nrpn_name_map,
                reschedule_lookahead=reschedule_lookahead,
                voice_leading=voice_leading,
                # For int/None: resolve immediately.  For str: store 0 as
                # placeholder; _resolve_pending_devices() fixes it in _run().
                device=0
                if (resolved_device is None or isinstance(resolved_device, str))
                else resolved_device,
                raw_device=resolved_device,
                mirrors=resolved_mirrors,
                min_energy=min_energy,
            )

            self._pending_patterns.append(pending)

            return fn

        return decorator

    def layer(
        self,
        *builder_fns: typing.Callable,
        channel: int,
        beats: typing.Optional[float] = None,
        bars: typing.Optional[float] = None,
        steps: typing.Optional[float] = None,
        step_duration: typing.Optional[float] = None,
        drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
        cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
        nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
        reschedule_lookahead: float = 1,
        voice_leading: bool = False,
        device: subsequence.midi_utils.DeviceId = None,
        mirrors: typing.Optional[
            typing.Iterable[subsequence.pattern.MirrorSpec]
        ] = None,
    ) -> None:
        """
        Combine multiple functions into a single MIDI pattern.

        This is useful for composing complex patterns out of reusable
        building blocks (e.g., a 'kick' function and a 'snare' function).

        See ``pattern()`` for the full description of ``beats``, ``bars``,
        ``steps``, and ``step_duration``.

        Parameters:
                builder_fns: One or more pattern builder functions.
                channel: MIDI channel (1-16, or 0-15 with ``zero_indexed_channels=True``).
                beats: Duration in beats (quarter notes).
                bars: Duration in bars (uses the composition's time signature — 4 beats each in 4/4).
                steps: Step count for step mode. Requires ``step_duration=``.
                step_duration: Duration of one step in beats. Requires ``steps=``.
                drum_note_map: Optional mapping for drum instruments.
                cc_name_map: Optional mapping of CC names to MIDI CC numbers.
                nrpn_name_map: Optional mapping of NRPN parameter names to 14-bit
                        parameter numbers.
                reschedule_lookahead: Beats in advance to compute the next cycle.
                voice_leading: If True, chords use smooth voice leading.
                mirrors: Optional list of additional ``(device, channel)`` destinations
                        to duplicate every event onto.  See ``pattern()`` for details.
        """

        beat_length, default_grid = self._resolve_length(
            beats, bars, steps, step_duration, beats_per_bar=self.time_signature[0]
        )

        # Resolve channel up-front so the mirror-to-self check has the canonical
        # primary form to compare against.
        resolved_channel = self._resolve_channel(channel)

        # See pattern() for the same comment about None / str handling.
        primary: typing.Optional[typing.Tuple[int, int]]
        if isinstance(device, str):
            primary = None
        else:
            primary = (device if device is not None else 0, resolved_channel)
        resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

        wants_chord = any(_fn_has_parameter(fn, "chord") for fn in builder_fns)

        if wants_chord:

            def merged_builder(
                p: subsequence.pattern_builder.PatternBuilder, chord: _InjectedChord
            ) -> None:
                for fn in builder_fns:
                    if _fn_has_parameter(fn, "chord"):
                        fn(p, chord)
                    else:
                        fn(p)

        else:

            def merged_builder(p: subsequence.pattern_builder.PatternBuilder) -> None:  # type: ignore[misc]
                for fn in builder_fns:
                    fn(p)

        # Give the merged builder a stable, unique name derived from its
        # components so multiple layer() calls don't all register under
        # "merged_builder" and collide in _running_patterns (which made
        # mute/tweak/unregister/live_info reach only the LAST layer).  "+" can't
        # appear in a Python identifier, so this never clashes with a real
        # pattern function's name.
        base_name = (
            "+".join(fn.__name__ for fn in builder_fns) or "layer"
        ) + f"@ch{resolved_channel}"
        merged_name = base_name
        suffix = 2

        # Two layers with the same components (e.g. on different saves of a
        # live file) must map to the same names pass-over-pass, while two
        # DIFFERENT layers sharing components in one pass must not collide.
        while merged_name in self._declared_names:
            merged_name = f"{base_name}#{suffix}"
            suffix += 1

        merged_builder.__name__ = merged_name

        # Record the declaration for the live-reload deletion diff, and hot-swap
        # in place when this layer is already running so a reload picks up edits
        # to the component functions without losing the pattern's cycle count,
        # tweaks, or mirrors (mirrors the pattern() decorator's hot-swap).
        self._declared_names.add(merged_builder.__name__)

        if self._is_live and merged_builder.__name__ in self._running_patterns:
            running = self._running_patterns[merged_builder.__name__]
            running._builder_fn = merged_builder
            running._wants_chord = wants_chord
            logger.info(f"Hot-swapped layer: {merged_builder.__name__}")
            return

        pending = _PendingPattern(
            builder_fn=merged_builder,
            channel=resolved_channel,  # already resolved to 0-indexed above
            length=beat_length,
            default_grid=default_grid,
            drum_note_map=drum_note_map,
            cc_name_map=cc_name_map,
            nrpn_name_map=nrpn_name_map,
            reschedule_lookahead=reschedule_lookahead,
            voice_leading=voice_leading,
            mirrors=resolved_mirrors,
            device=0 if (device is None or isinstance(device, str)) else device,
            raw_device=device,
        )

        self._pending_patterns.append(pending)

    def chords(
        self,
        *,
        channel: int,
        progression: subsequence.progressions.ProgressionSource,
        harmonic_rhythm: subsequence.progressions.HarmonicRhythmSpec,
        bars: typing.Optional[float] = None,
        beats: typing.Optional[float] = None,
        voicing: subsequence.progressions.VoicingSpec = (3, 4),
        velocity: typing.Union[
            int, typing.Tuple[int, int]
        ] = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY,
        detached: typing.Optional[float] = None,
        root: int = 60,
        key: typing.Optional[str] = None,
        seed: typing.Optional[int] = None,
        device: subsequence.midi_utils.DeviceId = None,
        mirrors: typing.Optional[
            typing.Iterable[subsequence.pattern.MirrorSpec]
        ] = None,
    ) -> subsequence.progressions.Progression:
        """Declare a self-contained chord part: a progression at a chosen harmonic rhythm.

        The one-call form of ``p.progression()`` — it registers a pattern on
        *channel* that plays *progression* across *bars* (or *beats*), each chord
        lasting a length drawn from *harmonic_rhythm* (the musical term for how often
        the chords change).  It needs no ``composition.harmony()`` call and, with an
        explicit chord list or a ``key=``, no composition key either — so a
        drums-plus-one-chord-part sketch stays simple.

        The progression is realised once, up front, and the same timeline plays every
        cycle (a stable phrase).  That timeline is returned so you can see exactly what
        was chosen — ``print(comp.chords(...))``.

        Parameters:
                channel: MIDI channel for the chord part.
                progression: A chord-graph style name to generate from, or an explicit list
                        of chords (``Chord`` objects or names like ``["Cm7", "Dbmaj7"]``).
                harmonic_rhythm: How long each chord lasts — a number, a list of lengths,
                        or ``between(low, high, step=...)``.  See ``p.progression()``.
                bars / beats: Length of the part (defaults to 4 beats if neither is given).  ``bars`` uses the
                        composition's time signature.
                voicing: Notes per chord — an int, or a ``(low, high)`` range (e.g. ``(3, 4)``).
                velocity: MIDI velocity, or a ``(low, high)`` tuple for per-voice humanisation.
                detached: Beats of silence before each next chord (``duration = length - detached``).
                root: MIDI root the voicings are centred on (e.g. 48 = C3).
                key: Key for a generated progression; defaults to the composition key.
                seed: Seed for the (otherwise fixed) realisation; defaults to the
                        composition seed, so the part is reproducible.
                device: Optional output-device override.
                mirrors: Optional additional ``(device, channel)`` destinations.

        Returns:
                The realised :class:`~subsequence.progressions.Progression`.
        """

        beat_length, default_grid = self._resolve_length(
            beats, bars, None, None, beats_per_bar=self.time_signature[0]
        )
        resolved_channel = self._resolve_channel(channel)
        resolved_key = key if key is not None else self.key

        rng = random.Random(seed if seed is not None else self._seed)
        timeline = subsequence.progressions.realize(
            source=progression,
            harmonic_rhythm=harmonic_rhythm,
            key=resolved_key,
            length=beat_length,
            rng=rng,
            scale=self.scale or "ionian",
        )

        captured_root = root
        captured_velocity = velocity
        captured_detached = detached
        captured_voicing = voicing

        def chords_builder(p: subsequence.pattern_builder.PatternBuilder) -> None:
            """Replay the realised timeline as block chords each cycle (voicing per chord)."""

            for chord, start, length in timeline:
                ring = (
                    length - captured_detached
                    if (captured_detached and captured_detached < length)
                    else length
                )
                voices = subsequence.progressions.resolve_voices(
                    captured_voicing, p.rng
                )
                p.chord(
                    chord,
                    root=captured_root,
                    beat=start,
                    duration=ring,
                    count=voices,
                    velocity=captured_velocity,
                )

        # Unique, stable name so multiple chord parts don't collide in
        # _running_patterns — including two parts on the SAME channel, which
        # get a deterministic #2/#3 suffix in declaration order.
        base_name = f"chords@ch{resolved_channel}"
        chords_name = base_name
        suffix = 2

        while chords_name in self._declared_names:
            chords_name = f"{base_name}#{suffix}"
            suffix += 1

        chords_builder.__name__ = chords_name
        self._declared_names.add(chords_name)

        primary: typing.Optional[typing.Tuple[int, int]]
        if isinstance(device, str):
            primary = None
        else:
            primary = (device if device is not None else 0, resolved_channel)
        resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

        if self._is_live and chords_builder.__name__ in self._running_patterns:
            running = self._running_patterns[chords_builder.__name__]
            running._builder_fn = chords_builder
            running._wants_chord = False
            logger.info(f"Hot-swapped chords: {chords_builder.__name__}")
            return timeline

        pending = _PendingPattern(
            builder_fn=chords_builder,
            channel=resolved_channel,
            length=beat_length,
            default_grid=default_grid,
            drum_note_map=None,
            reschedule_lookahead=1,
            voice_leading=False,
            mirrors=resolved_mirrors,
            device=0 if (device is None or isinstance(device, str)) else device,
            raw_device=device,
        )
        self._pending_patterns.append(pending)
        return timeline

    def phrase_part(
        self,
        *,
        channel: int,
        part: typing.Optional[str] = None,
        root: int = 60,
        bars: typing.Optional[float] = None,
        beats: typing.Optional[float] = None,
        velocity: typing.Optional[typing.Union[int, typing.Tuple[int, int]]] = None,
        fit: typing.Optional[float] = None,
        device: subsequence.midi_utils.DeviceId = None,
        mirrors: typing.Optional[
            typing.Iterable[subsequence.pattern.MirrorSpec]
        ] = None,
    ) -> None:
        """Declare a part that plays each section's bound Motif/Phrase.

        The one-call consumer for :meth:`section_motifs` — it registers a
        pattern on *channel* that walks whatever value is bound to the
        current section for *part* (stateless position from the cycle
        counter, via ``p.phrase()``).  A section with no binding for the
        part is **silent** for that part — bind material or don't; no
        fallback guessing.

        Parameters:
                channel: MIDI channel for the part.
                part: The part label to read from the registry (``None`` = the
                        unlabelled binding).
                root: Register anchor for degree resolution.
                bars / beats: Cycle length of the part (defaults to 4 beats);
                        the phrase is sliced one cycle window at a time.
                velocity: Optional override applied to every note.
                fit: Passed through (active with the melody engine stage).
                device: Optional output-device override.
                mirrors: Optional additional ``(device, channel)`` destinations.

        Example::

                composition.section_motifs("verse",  verse_line,  part="lead")
                composition.section_motifs("chorus", chorus_line, part="lead")
                composition.phrase_part(channel=4, part="lead", root=72, bars=2)
        """

        beat_length, default_grid = self._resolve_length(
            beats, bars, None, None, beats_per_bar=self.time_signature[0]
        )
        resolved_channel = self._resolve_channel(channel)

        captured_part = part
        captured_root = root
        captured_velocity = velocity
        captured_fit = fit

        def phrase_builder(p: subsequence.pattern_builder.PatternBuilder) -> None:
            """Walk the current section's bound value (silent when unbound)."""

            value = p.section_motif(captured_part)

            if value is None:
                return  # unbound section: silence for this part, by design

            p.phrase(
                value, root=captured_root, velocity=captured_velocity, fit=captured_fit
            )

        # Unique, stable name so multiple phrase parts don't collide —
        # including two parts on the SAME channel (deterministic #2/#3
        # suffixes in declaration order, the chords() convention).
        base_name = (
            f"phrase@{captured_part}@ch{resolved_channel}"
            if captured_part
            else f"phrase@ch{resolved_channel}"
        )
        phrase_name = base_name
        suffix = 2

        while phrase_name in self._declared_names:
            phrase_name = f"{base_name}#{suffix}"
            suffix += 1

        phrase_builder.__name__ = phrase_name
        self._declared_names.add(phrase_name)

        primary: typing.Optional[typing.Tuple[int, int]]
        if isinstance(device, str):
            primary = None
        else:
            primary = (device if device is not None else 0, resolved_channel)
        resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

        if self._is_live and phrase_builder.__name__ in self._running_patterns:
            running = self._running_patterns[phrase_builder.__name__]
            running._builder_fn = phrase_builder
            running._wants_chord = False
            logger.info(f"Hot-swapped phrase part: {phrase_builder.__name__}")
            return

        pending = _PendingPattern(
            builder_fn=phrase_builder,
            channel=resolved_channel,
            length=beat_length,
            default_grid=default_grid,
            drum_note_map=None,
            reschedule_lookahead=1,
            voice_leading=False,
            mirrors=resolved_mirrors,
            device=0 if (device is None or isinstance(device, str)) else device,
            raw_device=device,
        )
        self._pending_patterns.append(pending)

    def trigger(
        self,
        fn: typing.Callable,
        channel: int,
        beats: typing.Optional[float] = None,
        bars: typing.Optional[float] = None,
        steps: typing.Optional[float] = None,
        step_duration: typing.Optional[float] = None,
        quantize: float = 0,
        drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
        cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
        nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
        chord: bool = False,
        device: subsequence.midi_utils.DeviceId = None,
        mirrors: typing.Optional[
            typing.Iterable[subsequence.pattern.MirrorSpec]
        ] = None,
    ) -> None:
        """
        Trigger a one-shot pattern immediately or on a quantized boundary.

        This is useful for real-time response to sensors, OSC messages, or other
        external events. The builder function is called immediately with a fresh
        PatternBuilder, and the generated events are injected into the queue at
        the specified quantize boundary.

        The builder function has the same API as a ``@composition.pattern``
        decorated function and can use all PatternBuilder methods: ``p.note()``,
        ``p.euclidean()``, ``p.arpeggio()``, and so on.

        See ``pattern()`` for the full description of ``beats``, ``bars``,
        ``steps``, and ``step_duration``. Default is 1 beat.

        Parameters:
                fn: The pattern builder function (same signature as ``@comp.pattern``).
                channel: MIDI channel (1-16, or 0-15 with ``zero_indexed_channels=True``).
                beats: Duration in beats (quarter notes, default 1).
                bars: Duration in bars (uses the composition's time signature — 4 beats each in 4/4).
                steps: Step count for step mode. Requires ``step_duration=``.
                step_duration: Duration of one step in beats. Requires ``steps=``.
                quantize: Snap the trigger to a beat boundary: ``0`` = immediate (default),
                        ``1`` = next beat (quarter note), ``4`` = next bar. Use ``dur.*``
                        constants from ``subsequence.constants.durations``.
                drum_note_map: Optional drum name mapping for this pattern.
                cc_name_map: Optional mapping of CC names to MIDI CC numbers.
                nrpn_name_map: Optional mapping of NRPN parameter names to
                        14-bit parameter numbers.
                chord: If ``True``, the builder function receives the current chord as
                        a second parameter (same as ``@composition.pattern``).
                mirrors: Optional list of additional ``(device, channel)`` destinations
                        to fire this one-shot onto in parallel with the primary destination.

        Example:
                ```python
                # Immediate single note (channels are 1-16 by default)
                composition.trigger(
                        lambda p: p.note(60, beat=0, velocity=100, duration=0.5),
                        channel=1
                )

                # Quantized fill (next bar) — channel 10 is the GM drum channel
                import subsequence.constants.durations as dur
                composition.trigger(
                        lambda p: p.euclidean("snare", pulses=7, velocity=90),
                        channel=10,
                        drum_note_map=gm_drums.GM_DRUM_MAP,
                        quantize=dur.WHOLE
                )

                # With chord context — the builder receives the chord as a second
                # argument when chord=True.
                composition.trigger(
                        lambda p, chord: p.arpeggio(chord.tones(root=60), spacing=dur.SIXTEENTH),
                        channel=1,
                        quantize=dur.QUARTER,
                        chord=True
                )
                ```
        """

        # Resolve channel numbering
        resolved_channel = self._resolve_channel(channel)

        beat_length, default_grid = self._resolve_length(
            beats,
            bars,
            steps,
            step_duration,
            default=1.0,
            beats_per_bar=self.time_signature[0],
        )

        # Resolve device index — for trigger() this is always concrete by call time,
        # so the mirror-to-self check has the full primary tuple available.
        resolved_device_idx = self._resolve_device_id(device)
        resolved_mirrors = self._resolve_mirrors(
            mirrors, primary=(resolved_device_idx, resolved_channel)
        )

        # Create a temporary Pattern
        pattern = subsequence.pattern.Pattern(
            channel=resolved_channel,
            length=beat_length,
            device=resolved_device_idx,
            mirrors=resolved_mirrors,
        )

        # Resolve the section context once: the one-shot inherits the section's
        # effective key/scale (so a triggered degree resolves like everywhere
        # else) and a harmony view at the current playhead (so ChordTone /
        # Approach resolve too).
        trigger_section = (
            self._form_state.get_section_info() if self._form_state else None
        )
        trigger_key, trigger_scale = self._effective_key_scale(trigger_section)

        trigger_harmony: typing.Optional[HarmonyView] = None
        if not self._harmony_horizon.is_empty:
            trigger_harmony = HarmonyView(
                self._harmony_horizon,
                self._sequencer.pulse_count / self._sequencer.pulses_per_beat,
            )

        # Create a PatternBuilder
        builder = subsequence.pattern_builder.PatternBuilder(
            pattern=pattern,
            cycle=0,  # One-shot patterns don't rebuild, so cycle is always 0
            drum_note_map=drum_note_map,
            cc_name_map=cc_name_map,
            nrpn_name_map=nrpn_name_map,
            section=trigger_section,
            bar=self._builder_bar,
            conductor=self.conductor,
            rng=random.Random(),  # Fresh random state for each trigger
            tweaks={},
            default_grid=default_grid,
            data=self.data,
            # A one-shot resolves key-relative content against the same
            # effective key/scale as the section it fires into (previously
            # omitted entirely — degrees raised even in a keyed composition).
            key=trigger_key,
            scale=trigger_scale,
            time_signature=self.time_signature,
            held_notes=self._sequencer._held_notes,
            harmony=trigger_harmony,
            energy=self._current_energy(trigger_section),
        )

        # Call the builder function
        try:
            current_chord = self.current_chord() if chord else None

            if current_chord is not None:
                injected = _InjectedChord(
                    current_chord, None
                )  # No voice leading for one-shots
                fn(builder, injected)

            else:
                fn(builder)

        except Exception:
            logger.exception("Error in trigger builder — pattern will be silent")
            return

        # Calculate the start pulse based on quantize
        current_pulse = self._sequencer.pulse_count
        pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE

        if quantize == 0:
            # Immediate: use current pulse
            start_pulse = current_pulse

        else:
            # Quantize to the next multiple of (quantize * pulses_per_beat)
            quantize_pulses = int(quantize * pulses_per_beat)
            start_pulse = ((current_pulse // quantize_pulses) + 1) * quantize_pulses

        self._schedule_one_shot(pattern, start_pulse)

    def _schedule_one_shot(
        self, pattern: subsequence.pattern.Pattern, start_pulse: int
    ) -> None:
        """Schedule a one-shot pattern at an absolute pulse, thread-safely."""

        try:
            # Probe only: raises RuntimeError when not on the event loop.
            asyncio.get_running_loop()
            asyncio.create_task(self._sequencer.schedule_pattern(pattern, start_pulse))

        except RuntimeError:
            # Not on the event loop — hand the coroutine to the loop thread.
            if self._sequencer._event_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._sequencer.schedule_pattern(pattern, start_pulse),
                    loop=self._sequencer._event_loop,
                )
            else:
                logger.warning(
                    "trigger() called before playback started; pattern ignored"
                )

    @property
    def is_clock_following(self) -> bool:
        """True if either the primary or any additional device is following external clock."""

        return self._clock_follow or any(cf for _, _, cf in self._additional_inputs)

    def play(self) -> None:
        """
        Start the composition.

        This call blocks until the program is interrupted (e.g., via Ctrl+C).
        It initializes the MIDI hardware, launches the background sequencer,
        and begins playback.
        """

        try:
            asyncio.run(self._run())

        except KeyboardInterrupt:
            pass

    def render(
        self,
        bars: typing.Optional[int] = None,
        filename: str = "render.mid",
        max_minutes: typing.Optional[float] = 60.0,
    ) -> None:
        """Render the composition to a MIDI file without real-time playback.

        Runs the sequencer as fast as possible (no timing delays) and stops
        when the first active limit is reached.  The result is saved as a
        standard MIDI file that can be imported into any DAW.

        All patterns, scheduled callbacks, and harmony logic run exactly as
        they would during live playback — BPM transitions, generative fills,
        and probabilistic gates all work in render mode.  The only difference
        is that time is simulated rather than wall-clock driven.

        Parameters:
                bars: Number of bars to render, or ``None`` for no bar limit
                      (default ``None``).  When both *bars* and *max_minutes* are
                      active, playback stops at whichever limit is reached first.
                filename: Output MIDI filename (default ``"render.mid"``).
                max_minutes: Safety cap on the length of rendered MIDI in minutes
                             (default ``60.0``).  Pass ``None`` to disable the time
                             cap — you must then provide an explicit *bars* value.

        Raises:
                ValueError: If both *bars* and *max_minutes* are ``None``, which
                            would produce an infinite render.

        Examples:
                ```python
                # Default: renders up to 60 minutes of MIDI content.
                composition.render()

                # Render exactly 64 bars (time cap still active as backstop).
                composition.render(bars=64, filename="demo.mid")

                # Render up to 5 minutes of an infinite generative composition.
                composition.render(max_minutes=5, filename="five_min.mid")

                # Remove the time cap — must supply bars instead.
                composition.render(bars=128, max_minutes=None, filename="long.mid")
                ```
        """

        if bars is None and max_minutes is None:
            raise ValueError(
                "render() requires at least one limit: provide bars=, max_minutes=, or both. "
                "Passing both as None would produce an infinite render."
            )

        self._sequencer.recording = True
        self._sequencer.record_filename = filename
        self._sequencer.render_mode = True
        self._sequencer.render_bars = bars if bars is not None else 0
        self._sequencer.render_max_seconds = (
            max_minutes * 60.0 if max_minutes is not None else None
        )
        asyncio.run(self._run())

    def _broadcast_osc_status(self, bar: int) -> None:
        """
        Send the per-bar OSC status snapshot: bar number, current tempo,
        and (when active) the current chord name and form section.
        """

        if self._osc_server:
            self._osc_server.send("/bar", bar)
            self._osc_server.send("/bpm", self._sequencer.current_bpm)

            sounding = self.current_chord()
            if sounding is not None:
                self._osc_server.send("/chord", sounding.name())

            if self._form_state:
                info = self._form_state.get_section_info()
                if info:
                    self._osc_server.send("/section", info.name)

    async def _run(self) -> None:
        """
        Async entry point that schedules all patterns and runs the sequencer.
        """

        # 1. Pre-calculate MIDI input indices and configure sequencer clock follow.
        if self._input_device is not None:
            self._sequencer.input_device_name = self._input_device
            self._sequencer.clock_follow = self._clock_follow
            self._sequencer.clock_device_idx = 0

            if not self._clock_follow:
                # Find first additional input that wants to be the clock master.
                for idx, (_, _, cf) in enumerate(self._additional_inputs, start=1):
                    if cf:
                        self._sequencer.clock_follow = True
                        self._sequencer.clock_device_idx = idx
                        break

        # Populate input device name mapping early (before opening ports) so we can
        # resolve CC mappings to integer device indices immediately.
        if self._sequencer.input_device_name:
            self._input_device_names[self._sequencer.input_device_name] = 0
            if self._input_device_alias is not None:
                self._input_device_names[self._input_device_alias] = 0

        for idx, (dev_name, alias, _) in enumerate(self._additional_inputs, start=1):
            self._input_device_names[dev_name] = idx
            if alias:
                self._input_device_names[alias] = idx

        # 2. Pre-calculate output device names.
        if self._sequencer.output_device_name:
            self._output_device_names[self._sequencer.output_device_name] = 0
            # Primary device (index 0) is open by now (_init_midi_output ran in
            # the Sequencer constructor), so its latency can be set safely here.
            if self._output_latency_ms:
                self._sequencer.set_device_latency(0, self._output_latency_ms)

        # 3. Resolve name-based INPUT device ids in cc_map/cc_forward early — the
        # input-names map is fully populated above, and the callback thread needs
        # integer indices as soon as ports open.  OUTPUT names (cc_forward
        # output_device=, pattern device=) resolve after the additional outputs
        # are opened below; resolving them here matched against a map containing
        # only the primary and silently routed everything to device 0.
        for mapping in self._cc_mappings:
            raw = mapping.get("input_device")
            if isinstance(raw, str):
                mapping["input_device"] = self._resolve_input_device_id(raw)
        for fwd in self._cc_forwards:
            raw_in = fwd.get("input_device")
            if isinstance(raw_in, str):
                fwd["input_device"] = self._resolve_input_device_id(raw_in)

        # 4. Share CC input mappings, forwards, and a reference to composition.data
        # with the sequencer BEFORE opening the ports. This ensures that any initial
        # messages in the OS buffer are correctly mapped as soon as the port opens.
        self._sequencer.cc_mappings = self._cc_mappings
        self._sequencer.cc_forwards = self._cc_forwards
        self._sequencer._composition_data = self.data

        # Held-note input: create the tracker and resolve its channel/device
        # filter so the callback thread can buffer matching note events.
        if self._note_input is not None:
            if self._input_device is None and not self._additional_inputs:
                raise RuntimeError(
                    "note_input() requires a MIDI input — call composition.midi_input(device) first"
                )
            raw_dev = self._note_input.get("input_device")
            if isinstance(raw_dev, str):
                raw_dev = self._resolve_input_device_id(raw_dev)
            self._sequencer._note_input_channel = self._note_input["channel"]
            self._sequencer._note_input_device = raw_dev
            self._sequencer._held_notes = subsequence.held_notes.HeldNotes(
                release_ms=self._note_input["release_ms"],
                latch=self._note_input["latch"],
            )

        # 5. Open MIDI input ports early. Even without a deliberate sleep, opening
        # them before pattern building minimizes the window for missed messages.
        # Primary input
        self._sequencer._open_midi_inputs()

        # Additional inputs
        for idx, (dev_name, alias, cf) in enumerate(self._additional_inputs, start=1):
            # Use the pre-calculated index
            callback = self._sequencer._make_input_callback(idx)
            open_name, port = subsequence.midi_utils.select_input_device(
                dev_name, callback
            )
            if open_name and port is not None:
                self._sequencer.add_input_device(open_name, port)
            else:
                logger.warning(f"Could not open additional input device '{dev_name}'")

        # 6. Open additional MIDI output devices.
        for out in self._additional_outputs:
            open_name, port = subsequence.midi_utils.select_output_device(out.device)
            if open_name and port is not None:
                idx = self._sequencer.add_output_device(open_name, port, out.latency_ms)
                self._output_device_names[open_name] = idx
                if out.alias is not None:
                    self._output_device_names[out.alias] = idx
            else:
                logger.warning(
                    f"Could not open additional output device '{out.device}'"
                )

        # Warn if latency compensation adds noticeable whole-rig delay: the
        # slowest device defines the alignment point, so every faster device is
        # delayed up to that amount and live-input feel suffers.
        self._warn_if_high_latency()

        # Resolve any name-based output device IDs on patterns that may have been added
        # for additional output devices.
        self._resolve_pending_devices()

        # Resolve cc_forward output-device names now that every output port and
        # alias is registered (resolving earlier silently routed to device 0).
        for fwd in self._cc_forwards:
            raw_out = fwd.get("output_device")
            if isinstance(raw_out, str):
                fwd["output_device"] = self._resolve_device_id(raw_out)

        # Pass clock output flag (suppressed automatically when clock_follow=True).
        self._sequencer.clock_output = (
            self._clock_output and not self.is_clock_following
        )

        # Create Ableton Link clock if comp.link() was called.
        if self._link_quantum is not None:
            self._sequencer._link_clock = subsequence.link_clock.LinkClock(
                bpm=self.bpm,
                quantum=self._link_quantum,
                loop=asyncio.get_running_loop(),
            )

        # Deal play-time streams.  Every stream is NAME-keyed (crc32 of
        # "seed:name", see _stream_seed) rather than dealt from one master in
        # registration order: adding or removing one consumer can never shift
        # another's stream, and patterns added live derive identically in
        # _build_pattern_from_pending.  When no seed is set, components keep
        # their own unseeded RNGs (existing behaviour).
        if self._seed is not None:
            harmony_stream = self._stream("play:harmony")
            if self._harmonic_state is not None and harmony_stream is not None:
                self._harmonic_state.rng = harmony_stream

            form_stream = self._stream("play:form")
            if self._form_state is not None and form_stream is not None:
                self._form_state._rng = form_stream

        # The clocks fire BEFORE pattern rebuilds at the same pulse, and their
        # lookahead is RAISED to the maximum pattern lookahead (never patterns
        # clamped down): when a pattern rebuilds for its next cycle, the form
        # state and the harmony window already describe that cycle.
        bar_beats = float(self.time_signature[0])

        pattern_lookaheads = [
            pending.reschedule_lookahead for pending in self._pending_patterns
        ]
        pattern_lookaheads += [
            pattern.reschedule_lookahead for pattern in self._running_patterns.values()
        ]
        max_pattern_lookahead = max(pattern_lookaheads, default=1)

        clock_lookahead = max(
            1.0, float(self._harmony_reschedule_lookahead), float(max_pattern_lookahead)
        )

        if clock_lookahead > bar_beats:
            logger.warning(
                "A pattern's reschedule_lookahead (%.2g beats) exceeds the bar length (%.2g) — "
                "the harmony/form clocks fire at most one bar ahead, so that pattern may "
                "rebuild before the window covers its cycle start.",
                clock_lookahead,
                bar_beats,
            )
            clock_lookahead = bar_beats

        # Minimum span >= maximum lookahead: the clock cannot prepare a chord
        # boundary that arrives sooner than it fires.  Harmonic motion faster
        # than this floor stays available at the part level (p.progression),
        # where placement is not clock-bound.
        def _check_span_floor(
            progression: typing.Optional[Progression], label: str
        ) -> None:
            if progression is None:
                return
            shortest = min(span.beats for span in progression.spans)
            if shortest < clock_lookahead - 1e-9:
                raise ValueError(
                    f"{label}: shortest chord span ({shortest:g} beats) is below the clock "
                    f"lookahead ({clock_lookahead:g} beats — the largest pattern lookahead). "
                    "Lengthen the span, lower the pattern lookaheads, or place fast harmony "
                    "at the part level with p.progression()."
                )

        _check_span_floor(self._bound_progression, "harmony(progression=)")
        for section_name, section_progression in self._section_progressions.items():
            _check_span_floor(section_progression, f"section_chords({section_name!r})")

        # Key-relative section progressions resolve late, per occurrence — so
        # verify they WILL resolve now, before playback, rather than surfacing
        # a silent skip (or a dead clock) mid-render.  For each occurrence's
        # effective key+scale: a missing key, or a degree/scale that does not
        # resolve, is raised here with an actionable message.
        fs = self._form_state

        for section_name, section_progression in self._section_progressions.items():
            if section_progression.is_concrete:
                continue

            # The (key, scale) contexts this section may be resolved against.
            contexts: typing.List[
                typing.Tuple[typing.Optional[str], typing.Optional[str]]
            ] = []
            if (
                fs is not None
                and fs._sequence is not None
                and any(s.name == section_name for s in fs._sequence)
            ):
                for section in fs._sequence:
                    if section.name != section_name:
                        continue
                    ctx = (
                        section.key or self._form_key or self.key,
                        section.scale or self._form_scale or self.scale,
                    )
                    if ctx not in contexts:
                        contexts.append(ctx)
            else:
                contexts.append(
                    (self._form_key or self.key, self._form_scale or self.scale)
                )

            for ctx_key, ctx_scale in contexts:
                if ctx_key is None:
                    raise ValueError(
                        f"section_chords({section_name!r}) is key-relative (degrees/romans) but no key "
                        "resolves for it — set key= on the Composition, a form key (form(key=...)), or "
                        f"a Section.key on every {section_name!r} section."
                    )
                try:
                    section_progression.resolve(ctx_key, ctx_scale or "ionian")
                except ValueError as error:
                    raise ValueError(
                        f"section_chords({section_name!r}) does not resolve against its effective key "
                        f"{ctx_key} {ctx_scale or 'ionian'}: {error}"
                    )

        # min_energy with nothing feeding p.energy is a silent no-op — warn loudly.
        energy_gated = [
            p.builder_fn.__name__
            for p in self._pending_patterns
            if p.min_energy is not None
        ]

        if energy_gated and not self._energy_map and not self._form_has_payload:
            logger.warning(
                f"min_energy is set on {', '.join(energy_gated)} but no energy source is "
                "configured — p.energy is always 0.5 (call composition.energy() or bind a "
                "Form whose Sections carry energy)"
            )

        # The form clock MUST be registered before the harmonic clock: same-pulse
        # fixed callbacks fire in registration order (and all fixed callbacks fire
        # before callback sequences), and on a section-boundary bar the harmonic
        # clock reads the current section (via _get_section_progression) to decide
        # whether to walk that section's chords.  Registering harmony first would
        # make it read the OLD section on every boundary, shifting section_chords()
        # replays by one bar and bleeding them across sections.
        if self._form_state is not None:
            await schedule_form(
                sequencer=self._sequencer,
                form_state=self._form_state,
                reschedule_lookahead=clock_lookahead,
                on_bar=self._check_transitions,
                # Re-read every bar so a mid-playback form() re-bind advances
                # the NEW state instead of the abandoned object.
                get_form_state=lambda: self._form_state,
            )

        self._harmony_horizon.reset()
        self._harmonic_clock_started = False

        if (
            self._harmonic_state is not None
            or self._bound_progression is not None
            or self._section_progressions
        ):
            await self._start_harmonic_clock(bar_beats, clock_lookahead)

        # Bar counter - always active so p.bar is available to all builders.
        def _advance_builder_bar(pulse: int) -> None:
            self._builder_bar += 1

        first_bar_pulse = int(self.time_signature[0] * self._sequencer.pulses_per_beat)

        await self._sequencer.schedule_callback_repeating(
            callback=_advance_builder_bar,
            interval_beats=self.time_signature[0],
            start_pulse=first_bar_pulse,
            # Same raised lookahead as the form/harmony clocks: a pattern
            # rebuilding lookahead-early for its next cycle must read the bar
            # that cycle starts in, not the previous one.
            reschedule_lookahead=clock_lookahead,
        )

        # Run wait_for_initial=True scheduled functions and block until all complete.
        # This ensures composition.data is populated before patterns build.
        initial_tasks = [t for t in self._pending_scheduled if t.wait_for_initial]

        if initial_tasks:
            names = ", ".join(
                getattr(t.fn, "__name__", repr(t.fn)) for t in initial_tasks
            )
            logger.info(
                f"Waiting for initial scheduled {'function' if len(initial_tasks) == 1 else 'functions'} before start: {names}"
            )

            async def _run_initial(fn: typing.Callable) -> None:
                accepts_ctx = _fn_has_parameter(fn, "p")
                ctx = ScheduleContext(cycle=0)

                try:
                    if inspect.iscoroutinefunction(fn):
                        await (fn(ctx) if accepts_ctx else fn())
                    else:
                        loop = asyncio.get_running_loop()
                        call = (lambda: fn(ctx)) if accepts_ctx else fn
                        await loop.run_in_executor(None, call)
                except Exception as exc:
                    logger.warning(
                        f"Initial run of {getattr(fn, '__name__', repr(fn))!r} failed: {exc}"
                    )

            await asyncio.gather(*[_run_initial(t.fn) for t in initial_tasks])

        for pending_task in self._pending_scheduled:
            accepts_ctx = _fn_has_parameter(pending_task.fn, "p")

            # A wait_for_initial task already ran once as cycle 0 (the blocking
            # pre-roll above), so its repeating wrapper starts at cycle 1 — keeping
            # ScheduleContext.cycle monotonic across the initial and repeating runs.
            wrapped = _make_safe_callback(
                pending_task.fn,
                accepts_context=accepts_ctx,
                start_cycle=1 if pending_task.wait_for_initial else 0,
            )

            # wait_for_initial=True implies defer — no point firing at pulse 0
            # after the blocking run just completed.  defer=True skips the
            # backshift fire so the first repeating call happens one full cycle
            # later.
            if pending_task.wait_for_initial or pending_task.defer:
                start_pulse = int(
                    pending_task.cycle_beats * self._sequencer.pulses_per_beat
                )
            else:
                start_pulse = 0

            await self._sequencer.schedule_callback_repeating(
                callback=wrapped,
                interval_beats=pending_task.cycle_beats,
                start_pulse=start_pulse,
                reschedule_lookahead=pending_task.reschedule_lookahead,
            )

        # Build Pattern objects from pending registrations.
        patterns: typing.List[subsequence.pattern.Pattern] = []

        for i, pending in enumerate(self._pending_patterns):
            pattern = self._build_pattern_from_pending(pending)
            patterns.append(pattern)

        await schedule_patterns(
            sequencer=self._sequencer, patterns=patterns, start_pulse=0
        )

        # Populate the running patterns dict for live hot-swap and mute/unmute.
        for i, pending in enumerate(self._pending_patterns):
            name = pending.builder_fn.__name__
            self._running_patterns[name] = patterns[i]

        # Everything pending is running now; drop the declarations so a later
        # live reload cannot graduate stale copies.
        self._pending_patterns = []

        if self._display is not None and not self._sequencer.render_mode:
            self._display.start()
            self._sequencer.on_event("bar", self._display.update)
            self._sequencer.on_event("beat", self._display.update)

        if self._live_server is not None:
            await self._live_server.start()

        if self._osc_server is not None:
            await self._osc_server.start()
            self._sequencer.osc_server = self._osc_server
            self._sequencer.on_event("bar", self._broadcast_osc_status)

        # Start keystroke listener if hotkeys are enabled and not in render mode.
        if self._hotkeys_enabled and not self._sequencer.render_mode:
            self._keystroke_listener = subsequence.keystroke.KeystrokeListener()
            self._keystroke_listener.start()

            if self._keystroke_listener.active:
                # Listener started successfully — register the bar handler
                # and show all bindings so the user knows what's available.
                self._sequencer.on_event("bar", self._process_hotkeys)
                self._list_hotkeys()
            # If not active, KeystrokeListener.start() already logged a warning.

        if self._web_ui_enabled and not self._sequencer.render_mode:
            self._web_ui_server = subsequence.web_ui.WebUI(
                self, http_host=self._web_ui_http_host, ws_host=self._web_ui_ws_host
            )
            self._web_ui_server.start()

        try:
            await run_until_stopped(self._sequencer)
        finally:
            # Tear down every service even if run_until_stopped (or an earlier
            # stop) raised, and guard each individually, so one failure can't
            # strand the rest — most importantly the keystroke listener's
            # terminal restore.
            if self._web_ui_server is not None:
                try:
                    self._web_ui_server.stop()
                except Exception:
                    logger.exception("Error stopping web UI")

            if self._live_server is not None:
                try:
                    await self._live_server.stop()
                except Exception:
                    logger.exception("Error stopping live server")

            if self._live_reloader is not None:
                try:
                    self._live_reloader.stop()
                except Exception:
                    logger.exception("Error stopping live reloader")

            if self._osc_server is not None:
                try:
                    await self._osc_server.stop()
                except Exception:
                    logger.exception("Error stopping OSC server")
                self._sequencer.osc_server = None

            if self._display is not None:
                try:
                    self._display.stop()
                except Exception:
                    logger.exception("Error stopping display")

            if self._keystroke_listener is not None:
                try:
                    self._keystroke_listener.stop()
                except Exception:
                    logger.exception("Error stopping keystroke listener")
                self._keystroke_listener = None

    def _build_pattern_from_pending(
        self, pending: _PendingPattern, start_pulse: int = 0
    ) -> subsequence.pattern.Pattern:
        """
        Create a Pattern from a pending registration using a temporary subclass.

        The pattern's play stream is dealt here, keyed by NAME (crc32 of
        "seed:name" plus any reroll nonce), so registration order is
        irrelevant and a pattern added live gets exactly the stream it would
        have had at startup.  ``start_pulse`` anchors the first cycle on the
        beat axis so the initial build reads the harmony window at the right
        place (the sequencer keeps the anchor current on every reschedule).
        """

        composition_ref = self
        rng = self._stream(pending.builder_fn.__name__)

        class _DecoratorPattern(subsequence.pattern.Pattern):
            """
            Pattern subclass that delegates to a builder function on each reschedule.
            """

            def __init__(
                self,
                pending: _PendingPattern,
                pattern_rng: typing.Optional[random.Random] = None,
            ) -> None:
                """
                Initialize the decorator pattern from pending registration details.
                """

                super().__init__(
                    channel=pending.channel,
                    length=pending.length,
                    reschedule_lookahead=pending.reschedule_lookahead,
                    device=pending.device,
                    mirrors=pending.mirrors,
                )

                self._builder_fn = pending.builder_fn
                self._drum_note_map = pending.drum_note_map
                self._cc_name_map = pending.cc_name_map
                self._nrpn_name_map = pending.nrpn_name_map
                self._default_grid: int = pending.default_grid
                self._wants_chord = _fn_has_parameter(pending.builder_fn, "chord")
                self._cycle_count = 0
                self._rng = pattern_rng
                self._muted = False
                self._min_energy = pending.min_energy
                self._energy_gated = False
                self._voice_leading_state: typing.Optional[
                    subsequence.voicings.VoiceLeadingState
                ] = (
                    subsequence.voicings.VoiceLeadingState()
                    if pending.voice_leading
                    else None
                )
                self._tweaks: typing.Dict[str, typing.Any] = {}

                # Anchor of the cycle being built, on the absolute pulse axis.
                # The sequencer updates this on every reschedule; the initial
                # value is the pattern's first scheduled start.
                self._cycle_start_pulse = start_pulse

                self._rebuild()

            def _rebuild(self) -> None:
                """
                Clear steps and call the builder function to repopulate.
                """

                self.steps = {}
                self.cc_events = []
                self.osc_events = []
                self.raw_note_events = []
                current_cycle = self._cycle_count
                self._cycle_count += 1

                # lock(): re-deal the stream from its effective seed every
                # rebuild so a locked pattern realizes identically each cycle.
                # Checked here (engine-side) so it survives live reload.
                if self._builder_fn.__name__ in composition_ref._locked_names:
                    locked_seed = composition_ref._stream_seed(
                        self._builder_fn.__name__
                    )
                    if locked_seed is not None:
                        self._rng = random.Random(locked_seed)

                if self._muted:
                    return

                section_info = (
                    composition_ref._form_state.get_section_info()
                    if composition_ref._form_state
                    else None
                )
                energy = composition_ref._current_energy(section_info)
                effective_key, effective_scale = composition_ref._effective_key_scale(
                    section_info
                )

                # Automatic energy gating: below the threshold the pattern is
                # silent this cycle (composing with _muted — a performer mute
                # always wins).  Gate flips log once.
                if self._min_energy is not None:
                    gated = energy < self._min_energy

                    if gated != self._energy_gated:
                        state_word = "closed" if gated else "open"
                        logger.info(
                            f"Pattern '{self._builder_fn.__name__}': energy gate {state_word} "
                            f"(energy {energy:.2f}, min_energy {self._min_energy:g})"
                        )
                        self._energy_gated = gated

                    if gated:
                        return

                # The harmony view for this cycle, anchored at its start beat —
                # under variable harmonic rhythm the window, not the engine's
                # mutating singleton, is the source of truth.
                harmony_view: typing.Optional[HarmonyView] = None

                if not composition_ref._harmony_horizon.is_empty:
                    origin_beat = (
                        self._cycle_start_pulse
                        / composition_ref._sequencer.pulses_per_beat
                    )
                    harmony_view = HarmonyView(
                        composition_ref._harmony_horizon, origin_beat
                    )

                builder = subsequence.pattern_builder.PatternBuilder(
                    pattern=self,
                    cycle=current_cycle,
                    drum_note_map=self._drum_note_map,
                    cc_name_map=self._cc_name_map,
                    nrpn_name_map=self._nrpn_name_map,
                    section=section_info,
                    bar=composition_ref._builder_bar,
                    conductor=composition_ref.conductor,
                    rng=self._rng,
                    tweaks=self._tweaks,
                    default_grid=self._default_grid,
                    data=composition_ref.data,
                    # The effective key/scale re-anchors key-relative content
                    # (degrees, romans, generated material) to the section /
                    # form / composition tier in force — mode travels too.
                    key=effective_key,
                    scale=effective_scale,
                    time_signature=composition_ref.time_signature,
                    held_notes=composition_ref._sequencer._held_notes,
                    harmony=harmony_view,
                    section_motifs=composition_ref._section_motifs,
                    energy=energy,
                )

                try:
                    if self._wants_chord:
                        # The two-parameter convention: the injected chord is
                        # the cycle-start snapshot from the window (falling
                        # back to the engine before the clock has run).
                        chord = (
                            harmony_view.chord
                            if harmony_view is not None
                            else (
                                composition_ref._harmonic_state.get_current_chord()
                                if composition_ref._harmonic_state is not None
                                else None
                            )
                        )

                        if chord is not None:
                            injected = _InjectedChord(
                                chord,
                                self._voice_leading_state,
                                next_chord=harmony_view.next_chord
                                if harmony_view is not None
                                else None,
                                beats_remaining=harmony_view.until_change
                                if harmony_view is not None
                                else None,
                            )
                            self._builder_fn(builder, injected)
                        else:
                            self._builder_fn(builder)

                    else:
                        self._builder_fn(builder)

                except Exception:
                    # Discard whatever the builder placed before it raised —
                    # otherwise a half-built pattern plays and the log lies.
                    self.steps = {}
                    self.cc_events = []
                    self.osc_events = []
                    self.raw_note_events = []
                    logger.exception(
                        "Error in pattern builder '%s' (cycle %d) - pattern will be silent this cycle",
                        self._builder_fn.__name__,
                        current_cycle,
                    )

                # Auto-apply global tuning if set and not already applied by the builder.
                if (
                    composition_ref._tuning is not None
                    and not builder._tuning_applied
                    and not (
                        composition_ref._tuning_exclude_drums and self._drum_note_map
                    )
                ):
                    import subsequence.tuning as _tuning_mod

                    _tuning_mod.apply_tuning_to_pattern(
                        self,
                        composition_ref._tuning,
                        bend_range=composition_ref._tuning_bend_range,
                        channels=composition_ref._tuning_channels,
                        reference_note=composition_ref._tuning_reference_note,
                    )

            def on_reschedule(self) -> None:
                """
                Rebuild the pattern from the builder function before the next cycle.
                """

                self._rebuild()

        return _DecoratorPattern(pending, rng)
