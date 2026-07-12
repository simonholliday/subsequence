"""
Motif and Phrase — immutable musical values.

A :class:`Motif` is a short musical figure stored as a value: a frozen tuple
of timed note events (with *specification* pitches — scale degrees, chord
tones, drum names, or absolute MIDI) plus an optional stream of control
gestures (CC sweeps, pitch bends, NRPN/RPN moves), and an explicit length in
beats.  A :class:`Phrase` is a frozen sequence of Motifs whose segmentation
is preserved.

Values are frozen dataclasses: immutable, deterministic to construct,
hashable, printable, and safe to define at module level in a live-coded
file.  They carry no playback position — the engine owns position; values
are placed onto patterns with ``p.motif()`` / ``p.phrase()``.

Pitch is resolved late: a stored :class:`Degree` or :class:`ChordTone`
becomes a MIDI note only at placement, against the key/scale (and, where
applicable, the chord) in effect at that event's own beat.  The same motif
therefore sounds different under different harmony — by design.

The combination algebra:

- ``a + b`` — sequential: a Phrase of the two (segmentation preserved).
- ``a.then(b)`` / ``Motif.join([...])`` — closed sequential concat (one longer Motif).
- ``a & b`` / ``a.stack(b)`` — parallel merge (event union; length = max).
- ``m * n`` — repetition: a Phrase of n segments (``m * 1`` is ``m``).
- ``m.slice(start, end)`` — a window; durations and ramps truncate at the cut.

Transforms are pure and return new values.  Time transforms (``reverse``,
``rotate``, ``stretch``, ``slice``) carry control gestures with them — a
reversed rising sweep becomes a falling one; pitch- and note-scoped
transforms (``transpose``, ``invert``, ``pitched``, ``accent``,
``with_velocity``, ``quantize``) leave control gestures untouched.
"""

import dataclasses
import math
import random
import typing
import warnings

import subsequence.cadences
import subsequence.constants.velocity
import subsequence.easing
import subsequence.intervals
import subsequence.sequence_utils


_DEFAULT_VELOCITY = subsequence.constants.velocity.DEFAULT_VELOCITY

# Degree ints beyond this are almost certainly pasted MIDI note numbers
# (e.g. 60 for middle C), not scale degrees; fail loud rather than emit a
# squeal eight octaves up.
_MAX_PLAUSIBLE_DEGREE = 24

# World-rhythm timelines: name → (onset step indices, grid pulses, default
# voice).  Onset positions are the exact pulse indices catalogued in
# Toussaint, "The Geometry of Musical Rhythm" — the clave family and tresillo/
# cinquillo on a 16- or 8-pulse bar, the West-African bell patterns on 12.
# Read by Motif.preset().  Default voices are General MIDI percussion names
# (so a preset with no pitch= sounds against the standard GM drum map);
# override with pitch= for any other kit.
_WORLD_RHYTHMS: typing.Dict[str, typing.Tuple[typing.Tuple[int, ...], int, str]] = {
    # Cuban clave family (16-pulse bar).
    "son_clave_3_2": ((0, 3, 6, 10, 12), 16, "claves"),
    "son_clave_2_3": ((2, 4, 8, 11, 14), 16, "claves"),
    "rumba_clave_3_2": ((0, 3, 7, 10, 12), 16, "claves"),
    "rumba_clave_2_3": ((2, 4, 8, 11, 15), 16, "claves"),
    "bossa_nova_clave": ((0, 3, 6, 10, 13), 16, "side_stick"),
    # Tresillo / cinquillo (the 3-3-2 family).
    "tresillo": ((0, 3, 6), 8, "low_conga"),
    "tresillo_16": ((0, 6, 12), 16, "low_conga"),
    "cinquillo": ((0, 2, 3, 5, 6), 8, "low_conga"),
    # West-African / Cuban 4-4 bell timelines (16-pulse).
    "shiko": ((0, 4, 6, 10, 12), 16, "cowbell"),
    "soukous": ((0, 3, 6, 10, 11), 16, "cowbell"),
    "gahu": ((0, 3, 6, 10, 14), 16, "cowbell"),
    "samba_necklace": ((0, 3, 5, 7, 10, 12, 14), 16, "side_stick"),
    # The "standard pattern" / bembé bell on a 12-pulse cycle.
    "bembe": ((0, 2, 4, 5, 7, 9, 11), 12, "cowbell"),
    # bembe_euclidean is the specific Toussaint-catalogued Euclidean rotation
    # of the bembé necklace (intervals 2-1-2-2-1-2-2); it differs from this
    # library's own generate_euclidean_sequence(12, 7) default rotation.
    "bembe_euclidean": ((0, 2, 3, 5, 7, 8, 10), 12, "cowbell"),
    # Fume-fume is the FIVE-onset Ghanaian bell — Toussaint catalogues it as
    # a rotation of E(5,12), not the seven-onset standard pattern above.
    "fume_fume": ((0, 2, 4, 7, 9), 12, "cowbell"),
}

_CHORD_TONE_NAMES = {"root": 1, "third": 2, "fifth": 3, "seventh": 4}


# ── Pitch specifications ────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Degree:
    """
    A scale degree — 1-based, resolved against key + scale at placement.

    Degree 1 is the tonic; 8 is the tonic an octave up (steps may exceed the
    scale length and resolve into higher octaves).  ``octave`` shifts whole
    octaves; ``chroma`` is a chromatic offset in semitones (+1 = sharpened).
    """

    step: int
    octave: int = 0
    chroma: int = 0

    def __post_init__(self) -> None:
        """Validate that the degree is 1-based and plausibly a degree."""

        if self.step < 1:
            raise ValueError(f"Degree steps are 1-based (1 = tonic) — got {self.step}")


@dataclasses.dataclass(frozen=True)
class ChordTone:
    """
    An index into the current chord's tones — 1-based, resolved at placement.

    Accepts an int (1 = root, 2 = third, ...) or one of the names
    ``"root"`` / ``"third"`` / ``"fifth"`` / ``"seventh"``.  ``octave``
    shifts whole octaves.
    """

    index: int
    octave: int = 0

    def __init__(self, index_or_name: typing.Union[int, str], octave: int = 0) -> None:
        """Normalize a tone name to its 1-based index."""

        if isinstance(index_or_name, str):
            if index_or_name not in _CHORD_TONE_NAMES:
                raise ValueError(
                    f"Unknown chord tone name '{index_or_name}' — "
                    f"use one of {sorted(_CHORD_TONE_NAMES)} or a 1-based index"
                )
            index = _CHORD_TONE_NAMES[index_or_name]
        else:
            index = index_or_name

        if index < 1:
            raise ValueError(f"Chord tone indices are 1-based (1 = root) — got {index}")

        object.__setattr__(self, "index", index)
        object.__setattr__(self, "octave", octave)


@dataclasses.dataclass(frozen=True)
class Approach:
    """
    A half-step approach into a target pitch at the next chord boundary.

    Resolves at placement, one semitone below its target (the leading-tone
    approach); a ``ChordTone`` target reads the NEXT chord through the
    harmony window, so the approach lands as the harmony arrives.
    """

    target: typing.Union[int, Degree, ChordTone]


# ── Control signals ─────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class CC:
    """A MIDI CC signal — number, or a name resolved at placement via the pattern's ``cc_name_map``."""

    control: typing.Union[int, str]


@dataclasses.dataclass(frozen=True)
class PitchBend:
    """The channel pitch-bend wheel; values are normalised -1.0 to 1.0."""


@dataclasses.dataclass(frozen=True)
class NRPN:
    """An NRPN parameter — number, or a name resolved at placement via the pattern's ``nrpn_name_map``."""

    parameter: typing.Union[int, str]
    fine: bool = False
    null_reset: bool = True


@dataclasses.dataclass(frozen=True)
class RPN:
    """An RPN parameter — number, or one of the standard RPN names (resolved at placement)."""

    parameter: typing.Union[int, str]
    fine: bool = False
    null_reset: bool = True


@dataclasses.dataclass(frozen=True)
class OSC:
    """An OSC address; values are sent as the single float argument."""

    address: str


ControlSignal = typing.Union[CC, PitchBend, NRPN, RPN, OSC]
PitchSpec = typing.Union[int, str, Degree, ChordTone, Approach, None]

_SPEC_RANK = {int: 0, str: 1, Degree: 2, ChordTone: 3, Approach: 4, type(None): 5}
_SIGNAL_RANK = {CC: 0, PitchBend: 1, NRPN: 2, RPN: 3, OSC: 4}


def _pitch_sort_key(pitch: PitchSpec) -> tuple:
    """A total order over heterogeneous pitch specs (for canonical event order)."""

    rank = _SPEC_RANK[type(pitch)]

    if isinstance(pitch, (int, str)):
        return (rank, pitch)
    if isinstance(pitch, Degree):
        return (rank, pitch.step, pitch.octave, pitch.chroma)
    if isinstance(pitch, ChordTone):
        return (rank, pitch.index, pitch.octave)
    if isinstance(pitch, Approach):
        return (rank,) + _pitch_sort_key(pitch.target)

    return (rank,)


def _signal_sort_key(signal: ControlSignal) -> tuple:
    """A total order over control signals (for canonical event order)."""

    rank = _SIGNAL_RANK[type(signal)]

    if isinstance(signal, CC):
        return (rank, str(signal.control))
    if isinstance(signal, (NRPN, RPN)):
        return (rank, str(signal.parameter), signal.fine, signal.null_reset)
    if isinstance(signal, OSC):
        return (rank, signal.address)

    return (rank,)


def _velocity_key(
    velocity: typing.Union[int, typing.Tuple[int, int]],
) -> typing.Tuple[int, int]:
    """Normalise scalar-or-range velocity to a sortable pair."""

    if isinstance(velocity, tuple):
        return (velocity[0], velocity[1])

    return (velocity, velocity)


# ── Events ──────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class MotifEvent:
    """
    One timed note event inside a Motif.

    ``pitch`` is a specification: an absolute MIDI int, a drum name string,
    a :class:`Degree`, :class:`ChordTone`, or :class:`Approach` — or None
    for a pitch-stripped skeleton event (see :meth:`Motif.rhythm`), which
    must be re-pitched via :meth:`Motif.pitched` before placement.
    ``velocity`` is an int or a ``(low, high)`` random-range tuple.
    """

    beat: float
    pitch: PitchSpec
    velocity: typing.Union[int, typing.Tuple[int, int]] = _DEFAULT_VELOCITY
    duration: float = 0.25
    probability: float = 1.0

    def __post_init__(self) -> None:
        """Validate ranges that are wrong at any placement."""

        if self.duration <= 0:
            raise ValueError(f"Event duration must be positive — got {self.duration}")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                f"Event probability must be 0.0–1.0 — got {self.probability}"
            )

    def _sort_key(self) -> tuple:
        """Canonical ordering key — makes parallel merge order-independent."""

        return (
            self.beat,
            _pitch_sort_key(self.pitch),
            _velocity_key(self.velocity),
            self.duration,
            self.probability,
        )


@dataclasses.dataclass(frozen=True)
class ControlEvent:
    """
    One timed control gesture inside a Motif: a discrete write or a shaped ramp.

    A discrete write has ``end=None`` and ``span=0.0``; a ramp interpolates
    ``start`` → ``end`` over ``span`` beats through the easing ``shape``.
    Pulse density (``resolution=``) is deliberately not stored here — beats
    and shapes are music; MIDI traffic density is set at the placement call.
    """

    beat: float
    signal: ControlSignal
    start: float
    end: typing.Optional[float] = None
    span: float = 0.0
    shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear"
    probability: float = 1.0

    def __post_init__(self) -> None:
        """Validate the discrete/ramp invariants."""

        if (self.end is None) != (self.span == 0.0):
            raise ValueError(
                "A ramp needs both end= and span= (a discrete write has neither)"
            )
        if self.span < 0:
            raise ValueError(f"Ramp span must be non-negative — got {self.span}")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                f"Event probability must be 0.0–1.0 — got {self.probability}"
            )

    def _sort_key(self) -> tuple:
        """Canonical ordering key — makes parallel merge order-independent."""

        end = self.start if self.end is None else self.end
        return (
            self.beat,
            _signal_sort_key(self.signal),
            self.start,
            end,
            self.span,
            self.probability,
        )

    def _value_at(self, fraction: float) -> float:
        """The interpolated value at a 0–1 fraction through the ramp."""

        if self.end is None:
            return self.start

        easing_fn = (
            self.shape
            if callable(self.shape)
            else subsequence.easing.get_easing(self.shape)
        )
        return self.start + (self.end - self.start) * easing_fn(
            max(0.0, min(1.0, fraction))
        )


def _expand(name: str, value: typing.Any, n: int) -> list:
    """Expand a scalar parameter to n values, or validate a per-event list."""

    if (
        isinstance(value, (int, float, str))
        or value is None
        or isinstance(value, tuple)
    ):
        return [value] * n

    result = list(value)

    if len(result) != n:
        raise ValueError(
            f"{name} has {len(result)} values for {n} events — parallel lists must match"
        )

    return result


def _computed_length(
    events: typing.Iterable[MotifEvent], controls: typing.Iterable[ControlEvent]
) -> float:
    """Default length: the next whole beat at or after the last sounding moment."""

    ends = [e.beat + e.duration for e in events] + [c.beat + c.span for c in controls]
    return float(math.ceil(max(ends))) if ends else 0.0


# ── Motif ───────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Motif:
    """
    An immutable musical figure: timed note events + control gestures + a length in beats.

    Construct via the classmethods (:meth:`degrees`, :meth:`notes`,
    :meth:`hits`, :meth:`steps`, :meth:`euclidean`, the control-gesture
    constructors, or :meth:`from_events`) rather than positionally.
    ``length`` is explicit — a trailing rest is meaningful.
    """

    events: typing.Tuple[MotifEvent, ...]
    length: float
    controls: typing.Tuple[ControlEvent, ...] = ()
    fit: typing.Optional[float] = (
        None  # placement default for the fit dial; set by generate()
    )

    def __post_init__(self) -> None:
        """Validate, and normalise both streams to canonical order."""

        if self.length < 0:
            raise ValueError(f"Motif length must be non-negative — got {self.length}")

        object.__setattr__(
            self, "events", tuple(sorted(self.events, key=MotifEvent._sort_key))
        )
        object.__setattr__(
            self, "controls", tuple(sorted(self.controls, key=ControlEvent._sort_key))
        )

    # ── constructors ────────────────────────────────────────────────────

    @classmethod
    def empty(cls) -> "Motif":
        """The empty motif (zero events, zero length) — the identity for ``then``."""

        return cls(events=(), length=0.0)

    @classmethod
    def from_events(
        cls,
        events: typing.Iterable[MotifEvent],
        length: typing.Optional[float] = None,
        controls: typing.Iterable[ControlEvent] = (),
    ) -> "Motif":
        """Build a motif from explicit events (power use; length defaults to the next whole beat)."""

        events = tuple(events)
        controls = tuple(controls)

        return cls(
            events=events,
            length=_computed_length(events, controls) if length is None else length,
            controls=controls,
        )

    @classmethod
    def _from_sequence(
        cls,
        pitches: typing.List[PitchSpec],
        beats: typing.Optional[typing.List[float]],
        velocities: typing.Any,
        durations: typing.Any,
        probabilities: typing.Any,
        length: typing.Optional[float],
    ) -> "Motif":
        """Shared core: one event per element, None = rest (slot still advances)."""

        n = len(pitches)
        onsets = list(beats) if beats is not None else [float(i) for i in range(n)]

        if len(onsets) != n:
            raise ValueError(
                f"beats has {len(onsets)} onsets for {n} elements — parallel lists must match"
            )

        velocity_list = _expand("velocities", velocities, n)
        duration_list = _expand("durations", durations, n)
        probability_list = _expand("probabilities", probabilities, n)

        events = tuple(
            MotifEvent(
                beat=float(onsets[i]),
                pitch=pitches[i],
                velocity=velocity_list[i],
                duration=float(duration_list[i]),
                probability=float(probability_list[i]),
            )
            for i in range(n)
            if pitches[i] is not None
        )

        return cls(
            events=events,
            length=_computed_length(events, ()) if length is None else float(length),
        )

    @classmethod
    def degrees(
        cls,
        degrees: typing.List[typing.Union[int, Degree, None]],
        beats: typing.Optional[typing.List[float]] = None,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 1.0,
        probabilities: typing.Any = 1.0,
        length: typing.Optional[float] = None,
    ) -> "Motif":
        """
        A melody written as 1-based scale degrees, one per beat by default.

        Elements are ints (1 = tonic, 8 = tonic an octave up), ``None`` for a
        rest (the beat slot still advances), or :class:`Degree` for octave/
        chromatic detail.  Resolved against key + scale at placement.
        Durations default to a full beat (each note holds its slot).
        """

        converted: typing.List[PitchSpec] = []

        for element in degrees:
            if isinstance(element, int):
                if element > _MAX_PLAUSIBLE_DEGREE:
                    raise ValueError(
                        f"Degree {element} is implausibly large — scale degrees are 1-based "
                        f"(8 = tonic an octave up). For MIDI note numbers use Motif.notes()."
                    )
                converted.append(Degree(element))
            elif isinstance(element, Degree) or element is None:
                converted.append(element)
            else:
                raise TypeError(
                    f"Motif.degrees takes ints, Degree, or None — got {type(element).__name__}"
                )

        return cls._from_sequence(
            converted, beats, velocities, durations, probabilities, length
        )

    @classmethod
    def notes(
        cls,
        notes: typing.List[typing.Union[int, None]],
        beats: typing.Optional[typing.List[float]] = None,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 1.0,
        probabilities: typing.Any = 1.0,
        length: typing.Optional[float] = None,
    ) -> "Motif":
        """A melody written as absolute MIDI note numbers (60 = middle C); ``None`` = rest."""

        for element in notes:
            # bool is a subclass of int, but True/False are never MIDI notes.
            if isinstance(element, bool) or not (
                isinstance(element, int) or element is None
            ):
                raise TypeError(
                    f"Motif.notes takes MIDI ints or None — got {type(element).__name__}"
                )

        return cls._from_sequence(
            list(notes), beats, velocities, durations, probabilities, length
        )

    @classmethod
    def hits(
        cls,
        pitch: typing.Union[int, str],
        beats: typing.List[float],
        length: typing.Optional[float] = None,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 0.1,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """One pitch (usually a drum name) at a list of beat positions — the ``hit()`` convention."""

        return cls._from_sequence(
            [pitch] * len(beats),
            list(beats),
            velocities,
            durations,
            probabilities,
            length,
        )

    @classmethod
    def steps(
        cls,
        steps: typing.List[int],
        pitches: typing.Any,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 0.1,
        probabilities: typing.Any = 1.0,
        step_duration: float = 0.25,
        length: typing.Optional[float] = None,
    ) -> "Motif":
        """
        Grid placement — the ``sequence()`` convention: ``steps`` are 0-based
        grid indices (sixteenths by default), ``pitches`` a scalar or
        parallel list of MIDI ints or drum names.
        """

        n = len(steps)
        pitch_list = _expand("pitches", pitches, n)
        onsets = [s * step_duration for s in steps]

        if length is None and n:
            length = float(math.ceil((max(steps) + 1) * step_duration))

        return cls._from_sequence(
            pitch_list, onsets, velocities, durations, probabilities, length
        )

    @classmethod
    def euclidean(
        cls,
        pulses: int,
        steps: int,
        pitch: typing.Union[int, str],
        length: float = 4.0,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 0.1,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """A euclidean rhythm as a value: *pulses* spread evenly across *steps* over *length* beats."""

        # bool is a subclass of int, but True/False are never MIDI notes.
        if isinstance(pitch, bool):
            raise TypeError(
                f"Motif.euclidean takes a MIDI int or drum name for pitch — got {pitch!r}"
            )

        # The kernel returns one 0/1 flag per grid step; onsets are the 1s.
        # It validates pulses first, so pulses > steps still raises clearly.
        flags = subsequence.sequence_utils.generate_euclidean_sequence(
            steps=steps, pulses=pulses
        )

        if steps <= 0:
            # A grid of zero steps holds no onsets — an empty motif of the given
            # length, matching pulses=0 on a real grid (the empty-input policy).
            return cls._from_sequence(
                [], [], velocities, durations, probabilities, length
            )

        step_duration = length / steps
        onsets = [i * step_duration for i, flag in enumerate(flags) if flag]

        return cls._from_sequence(
            [pitch] * len(onsets),
            onsets,
            velocities,
            durations,
            probabilities,
            length,
        )

    @classmethod
    def preset(
        cls,
        name: str,
        pitch: typing.Optional[typing.Union[int, str]] = None,
        length: float = 4.0,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 0.1,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """A named world-rhythm timeline as a value — ``Motif.preset("son_clave_3_2")``.

        Looks a curated timeline up in the world-rhythm table (clave family,
        West-African bell patterns, tresillo/cinquillo, samba) and lays its
        onsets across *length* beats.  Onset positions are exact pulse indices
        from Toussaint's "The Geometry of Musical Rhythm"; each preset declares
        its own grid (16 for the clave/4-4 timelines, 12 for the bell
        patterns) and a default drum voice.

        Parameters:
                name: A preset name (``KeyError``-style ValueError lists them all).
                pitch: The voice — a drum name or MIDI int; defaults to the
                        preset's General-MIDI voice (``"claves"``, ``"cowbell"``,
                        ``"side_stick"``, ``"low_conga"``), so it sounds against the
                        standard GM drum map without a ``pitch=``.
                length: Total beats the cycle spans (4 = one common-time bar).
                velocities / durations / probabilities: The parallel-list params.

        Returns:
                A drum/pitched :class:`Motif` of the timeline's onsets.

        Raises:
                ValueError: If *name* is not a known preset.

        Example:
                ```python
                clave = subsequence.Motif.preset("son_clave_3_2")              # GM "claves"
                bell  = subsequence.Motif.preset("bembe", pitch="cowbell")     # 12-pulse
                ```
        """

        if name not in _WORLD_RHYTHMS:
            known = ", ".join(sorted(_WORLD_RHYTHMS))
            raise ValueError(f"Unknown rhythm preset {name!r}. Known presets: {known}.")

        steps, grid, voice = _WORLD_RHYTHMS[name]

        return cls.steps(
            steps=list(steps),
            pitches=pitch if pitch is not None else voice,
            velocities=velocities,
            durations=durations,
            probabilities=probabilities,
            step_duration=length / grid,
            length=length,
        )

    # ── control-gesture constructors (mirror the pattern_midi verbs) ────

    @classmethod
    def _control_writes(
        cls,
        signal: ControlSignal,
        values: typing.List[float],
        beats: typing.List[float],
        length: typing.Optional[float],
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """Shared core for discrete control writes."""

        if len(values) != len(beats):
            raise ValueError(
                f"values has {len(values)} entries for {len(beats)} beats — parallel lists must match"
            )

        probability_list = _expand("probabilities", probabilities, len(values))

        controls = tuple(
            ControlEvent(
                beat=float(beats[i]),
                signal=signal,
                start=float(values[i]),
                probability=float(probability_list[i]),
            )
            for i in range(len(values))
        )

        return cls(
            events=(),
            length=_computed_length((), controls) if length is None else float(length),
            controls=controls,
        )

    @classmethod
    def _control_ramp(
        cls,
        signal: ControlSignal,
        start: float,
        end: float,
        beat_start: float,
        beat_end: typing.Optional[float],
        shape: typing.Union[str, "subsequence.easing.EasingFn"],
        length: typing.Optional[float],
        probability: float = 1.0,
    ) -> "Motif":
        """Shared core for shaped control ramps."""

        if beat_end is None:
            if length is None:
                raise ValueError(
                    "A ramp needs beat_end= (or length=, which beat_end defaults to)"
                )
            beat_end = float(length)

        if beat_end <= beat_start:
            raise ValueError(
                f"beat_end ({beat_end}) must be after beat_start ({beat_start})"
            )

        controls = (
            ControlEvent(
                beat=float(beat_start),
                signal=signal,
                start=float(start),
                end=float(end),
                span=float(beat_end) - float(beat_start),
                shape=shape,
                probability=probability,
            ),
        )

        return cls(
            events=(),
            length=float(math.ceil(beat_end)) if length is None else float(length),
            controls=controls,
        )

    @classmethod
    def cc(
        cls,
        control: typing.Union[int, str],
        values: typing.List[int],
        beats: typing.List[float],
        length: typing.Optional[float] = None,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """Discrete CC writes at beat positions — mirrors ``p.cc()``; names resolve at placement."""

        return cls._control_writes(
            CC(control), list(values), list(beats), length, probabilities
        )

    @classmethod
    def cc_ramp(
        cls,
        control: typing.Union[int, str],
        start: int,
        end: int,
        beat_start: float = 0.0,
        beat_end: typing.Optional[float] = None,
        shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear",
        length: typing.Optional[float] = None,
        probability: float = 1.0,
    ) -> "Motif":
        """A CC value swept ``start`` → ``end`` over a beat range — mirrors ``p.cc_ramp()``."""

        return cls._control_ramp(
            CC(control), start, end, beat_start, beat_end, shape, length, probability
        )

    @classmethod
    def pitch_bend(
        cls,
        values: typing.List[float],
        beats: typing.List[float],
        length: typing.Optional[float] = None,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """Discrete pitch-bend writes (-1.0 to 1.0) at beat positions — mirrors ``p.pitch_bend()``."""

        return cls._control_writes(
            PitchBend(), list(values), list(beats), length, probabilities
        )

    @classmethod
    def pitch_bend_ramp(
        cls,
        start: float,
        end: float,
        beat_start: float = 0.0,
        beat_end: typing.Optional[float] = None,
        shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear",
        length: typing.Optional[float] = None,
        probability: float = 1.0,
    ) -> "Motif":
        """Pitch bend swept ``start`` → ``end`` (-1.0 to 1.0) over a beat range — mirrors ``p.pitch_bend_ramp()``."""

        return cls._control_ramp(
            PitchBend(), start, end, beat_start, beat_end, shape, length, probability
        )

    @classmethod
    def nrpn(
        cls,
        parameter: typing.Union[int, str],
        values: typing.List[int],
        beats: typing.List[float],
        fine: bool = False,
        null_reset: bool = True,
        length: typing.Optional[float] = None,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """Discrete NRPN parameter writes at beat positions — mirrors ``p.nrpn()``."""

        return cls._control_writes(
            NRPN(parameter, fine=fine, null_reset=null_reset),
            list(values),
            list(beats),
            length,
            probabilities,
        )

    @classmethod
    def nrpn_ramp(
        cls,
        parameter: typing.Union[int, str],
        start: int,
        end: int,
        beat_start: float = 0.0,
        beat_end: typing.Optional[float] = None,
        shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear",
        fine: bool = True,
        null_reset: bool = True,
        length: typing.Optional[float] = None,
        probability: float = 1.0,
    ) -> "Motif":
        """An NRPN value swept over a beat range — mirrors ``p.nrpn_ramp()``."""

        return cls._control_ramp(
            NRPN(parameter, fine=fine, null_reset=null_reset),
            start,
            end,
            beat_start,
            beat_end,
            shape,
            length,
            probability,
        )

    @classmethod
    def rpn(
        cls,
        parameter: typing.Union[int, str],
        values: typing.List[int],
        beats: typing.List[float],
        fine: bool = False,
        null_reset: bool = True,
        length: typing.Optional[float] = None,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """Discrete RPN parameter writes at beat positions — mirrors ``p.rpn()``."""

        return cls._control_writes(
            RPN(parameter, fine=fine, null_reset=null_reset),
            list(values),
            list(beats),
            length,
            probabilities,
        )

    @classmethod
    def rpn_ramp(
        cls,
        parameter: typing.Union[int, str],
        start: int,
        end: int,
        beat_start: float = 0.0,
        beat_end: typing.Optional[float] = None,
        shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear",
        fine: bool = True,
        null_reset: bool = True,
        length: typing.Optional[float] = None,
        probability: float = 1.0,
    ) -> "Motif":
        """An RPN value swept over a beat range — mirrors ``p.rpn_ramp()``."""

        return cls._control_ramp(
            RPN(parameter, fine=fine, null_reset=null_reset),
            start,
            end,
            beat_start,
            beat_end,
            shape,
            length,
            probability,
        )

    @classmethod
    def osc(
        cls,
        address: str,
        values: typing.List[float],
        beats: typing.List[float],
        length: typing.Optional[float] = None,
        probabilities: typing.Any = 1.0,
    ) -> "Motif":
        """Discrete OSC float sends at beat positions — mirrors ``p.osc()``."""

        return cls._control_writes(
            OSC(address), list(values), list(beats), length, probabilities
        )

    @classmethod
    def osc_ramp(
        cls,
        address: str,
        start: float,
        end: float,
        beat_start: float = 0.0,
        beat_end: typing.Optional[float] = None,
        shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear",
        length: typing.Optional[float] = None,
        probability: float = 1.0,
    ) -> "Motif":
        """An OSC float swept over a beat range — mirrors ``p.osc_ramp()``."""

        return cls._control_ramp(
            OSC(address), start, end, beat_start, beat_end, shape, length, probability
        )

    # ── the algebra ─────────────────────────────────────────────────────

    def then(self, other: "Motif") -> "Motif":
        """Closed sequential concat: glue *other* after this motif into ONE longer motif."""

        if not isinstance(other, Motif):
            raise TypeError(f"then() takes a Motif — got {type(other).__name__}")

        return Motif(
            events=self.events
            + tuple(
                dataclasses.replace(e, beat=e.beat + self.length) for e in other.events
            ),
            length=self.length + other.length,
            controls=self.controls
            + tuple(
                dataclasses.replace(c, beat=c.beat + self.length)
                for c in other.controls
            ),
            # fit is a dial, not content: keep ours, inherit the other's when
            # we have none — join()/tiling folds from empty() (fit=None), and
            # must not silently strip a generated motif's chord-snapping.
            fit=self.fit if self.fit is not None else other.fit,
        )

    @classmethod
    def join(cls, motifs: typing.Iterable["Motif"]) -> "Motif":
        """Fold a list of motifs into one with ``then`` (empty list → ``Motif.empty()``)."""

        result = cls.empty()

        for m in motifs:
            result = result.then(m)

        return result

    @classmethod
    def generate(
        cls,
        rhythm: typing.Any,
        length: typing.Optional[float] = None,
        scale: typing.Optional[typing.Union[str, typing.Sequence[int]]] = None,
        contour: typing.Optional[str] = None,
        end_on: typing.Optional[typing.Union[int, Degree]] = None,
        cadence: typing.Optional[str] = None,
        pins: typing.Optional[typing.Dict[int, typing.Union[int, Degree]]] = None,
        max_pitches: typing.Optional[int] = None,
        velocities: typing.Any = _DEFAULT_VELOCITY,
        durations: typing.Any = 0.25,
        seed: typing.Optional[int] = None,
        rng: typing.Optional[random.Random] = None,
        state: typing.Optional[typing.Any] = None,
        nir_strength: float = 0.5,
        pitch_diversity: float = 0.6,
        tessitura_strength: float = 0.6,
    ) -> "Motif":
        """Generate a melodic motif — rhythm first, pitches walked, a value out.

        The melody engine emitting a value: you give the **rhythm** (an onset
        list in beats, or another motif whose rhythm to borrow — cross-pattern
        rhythm reuse is shared values); the engine walks pitches over it
        through the soft scoring factors (NIR expectation, contour envelope,
        tessitura regression, diversity), honouring any pins.

        The result emits **scale degrees** (resolved at placement against the
        composition key/scale), so a generated hook transposes, varies, and
        develops like a hand-written one.  ``scale=`` constrains *candidate
        choice only*: a name or interval list masks which pitches the walk
        may use, spelled relative to its best-fit reference (major or minor)
        — bind it in a composition whose scale matches that family and
        resolution is exact.  An explicit MIDI pitch pool (a list of note
        numbers) switches to absolute output (the sieve/atonal path).

        Parameters:
                rhythm: Onset beats (``[0, 1, 1.5, 1.75, 2.5]``) or a Motif
                        (its onsets are borrowed).
                length: Motif length in beats; defaults to the onsets rounded
                        up to a whole 4-beat bar.
                scale: A scale name, an interval list, or an explicit MIDI
                        pitch pool.  ``None`` = the plain seven degrees.
                contour: Envelope shaping the line's height over its span —
                        ``"arch"``, ``"valley"``, ``"ascending"``, ``"descending"``.
                end_on: Degree the line must end on — sugar for ``pins={-1: ...}``.
                        Degree semantics: raises with an explicit MIDI pool (pin the
                        exact note instead).
                cadence: A cadence name (``"strong"``/``"soft"``/``"open"``/
                        ``"fakeout"``) — the line closes on that cadence's melodic
                        degree (1 for the full closes and the fakeout, 5 for the
                        open half).  Sugar for ``end_on=``; conflicts with it, and
                        raises with an explicit MIDI pool like ``end_on=``.
                pins: ``{position: degree}`` — 1-based note positions (``-1`` =
                        the last, the Python idiom); the engine fills between.  With
                        an explicit MIDI pool there are no degrees to read, so each
                        pin is the exact MIDI note to play (``Degree`` pins raise).
                max_pitches: Cap on distinct pitches (a tight pool is a hook);
                        keeps the most central candidates.
                velocities / durations: Scalar or per-note list (the parallel-
                        list convention).
                seed: Seed for the walk (required or warned — module-level
                        nondeterminism breaks live reload).
                rng: Explicit stream (overrides ``seed``).
                state: A ``MelodicState`` whose dials, scoring factors, and
                        melodic history seed the walk.  It is **copied** — building
                        a value never mutates a module-level live object.  The
                        candidate pool is not carried over: it is always rebuilt
                        from ``scale=`` (pass an explicit pool there instead),
                        though the state's key still sets the tonic that the NIR
                        closure rule lands on.
                nir_strength / pitch_diversity / tessitura_strength: The walk's
                        dials when no ``state`` is given.

        Example:
                ```python
                hook = subsequence.Motif.generate(
                        rhythm=[0, 1, 1.5, 1.75, 2.5], scale="minor_pentatonic",
                        contour="arch", end_on=1, seed=7,
                )
                ```
        """

        import subsequence.melodic_state

        onsets = (
            list(rhythm.onsets())
            if hasattr(rhythm, "onsets")
            else [float(b) for b in rhythm]
        )

        if cadence is not None:
            if end_on is not None:
                raise ValueError(
                    "cadence= already names the close degree — it conflicts with end_on="
                )
            end_on = subsequence.cadences.cadence_formula(cadence).close_degree

        if not onsets:
            raise ValueError(
                "generate() needs at least one onset — the rhythm comes first"
            )
        if sorted(onsets) != onsets:
            raise ValueError("rhythm onsets must ascend")

        if length is None:
            length = max(4.0, math.ceil((onsets[-1] + 1e-9) / 4.0) * 4.0)
        if onsets[-1] >= length:
            raise ValueError(
                f"the last onset ({onsets[-1]:g}) falls outside length={length:g}"
            )

        if rng is None:
            if seed is None:
                warnings.warn(
                    "generate() without seed= is nondeterministic — pass seed= so the "
                    "value survives live reload",
                    stacklevel=2,
                )
                rng = random.Random()
            else:
                rng = random.Random(seed)

        # --- The candidate pool ------------------------------------------------
        absolute_pool: typing.Optional[typing.List[int]] = None
        intervals: typing.List[int]

        if scale is None:
            intervals = list(subsequence.intervals.scale_pitch_classes(0, "ionian"))
        elif isinstance(scale, str):
            intervals = list(subsequence.intervals.scale_pitch_classes(0, scale))
        else:
            values = [int(v) for v in scale]
            if values and (min(values) != 0 or max(values) > 11):
                absolute_pool = sorted(values)  # an explicit MIDI pool: absolute output
                intervals = []
            else:
                intervals = sorted(set(values))

        # Best-fit reference scale for degree spelling: whichever of major/
        # minor contains more of the pool (ties to major).  Bound under a
        # matching composition scale, resolution is exact.
        if absolute_pool is None:
            ionian = set(subsequence.intervals.scale_pitch_classes(0, "ionian"))
            aeolian = set(subsequence.intervals.scale_pitch_classes(0, "minor"))
            reference_name = (
                "minor"
                if sum(i in aeolian for i in intervals)
                > sum(i in ionian for i in intervals)
                else "ionian"
            )
            reference = list(
                subsequence.intervals.scale_pitch_classes(0, reference_name)
            )

        # --- The walking state (copied, never mutated in place) ----------------
        if state is not None:
            walker = state.clone()
            walker.rest_probability = (
                0.0  # generate is rhythm-first: every onset gets a
            )
        # note, so the walker never rests (and never falls
        # back to a stuck repeat) — rests come from the rhythm
        else:
            walker = subsequence.melodic_state.MelodicState(
                nir_strength=nir_strength,
                pitch_diversity=pitch_diversity,
                tessitura_strength=tessitura_strength,
                chord_weight=0.0,  # values have no chord context; fit applies at placement
            )

        if absolute_pool is not None:
            walker.set_pool(absolute_pool)
        else:
            # Offsets over ~1.5 octaves anchored at 60 — register is decided
            # at placement (root=), so the anchor is arbitrary and erased.
            walker.set_pool(
                [
                    60 + octave * 12 + interval
                    for octave in (0, 1)
                    for interval in intervals
                    if octave * 12 + interval <= 19
                ]
            )

        if max_pitches is not None:
            if max_pitches < 1:
                raise ValueError("max_pitches must be at least 1")
            pool = sorted(walker._pitch_pool)
            centre = pool[len(pool) // 2]
            walker.set_pool(
                sorted(sorted(pool, key=lambda p: (abs(p - centre), p))[:max_pitches])
            )

        # --- Pins ---------------------------------------------------------------
        resolved_pins: typing.Dict[int, int] = {}
        combined = dict(pins or {})

        # cadence=/end_on= name scale DEGREES — meaningless against an explicit
        # MIDI pool, where they would silently land as raw (sub-audio) note
        # numbers.
        if absolute_pool is not None and end_on is not None:
            raise ValueError(
                "cadence=/end_on= name scale degrees, but this motif uses an "
                "explicit MIDI pool — pin the exact closing note instead: "
                "pins={-1: <midi note>}"
            )

        if end_on is not None:
            if -1 in combined or len(onsets) in combined:
                raise ValueError(
                    "end_on conflicts with a pin on the last note — they name the same position"
                )
            combined[-1] = end_on

        for pin_position, pin_spec in combined.items():
            if not isinstance(pin_position, int) or isinstance(pin_position, bool):
                raise ValueError(
                    f"pin positions are 1-based ints (or -1 for last), got {pin_position!r}"
                )
            index = (
                pin_position - 1 if pin_position >= 1 else len(onsets) + pin_position
            )
            if not 0 <= index < len(onsets):
                raise ValueError(
                    f"pin position {pin_position} is outside the {len(onsets)}-note rhythm"
                )
            if absolute_pool is not None:
                # A raw int pins the exact MIDI note; a Degree has no meaning
                # here (the pool defines no scale to read it against).
                if not isinstance(pin_spec, int) or isinstance(pin_spec, bool):
                    raise ValueError(
                        f"pin {pin_spec!r} is a scale degree, but this motif uses an "
                        "explicit MIDI pool — pin the exact MIDI note instead "
                        "(e.g. pins={-1: 52})"
                    )
                resolved_pins[index] = int(pin_spec)
            else:
                degree = (
                    pin_spec if isinstance(pin_spec, Degree) else Degree(int(pin_spec))
                )
                step_index = (degree.step - 1) % len(reference)
                carry = (degree.step - 1) // len(reference)
                resolved_pins[index] = (
                    60
                    + reference[step_index]
                    + 12 * (carry + degree.octave)
                    + degree.chroma
                )

        # --- The walk -----------------------------------------------------------
        envelopes: typing.Dict[str, typing.Callable[[float], float]] = {
            "arch": lambda pos: 0.15 + 0.8 * math.sin(math.pi * pos),
            "valley": lambda pos: 0.95 - 0.8 * math.sin(math.pi * pos),
            "ascending": lambda pos: 0.1 + 0.85 * pos,
            "descending": lambda pos: 0.95 - 0.85 * pos,
        }

        if contour is not None and contour not in envelopes:
            known = ", ".join(sorted(envelopes))
            raise ValueError(f"unknown contour {contour!r} — expected one of: {known}")

        chosen_pitches: typing.List[int] = []

        for index, onset in enumerate(onsets):
            if index in resolved_pins:
                pitch = resolved_pins[index]
                walker.record(pitch)  # pins enter the NIR context like chosen notes
            else:
                span_position = index / (len(onsets) - 1) if len(onsets) > 1 else 0.0
                target = (
                    envelopes[contour](span_position) if contour is not None else None
                )
                picked = walker.choose_next(
                    None, rng, beat=onset, position=span_position, contour_target=target
                )
                pitch = picked if picked is not None else walker._pitch_pool[0]

            chosen_pitches.append(pitch)

        # --- Emission ------------------------------------------------------------
        velocity_values = _expand("velocities", velocities, len(onsets))
        duration_values = _expand("durations", durations, len(onsets))

        events = []

        for index, (onset, pitch) in enumerate(zip(onsets, chosen_pitches)):
            spec: PitchSpec

            if absolute_pool is not None:
                spec = pitch
            else:
                offset = pitch - 60
                octave, pc = divmod(offset, 12)
                if pc in reference:
                    spec = Degree(reference.index(pc) + 1, octave=octave)
                elif (pc + 1) % 12 in reference and pc + 1 <= 11:
                    spec = Degree(reference.index(pc + 1) + 1, octave=octave, chroma=-1)
                else:
                    spec = Degree(reference.index(pc - 1) + 1, octave=octave, chroma=1)

            events.append(
                MotifEvent(
                    beat=onset,
                    pitch=spec,
                    velocity=velocity_values[index],
                    duration=float(duration_values[index]),
                )
            )

        return cls(events=tuple(events), length=float(length), fit=0.7)

    def stack(self, other: typing.Union["Motif", "Phrase"]) -> "Motif":
        """
        Parallel merge (the spelled form of ``&``): event union, length = max.

        No implicit tiling — a short gesture stacked under a long figure
        plays once.  Phrase operands flatten first.
        """

        if isinstance(other, Phrase):
            merged = other.flatten()
        elif isinstance(other, Motif):
            merged = other
        else:
            raise TypeError(
                f"stack() takes a Motif or Phrase — got {type(other).__name__}"
            )

        return Motif(
            events=self.events + merged.events,
            length=max(self.length, merged.length),
            controls=self.controls + merged.controls,
            fit=self.fit,
        )

    def slice(self, start: float, end: float) -> "Motif":
        """
        A window onto the motif, on its own authority: events starting outside
        are dropped; durations and ramp spans truncate at the cut (a truncated
        ramp ends at its interpolated cut value).  Beats shift so the window
        starts at 0.
        """

        if end <= start:
            raise ValueError(f"slice end ({end}) must be after start ({start})")

        events = tuple(
            dataclasses.replace(
                e, beat=e.beat - start, duration=min(e.duration, end - e.beat)
            )
            for e in self.events
            if start <= e.beat < end
        )

        controls = []

        for c in self.controls:
            if not (start <= c.beat < end):
                continue
            if c.end is not None and c.beat + c.span > end:
                kept = end - c.beat
                controls.append(
                    dataclasses.replace(
                        c,
                        beat=c.beat - start,
                        span=kept,
                        end=c._value_at(kept / c.span),
                    )
                )
            else:
                controls.append(dataclasses.replace(c, beat=c.beat - start))

        return Motif(
            events=events, length=end - start, controls=tuple(controls), fit=self.fit
        )

    def __add__(self, other: typing.Any) -> "Phrase":
        """``a + b`` — sequential: a two-segment Phrase (segmentation preserved)."""

        if isinstance(other, Motif):
            return Phrase((self, other))

        return NotImplemented

    def __mul__(self, count: int) -> typing.Union["Motif", "Phrase"]:
        """``m * n`` — repetition: a Phrase of n segments; ``m * 1`` is ``m``; ``m * 0`` is empty."""

        if not isinstance(count, int):
            return NotImplemented
        if count < 0:
            raise ValueError(f"Repetition count must be non-negative — got {count}")
        if count == 0:
            return Motif.empty()
        if count == 1:
            return self

        return Phrase((self,) * count)

    __rmul__ = __mul__

    def __and__(self, other: typing.Any) -> "Motif":
        """``a & b`` — parallel merge; the spelled form is :meth:`stack`."""

        if isinstance(other, (Motif, Phrase)):
            return self.stack(other)

        return NotImplemented

    # ── transforms (pure; control gestures ride time, ignore pitch) ─────

    def reverse(self) -> "Motif":
        """Mirror the figure in time; ramps swap direction (a rising sweep falls)."""

        events = tuple(
            dataclasses.replace(e, beat=max(0.0, self.length - e.beat - e.duration))
            for e in self.events
        )
        controls = tuple(
            dataclasses.replace(
                c,
                beat=max(0.0, self.length - c.beat - c.span),
                start=c.start if c.end is None else c.end,
                end=c.end if c.end is None else c.start,
            )
            for c in self.controls
        )

        return Motif(events=events, length=self.length, controls=controls, fit=self.fit)

    def rotate(self, beats: float) -> "Motif":
        """Shift every onset by *beats*, wrapping modulo the length (spans ride along)."""

        if self.length == 0:
            return self

        events = tuple(
            dataclasses.replace(e, beat=(e.beat + beats) % self.length)
            for e in self.events
        )
        controls = tuple(
            dataclasses.replace(c, beat=(c.beat + beats) % self.length)
            for c in self.controls
        )

        return Motif(events=events, length=self.length, controls=controls, fit=self.fit)

    def stretch(self, factor: float) -> "Motif":
        """Scale time by *factor* (2.0 = half-time feel): beats, durations, spans, and length."""

        if factor <= 0:
            raise ValueError(f"Stretch factor must be positive — got {factor}")

        events = tuple(
            dataclasses.replace(e, beat=e.beat * factor, duration=e.duration * factor)
            for e in self.events
        )
        controls = tuple(
            dataclasses.replace(c, beat=c.beat * factor, span=c.span * factor)
            for c in self.controls
        )

        return Motif(
            events=events, length=self.length * factor, controls=controls, fit=self.fit
        )

    def quantize(self, grid: float) -> "Motif":
        """Snap note onsets to the nearest multiple of *grid* beats (control gestures untouched).

        An onset exactly midway between grid lines snaps LATER (round half
        up) — every midpoint moves the same way, the predictable behaviour
        for a musician.  (Python's own ``round()`` is half-to-even, which
        made exact midpoints snap in alternating directions.)
        """

        if grid <= 0:
            raise ValueError(f"Quantize grid must be positive — got {grid}")

        events = tuple(
            dataclasses.replace(e, beat=math.floor(e.beat / grid + 0.5) * grid)
            for e in self.events
        )

        return Motif(
            events=events, length=self.length, controls=self.controls, fit=self.fit
        )

    def accent(self, beat: float, amount: int = 20) -> "Motif":
        """Add *amount* velocity to every note at the given beat position (0-based beats)."""

        def boost(
            velocity: typing.Union[int, typing.Tuple[int, int]],
        ) -> typing.Union[int, typing.Tuple[int, int]]:
            # Clamp both ends: a negative amount (a de-accent) must not store
            # a velocity below 1, which MIDI cannot play.
            if isinstance(velocity, tuple):
                return (
                    max(1, min(127, velocity[0] + amount)),
                    max(1, min(127, velocity[1] + amount)),
                )
            return max(1, min(127, velocity + amount))

        events = tuple(
            dataclasses.replace(e, velocity=boost(e.velocity))
            if abs(e.beat - beat) < 1e-9
            else e
            for e in self.events
        )

        return Motif(
            events=events, length=self.length, controls=self.controls, fit=self.fit
        )

    def with_velocity(
        self, velocity: typing.Union[int, typing.Tuple[int, int]]
    ) -> "Motif":
        """Replace every note's velocity (an int, or a ``(low, high)`` random range)."""

        events = tuple(dataclasses.replace(e, velocity=velocity) for e in self.events)

        return Motif(
            events=events, length=self.length, controls=self.controls, fit=self.fit
        )

    def _nudged_pitch(self, pitch: PitchSpec, rng: random.Random) -> PitchSpec:
        """One varied pitch: a small melodic nudge that always changes the note.

        Degrees move by scale steps, MIDI ints by semitones, chord tones by
        index; an Approach's target is nudged.  Drum names raise — a varied
        drum is a different instrument, not a variation.
        """

        if isinstance(pitch, Degree):
            steps = [
                pitch.step + delta
                for delta in (-2, -1, 1, 2)
                if pitch.step + delta >= 1
            ]
            return dataclasses.replace(pitch, step=rng.choice(steps))
        if isinstance(pitch, ChordTone):
            indices = [
                pitch.index + delta for delta in (-1, 1) if pitch.index + delta >= 1
            ]
            return ChordTone(rng.choice(indices), octave=pitch.octave)
        if isinstance(pitch, Approach):
            nudged = self._nudged_pitch(pitch.target, rng)
            if not isinstance(nudged, (int, Degree, ChordTone)):
                raise TypeError(
                    f"cannot vary an Approach aimed at {type(nudged).__name__} content"
                )
            return Approach(nudged)
        if isinstance(pitch, int):
            return pitch + rng.choice((-2, -1, 1, 2))

        raise TypeError(
            f"vary() moves pitches — {type(pitch).__name__} content cannot vary "
            "(a varied drum is a different instrument)"
        )

    def vary(
        self,
        notes: int = 1,
        position: str = "end",
        seed: typing.Optional[int] = None,
        rng: typing.Optional[random.Random] = None,
        keep_contour: bool = False,
    ) -> "Motif":
        """Replace a few pitches, preserving the rhythm — the smallest variation.

        Rhythm, velocities, durations, rests, and control gestures are
        untouched; only the chosen notes' pitches move (by a small melodic
        nudge: scale steps for degrees, semitones for MIDI ints).

        Parameters:
                notes: How many pitched notes to vary (clamped to what exists).
                position: Which notes — ``"end"`` (the tail, the default),
                        ``"start"``, or ``"anywhere"`` (drawn from the stream).
                seed: Seed for the variation.  A standalone vary without a seed
                        warns — module-level nondeterminism breaks live reload.
                rng: An explicit random stream (overrides ``seed``; used by
                        recipe machinery).
                keep_contour: When True, the variation preserves the line's
                        CSEG — every varied note keeps its rank relations with
                        every other note, so the melodic shape is identical (the
                        motif-identity guard).  Where no nudge can preserve the
                        contour, that note stays unchanged — shape wins over
                        motion.

        Example:
                ```python
                answer = call.vary(notes=1, seed=4)     # same figure, new tail note
                ```
        """

        if notes < 0:
            raise ValueError(f"notes must be at least 0, got {notes}")
        if position not in ("end", "start", "anywhere"):
            raise ValueError(
                f'position must be "end", "start", or "anywhere" — got {position!r}'
            )

        if rng is None:
            if seed is None:
                warnings.warn(
                    "vary() without seed= is nondeterministic — pass seed= so the "
                    "value survives live reload",
                    stacklevel=2,
                )
                rng = random.Random()
            else:
                rng = random.Random(seed)

        pitched_indices = [
            index for index, event in enumerate(self.events) if event.pitch is not None
        ]
        count = min(notes, len(pitched_indices))

        if count == 0:
            return self

        if position == "end":
            chosen = pitched_indices[-count:]
        elif position == "start":
            chosen = pitched_indices[:count]
        else:
            chosen = sorted(rng.sample(pitched_indices, count))

        events = list(self.events)

        for index in chosen:
            if keep_contour:
                replacement = self._contour_safe_nudge(
                    events, index, pitched_indices, rng
                )
                if replacement is not None:
                    events[index] = dataclasses.replace(
                        events[index], pitch=replacement
                    )
            else:
                events[index] = dataclasses.replace(
                    events[index], pitch=self._nudged_pitch(events[index].pitch, rng)
                )

        return Motif(
            events=tuple(events),
            length=self.length,
            controls=self.controls,
            fit=self.fit,
        )

    @staticmethod
    def _rank_value(pitch: PitchSpec) -> float:
        """A comparable height for contour ranking (uniform content only)."""

        if isinstance(pitch, Degree):
            return pitch.octave * 7 + pitch.step + 0.4 * pitch.chroma
        if isinstance(pitch, ChordTone):
            return pitch.octave * 4 + pitch.index
        if isinstance(pitch, int):
            return float(pitch)

        raise TypeError(
            f"keep_contour needs rankable pitches — {type(pitch).__name__} content has no height"
        )

    def _contour_safe_nudge(
        self,
        events: typing.List[MotifEvent],
        index: int,
        pitched_indices: typing.List[int],
        rng: random.Random,
    ) -> typing.Optional[PitchSpec]:
        """A nudge for events[index] that preserves its CSEG rank relations.

        Candidates are the usual small nudges, filtered to those keeping the
        note's above/below/equal relation to every other pitched note.  One
        rng draw happens regardless (stream stability); ``None`` means no
        candidate preserves the shape — leave the note alone.
        """

        pitch = events[index].pitch

        if isinstance(pitch, Degree):
            candidates: typing.List[PitchSpec] = [
                dataclasses.replace(pitch, step=pitch.step + delta)
                for delta in (-2, -1, 1, 2)
                if pitch.step + delta >= 1
            ]
        elif isinstance(pitch, int):
            candidates = [pitch + delta for delta in (-2, -1, 1, 2)]
        else:
            raise TypeError(f"keep_contour cannot vary {type(pitch).__name__} content")

        original = self._rank_value(pitch)
        others = [
            (self._rank_value(events[other].pitch), other)
            for other in pitched_indices
            if other != index
        ]

        def preserves(candidate: PitchSpec) -> bool:
            height = self._rank_value(candidate)
            for other_height, _ in others:
                before = (original > other_height) - (original < other_height)
                after = (height > other_height) - (height < other_height)
                if before != after:
                    return False
            return True

        surviving = [candidate for candidate in candidates if preserves(candidate)]

        # One draw either way, so adding keep_contour never shifts the stream
        # consumed by the notes around this one.
        draw = rng.random()

        if not surviving:
            return None

        return surviving[int(draw * len(surviving)) % len(surviving)]

    def answer(self, to: typing.Union[int, Degree] = 1) -> "Motif":
        """Call → response: re-aim the tail to a stable degree.

        The classic consequent move — the figure repeats but its last pitched
        note lands home (degree 1 by default; pass ``to=5`` for a half-close,
        or a full ``Degree`` for register control).  Everything else —
        rhythm, the other pitches, velocities, controls — is untouched.

        Degree content only: absolute MIDI has no degrees to re-aim (build
        the call with ``motif([...])``), and drums raise.
        """

        target = to if isinstance(to, Degree) else Degree(int(to))

        pitched_indices = [
            index for index, event in enumerate(self.events) if event.pitch is not None
        ]

        if not pitched_indices:
            return self

        last = self.events[pitched_indices[-1]]

        if not isinstance(last.pitch, Degree):
            raise TypeError(
                f"answer() re-aims scale degrees — the tail is {type(last.pitch).__name__} "
                "content (build the call with motif([...]) for degree content)"
            )

        if isinstance(to, int):
            # Keep the call's register: only the step is re-aimed.
            target = dataclasses.replace(last.pitch, step=int(to), chroma=0)

        events = list(self.events)
        events[pitched_indices[-1]] = dataclasses.replace(last, pitch=target)

        return Motif(
            events=tuple(events),
            length=self.length,
            controls=self.controls,
            fit=self.fit,
        )

    def pitched(self, spec: PitchSpec) -> "Motif":
        """
        Replace every pitch with one spec — a kick rhythm becomes a bass line.

        ``"root"`` / ``"third"`` / ``"fifth"`` / ``"seventh"`` become chord
        tones; any other string is a drum name; ints are MIDI; Degree /
        ChordTone / Approach pass through.
        """

        if isinstance(spec, str) and spec in _CHORD_TONE_NAMES:
            spec = ChordTone(spec)

        events = tuple(dataclasses.replace(e, pitch=spec) for e in self.events)

        return Motif(
            events=events, length=self.length, controls=self.controls, fit=self.fit
        )

    def rhythm(self) -> "Motif":
        """
        Strip pitches (and control gestures): a reusable rhythmic skeleton.

        Timing, velocities, durations, and probabilities survive; re-pitch
        with :meth:`pitched` before placement (placing a skeleton raises).
        """

        events = tuple(dataclasses.replace(e, pitch=None) for e in self.events)

        return Motif(events=events, length=self.length)

    def onsets(self) -> typing.List[float]:
        """The note onset beats, in order — ready for rhythm-first generation."""

        return [e.beat for e in self.events]

    def transpose(
        self, steps: typing.Optional[int] = None, semitones: typing.Optional[int] = None
    ) -> "Motif":
        """
        Transpose pitched content; the keyword names the unit.

        ``steps=`` moves scale degrees diatonically (the sequencing move) and
        raises on absolute-MIDI or drum content; ``semitones=`` is the
        literal chromatic form for MIDI ints and degrees.  Drum motifs raise
        on both — a transposed drum name is a different instrument, not a
        transposition.
        """

        if (steps is None) == (semitones is None):
            raise ValueError("transpose() takes exactly one of steps= or semitones=")

        def move(pitch: PitchSpec) -> PitchSpec:
            if pitch is None:
                return None

            if isinstance(pitch, Approach):
                moved = move(pitch.target)
                if not isinstance(moved, (int, Degree, ChordTone)):
                    raise TypeError(
                        f"transpose cannot aim an Approach at {type(moved).__name__} content"
                    )
                return Approach(moved)

            if steps is not None:
                if isinstance(pitch, Degree):
                    return dataclasses.replace(pitch, step=pitch.step + steps)
                raise TypeError(
                    f"transpose(steps=) moves scale degrees — {type(pitch).__name__} content "
                    f"has no degrees (use semitones= for MIDI ints)"
                )

            assert (
                semitones is not None
            )  # exactly one of steps/semitones is set (validated above)

            if isinstance(pitch, int):
                return pitch + semitones
            if isinstance(pitch, Degree):
                return dataclasses.replace(pitch, chroma=pitch.chroma + semitones)
            raise TypeError(
                f"transpose(semitones=) cannot move {type(pitch).__name__} content"
            )

        events = tuple(dataclasses.replace(e, pitch=move(e.pitch)) for e in self.events)

        return Motif(
            events=events, length=self.length, controls=self.controls, fit=self.fit
        )

    def invert(self, pivot: typing.Optional[int] = None) -> "Motif":
        """
        Mirror pitches around a pivot: MIDI content around a MIDI pivot,
        degree content around a degree pivot (default: the first note's pitch).
        Drum motifs raise.
        """

        pitched_events = [e for e in self.events if e.pitch is not None]

        if not pitched_events:
            return self

        first = pitched_events[0].pitch

        if pivot is None:
            if isinstance(first, int):
                pivot = first
            elif isinstance(first, Degree):
                pivot = first.step
            else:
                raise TypeError(
                    f"invert() cannot derive a pivot from {type(first).__name__} content"
                )

        def mirror(pitch: PitchSpec) -> PitchSpec:
            if pitch is None:
                return None
            if isinstance(pitch, int):
                return 2 * pivot - pitch
            if isinstance(pitch, Degree):
                mirrored = 2 * pivot - pitch.step
                if mirrored < 1:
                    raise ValueError(
                        f"invert() around degree {pivot} sends degree {pitch.step} below the tonic — "
                        f"raise the pivot or use Degree octaves"
                    )
                # Reflection around the pivot (read at octave 0) is an isometry, so a
                # note's register flips too: a degree an octave above the pivot lands an
                # octave below it.  Negating octave needs no scale length and leaves
                # octave-0 content unchanged.
                return dataclasses.replace(
                    pitch, step=mirrored, octave=-pitch.octave, chroma=-pitch.chroma
                )
            raise TypeError(f"invert() cannot mirror {type(pitch).__name__} content")

        events = tuple(
            dataclasses.replace(e, pitch=mirror(e.pitch)) for e in self.events
        )

        return Motif(
            events=events, length=self.length, controls=self.controls, fit=self.fit
        )

    # ── description ─────────────────────────────────────────────────────

    def describe(self) -> str:
        """A readable one-line summary: length, notes (pitch@beat), and control gestures."""

        notes = ", ".join(f"{_pitch_label(e.pitch)}@{e.beat:g}" for e in self.events)
        parts = [
            f"Motif {self.length:g} beats",
            f"[{notes}]" if notes else "[no notes]",
        ]

        if self.controls:
            gestures = ", ".join(_control_label(c) for c in self.controls)
            parts.append(f"controls [{gestures}]")

        return " ".join(parts)

    def __str__(self) -> str:
        """Printable form (same as :meth:`describe`)."""

        return self.describe()


def _pitch_label(pitch: PitchSpec) -> str:
    """Compact label for a pitch spec in describe() output."""

    if pitch is None:
        return "·"
    if isinstance(pitch, Degree):
        marks = "+" * pitch.octave if pitch.octave > 0 else "-" * -pitch.octave
        chroma = (
            f"#{pitch.chroma}"
            if pitch.chroma > 0
            else f"b{-pitch.chroma}"
            if pitch.chroma < 0
            else ""
        )
        return f"^{pitch.step}{marks}{chroma}"
    if isinstance(pitch, ChordTone):
        return f"tone{pitch.index}"
    if isinstance(pitch, Approach):
        return f">{_pitch_label(pitch.target)}"

    return str(pitch)


def _control_label(c: ControlEvent) -> str:
    """Compact label for a control event in describe() output."""

    if isinstance(c.signal, CC):
        name = (
            f"CC{c.signal.control}"
            if isinstance(c.signal.control, int)
            else f"CC:{c.signal.control}"
        )
    elif isinstance(c.signal, PitchBend):
        name = "bend"
    elif isinstance(c.signal, NRPN):
        name = f"NRPN{c.signal.parameter}"
    elif isinstance(c.signal, RPN):
        name = f"RPN{c.signal.parameter}"
    else:
        name = c.signal.address

    if c.end is None:
        return f"{name}={c.start:g}@{c.beat:g}"

    return f"{name} {c.start:g}→{c.end:g} over {c.beat:g}–{c.beat + c.span:g}"


# ── Phrase ──────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class _PhraseRecipe:
    """Provenance of a generated phrase — what reroll() regenerates from.

    Generated values carry their recipe (the generator spec and seed) so
    per-region regeneration is possible; a hand-written or transformed
    phrase has none, and rerolling it raises loudly.

    Attributes:
            source: The motif the phrase was developed from.
            plan: The unit-label tuple, or the recipe name.
            bars: The phrase length in bars.
            seed: The development seed (None = the unseeded warning path).
            beats_per_bar: The bar size the plan was spread against.
            cadence: The cadence name the phrase closes on (``sentence()``/
                    ``period()`` record it; ``develop()`` leaves it ``None``).
    """

    source: Motif
    plan: typing.Union[typing.Tuple[str, ...], str]
    bars: int
    seed: typing.Optional[int]
    beats_per_bar: float = 4.0
    cadence: typing.Optional[str] = None


def _contrast_unit(source: Motif, rng: random.Random) -> Motif:
    """A generated contrast unit: the source's rhythm, freshly re-pitched.

    Roughly half the pitched notes move (small melodic nudges), so the unit
    is recognisably related but melodically new.  The richer rhythm-first
    generator arrives with the melody engine stage.
    """

    pitched = sum(1 for event in source.events if event.pitch is not None)

    return source.vary(notes=max(1, pitched // 2), position="anywhere", rng=rng)


def _call_response_units(call: Motif, seed: typing.Optional[int]) -> typing.List[Motif]:
    """The call_response recipe: call, answer, call, varied answer."""

    response = call.answer()
    varied = response.vary(
        notes=1, position="end", rng=random.Random(f"{seed}:cr:vary")
    )

    return [call, response, call, varied]


def _tile_source(
    motif: Motif, bars: int, unit_count: int, beats_per_bar: float
) -> Motif:
    """Validate the bars/unit arithmetic and tile the motif up to one unit.

    A 1-bar hook in 2-bar units repeats — the unit is the tile, and
    answer()/vary() act on the whole tile (its tail is the unit's tail).
    """

    if bars % unit_count != 0:
        raise ValueError(
            f"bars={bars} does not divide evenly across {unit_count} plan units — "
            "each unit must fill a whole number of bars"
        )

    unit_beats = bars * beats_per_bar / unit_count

    if motif.length <= 0:
        raise ValueError("cannot develop an empty motif")

    tiling = unit_beats / motif.length

    if abs(tiling - round(tiling)) > 1e-9 or round(tiling) < 1:
        raise ValueError(
            f"the motif is {motif.length:g} beats but each of the {unit_count} plan units "
            f"spans {unit_beats:g} beats ({bars} bars / {unit_count} units) — units must be "
            "a whole tiling of the motif (adjust bars, the plan, or the motif's length)"
        )

    return motif if round(tiling) == 1 else Motif.join([motif] * int(round(tiling)))


# The curated recipe table — names reserved for plans whose semantics exceed
# a label skeleton.  Each entry is (unit_count, builder); the builder takes
# (source_motif, seed) and returns exactly unit_count units.
_PHRASE_RECIPES: typing.Dict[
    str,
    typing.Tuple[
        int, typing.Callable[[Motif, typing.Optional[int]], typing.List[Motif]]
    ],
] = {
    "call_response": (4, _call_response_units),
}


@dataclasses.dataclass(frozen=True)
class Phrase:
    """
    A sequence of Motifs with segmentation preserved.

    Segmentation is the unit of editing — it is what development and
    per-region regeneration operate on.  ``flatten()`` erases it into one
    long Motif.  Length is the sum of segment lengths.

    A phrase made by :meth:`develop` carries its recipe, so
    :meth:`reroll` can regenerate a region; transforms and hand edits
    return recipe-less phrases (their notes no longer come from the
    recipe, so there is nothing honest to regenerate from).
    """

    segments: typing.Tuple[Motif, ...]
    recipe: typing.Optional[_PhraseRecipe]

    def __init__(
        self,
        segments: typing.Iterable[Motif],
        recipe: typing.Optional[_PhraseRecipe] = None,
    ) -> None:
        """Coerce any iterable of Motifs."""

        segments = tuple(segments)

        for segment in segments:
            if not isinstance(segment, Motif):
                raise TypeError(
                    f"Phrase segments must be Motifs — got {type(segment).__name__}"
                )

        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "recipe", recipe)

    @property
    def length(self) -> float:
        """Total length in beats (sum of segment lengths)."""

        return sum(segment.length for segment in self.segments)

    @classmethod
    def develop(
        cls,
        motif: Motif,
        bars: int = 8,
        plan: typing.Optional[typing.Union[typing.Sequence[str], str]] = None,
        seed: typing.Optional[int] = None,
        beats_per_bar: float = 4.0,
    ) -> "Phrase":
        """Grow a motif into a phrase by a plan — the phrase generator.

        ``plan`` follows the standard form.  The literal form is a **list of
        unit labels** — ``plan=["a", "a", "a", "b"]``, equivalently
        ``["a"] * 3 + ["b"]``: the first label is the given motif, each new
        label is a generated contrast unit (the source's rhythm, freshly
        re-pitched), a repeated label is a restatement, and *bars* spreads
        evenly across the units.  A bare string is a **recipe name** from
        the curated table — ``plan="call_response"`` (call, answer, call,
        varied answer) — reserved for plans whose semantics exceed a label
        skeleton.  A letter string is not a plan: a sequence of labels is a
        sequence, so it is a list.

        The result carries its recipe, so :meth:`reroll` can regenerate a
        region later.

        Parameters:
                motif: The source unit (its length must be ``bars / len(units)``
                        bars — the plan's units tile the phrase exactly).
                bars: Phrase length in bars (must divide evenly by the unit
                        count).
                plan: A list of unit labels, or a recipe name.
                seed: Seed for the generated units.  Without one, develop()
                        warns — module-level nondeterminism breaks live reload.
                beats_per_bar: Bar size in beats (the value is context-free;
                        4 is the common-time default).

        Example:
                ```python
                call = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3])
                lead = subsequence.Phrase.develop(call, bars=8, plan="call_response", seed=11)
                ```
        """

        if plan is None:
            raise ValueError(
                'develop() needs a plan= — a list of unit labels (plan=["a", "a", "a", "b"]) '
                'or a recipe name (plan="call_response")'
            )

        if seed is None:
            warnings.warn(
                "develop() without seed= is nondeterministic — pass seed= so the "
                "value survives live reload",
                stacklevel=2,
            )

        # How many units the plan asks for — known before any unit is built,
        # so a short motif can tile up to the unit size first.
        if isinstance(plan, str):
            if plan not in _PHRASE_RECIPES:
                known = ", ".join(sorted(_PHRASE_RECIPES))
                hint = ""
                if (
                    plan.isalpha()
                    and plan == plan.lower()
                    and len(set(plan)) < len(plan)
                ):
                    spelled = ", ".join(repr(c) for c in plan)
                    hint = f" A letter string is not a plan — a sequence of labels is a list: plan=[{spelled}]."
                raise ValueError(
                    f"Unknown phrase recipe {plan!r}. Known recipes: {known}.{hint}"
                )
            unit_count = _PHRASE_RECIPES[plan][0]
        else:
            labels = list(plan)
            if not labels or not all(
                isinstance(label, str) and label for label in labels
            ):
                raise ValueError(
                    "plan labels must be non-empty strings, e.g. plan=['a', 'a', 'b']"
                )
            unit_count = len(labels)

        source = _tile_source(motif, bars, unit_count, beats_per_bar)

        # An unseeded call draws a fresh salt so repeated calls genuinely
        # differ, as the warning above promises — interpolating None gave the
        # FIXED seed "None:..." and silently returned the same phrase every
        # time.
        salt = seed if seed is not None else random.randrange(2**32)

        if isinstance(plan, str):
            units = _PHRASE_RECIPES[plan][1](source, salt)
            stored_plan: typing.Union[typing.Tuple[str, ...], str] = plan
        else:
            generated: typing.Dict[str, Motif] = {labels[0]: source}
            for label in labels:
                if label not in generated:
                    generated[label] = _contrast_unit(
                        source, random.Random(f"{salt}:unit:{label}")
                    )
            units = [generated[label] for label in labels]
            stored_plan = tuple(labels)

        return cls(
            units,
            recipe=_PhraseRecipe(
                source=motif,
                plan=stored_plan,
                bars=bars,
                seed=seed,
                beats_per_bar=beats_per_bar,
            ),
        )

    def reroll(
        self,
        bar: typing.Optional[int] = None,
        bars: typing.Optional[typing.Sequence[int]] = None,
        seed: typing.Optional[int] = None,
    ) -> "Phrase":
        """Regenerate only the named bars — rhythm and boundary pitches kept.

        Within each named bar, the first and last pitched notes stay (the
        boundary pins) and the interior pitches re-roll from a fresh per-bar
        stream salted by ``seed=`` (an unseeded call draws a fresh salt, so
        each call genuinely differs); onsets, durations, velocities, rests,
        drums, and control gestures are untouched.  Segmentation and the
        recipe survive, so rerolls compose.

        Only a phrase that carries a recipe can reroll — a hand-written or
        transformed phrase raises loudly (its notes no longer come from a
        generator, so regenerating them would invent music).

        Parameters:
                bar: A single 1-based bar to reroll.
                bars: A list of 1-based bars (the paired plural spelling).
                seed: Seed for the new pitches (salted per bar).  Without one,
                        reroll() warns.

        Example:
                ```python
                lead = lead.reroll(bar=7, seed=4)    # only bar 7; rhythm + boundaries kept
                ```
        """

        if self.recipe is None:
            raise ValueError(
                "this phrase carries no recipe (it was written by hand, or transformed "
                "since generation) — reroll() regenerates from a recipe; edit segments "
                "with replace(), or rebuild with Phrase.develop()"
            )

        if (bar is None) == (bars is None):
            raise ValueError(
                "reroll() takes exactly one of bar= (an int) or bars= (a list)"
            )

        region = [bar] if bar is not None else list(bars or [])
        beats_per_bar = self.recipe.beats_per_bar
        total_bars = int(round(self.length / beats_per_bar))

        for number in region:
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or not 1 <= number <= total_bars
            ):
                raise ValueError(
                    f"bar {number!r} is outside this phrase (1–{total_bars})"
                )

        if seed is None:
            warnings.warn(
                "reroll() without seed= is nondeterministic — pass seed= so the "
                "value survives live reload",
                stacklevel=2,
            )

        # Unseeded rerolls draw a fresh salt — a fixed "None:..." seed would
        # "re-roll" to the identical pitches every time.
        salt = seed if seed is not None else random.randrange(2**32)

        windows = [
            (
                (number - 1) * beats_per_bar,
                number * beats_per_bar,
                random.Random(f"{salt}:reroll:{number}"),
            )
            for number in sorted(set(region))
        ]

        new_segments: typing.List[Motif] = []
        offset = 0.0

        for segment in self.segments:
            events = list(segment.events)

            for window_start, window_end, rng in windows:
                inside = [
                    index
                    for index, event in enumerate(events)
                    if window_start <= offset + event.beat < window_end
                    and event.pitch is not None
                    and not isinstance(event.pitch, str)
                ]

                # Boundary pins: the first and last pitched notes of the bar
                # stay; only the interior re-rolls.
                for index in inside[1:-1]:
                    events[index] = dataclasses.replace(
                        events[index],
                        pitch=segment._nudged_pitch(events[index].pitch, rng),
                    )

            new_segments.append(
                Motif(
                    events=tuple(events),
                    length=segment.length,
                    controls=segment.controls,
                )
            )
            offset += segment.length

        return Phrase(new_segments, recipe=self.recipe)

    def flatten(self) -> Motif:
        """Erase segmentation: one long Motif (the monoid homomorphism onto ``then``)."""

        return Motif.join(self.segments)

    # ── algebra ─────────────────────────────────────────────────────────

    def __add__(self, other: typing.Any) -> "Phrase":
        """Append a Motif segment, or concatenate another Phrase's segments."""

        if isinstance(other, Motif):
            return Phrase(self.segments + (other,))
        if isinstance(other, Phrase):
            return Phrase(self.segments + other.segments)

        return NotImplemented

    def __radd__(self, other: typing.Any) -> "Phrase":
        """A Motif on the left prepends as a segment."""

        if isinstance(other, Motif):
            return Phrase((other,) + self.segments)

        return NotImplemented

    def __mul__(self, count: int) -> "Phrase":
        """Tile the segments *count* times."""

        if not isinstance(count, int):
            return NotImplemented
        if count < 0:
            raise ValueError(f"Repetition count must be non-negative — got {count}")

        return Phrase(self.segments * count)

    __rmul__ = __mul__

    def __and__(self, other: typing.Any) -> Motif:
        """Parallel merge is vertical: Phrase operands flatten to Motif first."""

        if isinstance(other, (Motif, Phrase)):
            return self.flatten().stack(other)

        return NotImplemented

    def stack(self, other: typing.Union[Motif, "Phrase"]) -> Motif:
        """The spelled form of ``&`` — flattens, then merges."""

        return self.flatten().stack(other)

    def slice(self, start: float, end: float) -> "Phrase":
        """A window; re-segments at the cut points (partial segments are sliced)."""

        segments = []
        offset = 0.0

        for segment in self.segments:
            seg_start, seg_end = offset, offset + segment.length
            lo, hi = max(start, seg_start), min(end, seg_end)
            if lo < hi:
                segments.append(segment.slice(lo - seg_start, hi - seg_start))
            offset = seg_end

        return Phrase(segments)

    def replace(self, position: int, motif: Motif) -> "Phrase":
        """Replace the segment at a 1-based position (musicians count from one)."""

        if not 1 <= position <= len(self.segments):
            raise IndexError(
                f"Phrase has {len(self.segments)} segments — position {position} is out of range (1-based)"
            )

        segments = list(self.segments)
        segments[position - 1] = motif

        return Phrase(segments)

    # ── transforms: lifted segment-wise, except time-reordering ─────────

    def reverse(self) -> "Phrase":
        """Reverse the whole timeline: segments reverse order AND each reverses internally."""

        return Phrase(tuple(segment.reverse() for segment in reversed(self.segments)))

    def rotate(self, beats: float) -> "Phrase":
        """Rotate the whole timeline modulo the total length, then re-segment at the original boundaries."""

        flat = self.flatten().rotate(beats)
        segments = []
        offset = 0.0

        # Re-segment by onset (events keep their full durations — a note may
        # ring past its new segment, exactly as it does on the flat timeline).
        for segment in self.segments:
            lo, hi = offset, offset + segment.length
            segments.append(
                Motif(
                    events=tuple(
                        dataclasses.replace(e, beat=e.beat - lo)
                        for e in flat.events
                        if lo <= e.beat < hi
                    ),
                    length=segment.length,
                    controls=tuple(
                        dataclasses.replace(c, beat=c.beat - lo)
                        for c in flat.controls
                        if lo <= c.beat < hi
                    ),
                )
            )
            offset = hi

        return Phrase(segments)

    def _lift(self, name: str, *args: typing.Any, **kwargs: typing.Any) -> "Phrase":
        """Apply a Motif transform to every segment."""

        return Phrase(
            tuple(getattr(segment, name)(*args, **kwargs) for segment in self.segments)
        )

    def stretch(self, factor: float) -> "Phrase":
        """Scale time in every segment (lengths scale with them)."""

        return self._lift("stretch", factor)

    def quantize(self, grid: float) -> "Phrase":
        """Snap note onsets segment-wise."""

        return self._lift("quantize", grid)

    def with_velocity(
        self, velocity: typing.Union[int, typing.Tuple[int, int]]
    ) -> "Phrase":
        """Replace every note's velocity, segment-wise."""

        return self._lift("with_velocity", velocity)

    def pitched(self, spec: PitchSpec) -> "Phrase":
        """Replace every pitch, segment-wise."""

        return self._lift("pitched", spec)

    def rhythm(self) -> "Phrase":
        """Strip pitches segment-wise: a phrase-shaped skeleton."""

        return self._lift("rhythm")

    def transpose(
        self, steps: typing.Optional[int] = None, semitones: typing.Optional[int] = None
    ) -> "Phrase":
        """Transpose every segment (see :meth:`Motif.transpose`)."""

        return self._lift("transpose", steps=steps, semitones=semitones)

    def invert(self, pivot: typing.Optional[int] = None) -> "Phrase":
        """Mirror pitches in every segment around one pivot (see :meth:`Motif.invert`)."""

        if pivot is None:
            for segment in self.segments:
                for event in segment.events:
                    if event.pitch is not None:
                        if isinstance(event.pitch, int):
                            pivot = event.pitch
                        elif isinstance(event.pitch, Degree):
                            pivot = event.pitch.step
                        break
                if pivot is not None:
                    break

        return self._lift("invert", pivot=pivot)

    def describe(self) -> str:
        """A readable summary: total length and each segment on its own line."""

        header = f"Phrase {self.length:g} beats, {len(self.segments)} segments"
        lines = [
            f"  {i + 1}. {segment.describe()}"
            for i, segment in enumerate(self.segments)
        ]

        return "\n".join([header] + lines)

    def __str__(self) -> str:
        """Printable form (same as :meth:`describe`)."""

        return self.describe()


def motif(
    degrees: typing.List[typing.Union[int, Degree, None]],
    beats: typing.Optional[typing.List[float]] = None,
    velocities: typing.Any = _DEFAULT_VELOCITY,
    durations: typing.Any = 1.0,
    probabilities: typing.Any = 1.0,
    length: typing.Optional[float] = None,
) -> Motif:
    """
    The lowercase shortcut: a melody as 1-based scale degrees.

    ``subsequence.motif([5, 6, 5, 3])`` is ``Motif.degrees([5, 6, 5, 3])`` —
    relative pitch is the primary form.  For absolute MIDI note numbers use
    ``Motif.notes([64, 65, 64, 60])``; implausibly large ints here raise so
    a pasted MIDI list fails loud instead of squealing octaves up.
    """

    return Motif.degrees(
        degrees,
        beats=beats,
        velocities=velocities,
        durations=durations,
        probabilities=probabilities,
        length=length,
    )


def sentence(
    motif: Motif,
    bars: int = 8,
    cadence: str = "strong",
    seed: typing.Optional[int] = None,
    beats_per_bar: float = 4.0,
) -> Phrase:
    """The classical sentence, as a thin combinator — idea, idea, drive, close.

    Four units: the basic idea stated twice (the presentation), a generated
    contrast unit (the continuation — the source's rhythm, freshly
    re-pitched), and a second contrast unit whose tail lands on the
    cadence's close degree (the cadential close).  An 8-bar sentence from a
    2-bar idea is the textbook proportion; a shorter idea tiles up to the
    unit size first.

    The melodic side of a cadence only — pair it with the harmonic side
    (``prog.cadence()``, ``Progression.generate(cadence=)``, or
    ``request_cadence()``) and the two arrive together.

    Parameters:
            motif: The basic idea (degree content — the close re-aims a degree).
            bars: Sentence length (must divide evenly across the 4 units).
            cadence: The close — ``"strong"`` lands on 1, ``"open"`` on 5,
                    ``"soft"``/``"fakeout"`` on 1 (theory aliases accepted).
            seed: Seed for the generated continuation units (seed-or-warn).
            beats_per_bar: Bar size in beats (context-free; 4 is the default).

    Example:
            ```python
            idea = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3])
            verse_lead = subsequence.sentence(idea, bars=8, cadence="open", seed=11)
            ```
    """

    spec = subsequence.cadences.cadence_formula(cadence)

    if seed is None:
        warnings.warn(
            "sentence() without seed= is nondeterministic — pass seed= so the "
            "value survives live reload",
            stacklevel=2,
        )

    source = _tile_source(motif, bars, 4, beats_per_bar)

    # Unseeded calls draw a fresh salt (a fixed "None:..." seed would return
    # the same sentence every time, belying the warning above).
    salt = seed if seed is not None else random.randrange(2**32)

    continuation = _contrast_unit(
        source, random.Random(f"{salt}:sentence:continuation")
    )
    cadential = _contrast_unit(
        source, random.Random(f"{salt}:sentence:cadential")
    ).answer(to=spec.close_degree)

    return Phrase(
        [source, source, continuation, cadential],
        recipe=_PhraseRecipe(
            source=motif,
            plan="sentence",
            bars=bars,
            seed=seed,
            beats_per_bar=beats_per_bar,
            cadence=spec.name,
        ),
    )


def period(
    antecedent: typing.Union[Motif, Phrase],
    cadence: str = "strong",
    beats_per_bar: float = 4.0,
) -> Phrase:
    """The classical period, as a thin combinator — question, then answer.

    Two halves: the antecedent with its tail re-aimed to the open half-close
    (degree 5 — the question), then the same material restated with its tail
    on the cadence's close degree (the answer).  The two halves differ
    exactly at their closes — the open/closed contrast *is* the period.

    Deterministic: no notes are generated, only the two tail notes re-aim
    (so there is no seed).  Vary the consequent yourself for a looser
    restatement: ``period(a).reroll(bar=7, seed=4)``.

    Parameters:
            antecedent: The first half — a Motif, or a Phrase whose segmentation
                    is kept (only its last segment's tail re-aims).
            cadence: The consequent's close — ``"strong"`` lands on 1 (theory
                    aliases accepted).
            beats_per_bar: Bar size in beats, recorded for ``reroll()`` windows.

    Example:
            ```python
            idea = subsequence.motif([3, 4, 5, 1, None, 6, 5, 4], length=8)
            lead = subsequence.period(idea)        # 16 beats: half-close, then home
            ```
    """

    spec = subsequence.cadences.cadence_formula(cadence)
    open_degree = subsequence.cadences.cadence_formula("open").close_degree

    units = (
        list(antecedent.segments) if isinstance(antecedent, Phrase) else [antecedent]
    )

    if not units or sum(unit.length for unit in units) <= 0:
        raise ValueError("cannot build a period from an empty antecedent")

    tail = units[-1]

    antecedent_units = units[:-1] + [tail.answer(to=open_degree)]
    consequent_units = units[:-1] + [tail.answer(to=spec.close_degree)]

    source = antecedent.flatten() if isinstance(antecedent, Phrase) else antecedent
    total_beats = 2 * sum(unit.length for unit in units)

    return Phrase(
        antecedent_units + consequent_units,
        recipe=_PhraseRecipe(
            source=source,
            plan="period",
            bars=int(round(total_beats / beats_per_bar)),
            seed=None,
            beats_per_bar=beats_per_bar,
            cadence=spec.name,
        ),
    )
