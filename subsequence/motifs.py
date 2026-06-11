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

import subsequence.constants.velocity
import subsequence.easing
import subsequence.sequence_utils


_DEFAULT_VELOCITY = subsequence.constants.velocity.DEFAULT_VELOCITY

# Degree ints beyond this are almost certainly pasted MIDI note numbers
# (e.g. 60 for middle C), not scale degrees; fail loud rather than emit a
# squeal eight octaves up.
_MAX_PLAUSIBLE_DEGREE = 24

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

	def __post_init__ (self) -> None:

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

	def __init__ (self, index_or_name: typing.Union[int, str], octave: int = 0) -> None:

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

	Parses today; resolution requires the harmony window and is not yet
	available — placing a motif containing one raises with a clear message.
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


def _pitch_sort_key (pitch: PitchSpec) -> tuple:

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


def _signal_sort_key (signal: ControlSignal) -> tuple:

	"""A total order over control signals (for canonical event order)."""

	rank = _SIGNAL_RANK[type(signal)]

	if isinstance(signal, CC):
		return (rank, str(signal.control))
	if isinstance(signal, (NRPN, RPN)):
		return (rank, str(signal.parameter), signal.fine, signal.null_reset)
	if isinstance(signal, OSC):
		return (rank, signal.address)

	return (rank,)


def _velocity_key (velocity: typing.Union[int, typing.Tuple[int, int]]) -> typing.Tuple[int, int]:

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

	def __post_init__ (self) -> None:

		"""Validate ranges that are wrong at any placement."""

		if self.duration <= 0:
			raise ValueError(f"Event duration must be positive — got {self.duration}")
		if not 0.0 <= self.probability <= 1.0:
			raise ValueError(f"Event probability must be 0.0–1.0 — got {self.probability}")

	def _sort_key (self) -> tuple:

		"""Canonical ordering key — makes parallel merge order-independent."""

		return (self.beat, _pitch_sort_key(self.pitch), _velocity_key(self.velocity), self.duration, self.probability)


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

	def __post_init__ (self) -> None:

		"""Validate the discrete/ramp invariants."""

		if (self.end is None) != (self.span == 0.0):
			raise ValueError("A ramp needs both end= and span= (a discrete write has neither)")
		if self.span < 0:
			raise ValueError(f"Ramp span must be non-negative — got {self.span}")
		if not 0.0 <= self.probability <= 1.0:
			raise ValueError(f"Event probability must be 0.0–1.0 — got {self.probability}")

	def _sort_key (self) -> tuple:

		"""Canonical ordering key — makes parallel merge order-independent."""

		end = self.start if self.end is None else self.end
		return (self.beat, _signal_sort_key(self.signal), self.start, end, self.span, self.probability)

	def _value_at (self, fraction: float) -> float:

		"""The interpolated value at a 0–1 fraction through the ramp."""

		if self.end is None:
			return self.start

		easing_fn = self.shape if callable(self.shape) else subsequence.easing.get_easing(self.shape)
		return self.start + (self.end - self.start) * easing_fn(max(0.0, min(1.0, fraction)))


def _expand (name: str, value: typing.Any, n: int) -> list:

	"""Expand a scalar parameter to n values, or validate a per-event list."""

	if isinstance(value, (int, float, str)) or value is None or isinstance(value, tuple):
		return [value] * n

	result = list(value)

	if len(result) != n:
		raise ValueError(f"{name} has {len(result)} values for {n} events — parallel lists must match")

	return result


def _computed_length (events: typing.Iterable[MotifEvent], controls: typing.Iterable[ControlEvent]) -> float:

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

	def __post_init__ (self) -> None:

		"""Validate, and normalise both streams to canonical order."""

		if self.length < 0:
			raise ValueError(f"Motif length must be non-negative — got {self.length}")

		object.__setattr__(self, "events", tuple(sorted(self.events, key=MotifEvent._sort_key)))
		object.__setattr__(self, "controls", tuple(sorted(self.controls, key=ControlEvent._sort_key)))

	# ── constructors ────────────────────────────────────────────────────

	@classmethod
	def empty (cls) -> "Motif":

		"""The empty motif (zero events, zero length) — the identity for ``then``."""

		return cls(events=(), length=0.0)

	@classmethod
	def from_events (
		cls,
		events: typing.Iterable[MotifEvent],
		length: typing.Optional[float] = None,
		controls: typing.Iterable[ControlEvent] = (),
	) -> "Motif":

		"""Build a motif from explicit events (power use; length defaults to the next whole beat)."""

		events = tuple(events)
		controls = tuple(controls)

		return cls(
			events = events,
			length = _computed_length(events, controls) if length is None else length,
			controls = controls,
		)

	@classmethod
	def _from_sequence (
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
			raise ValueError(f"beats has {len(onsets)} onsets for {n} elements — parallel lists must match")

		velocity_list = _expand("velocities", velocities, n)
		duration_list = _expand("durations", durations, n)
		probability_list = _expand("probabilities", probabilities, n)

		events = tuple(
			MotifEvent(
				beat = float(onsets[i]),
				pitch = pitches[i],
				velocity = velocity_list[i],
				duration = float(duration_list[i]),
				probability = float(probability_list[i]),
			)
			for i in range(n)
			if pitches[i] is not None
		)

		return cls(
			events = events,
			length = _computed_length(events, ()) if length is None else float(length),
		)

	@classmethod
	def degrees (
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
				raise TypeError(f"Motif.degrees takes ints, Degree, or None — got {type(element).__name__}")

		return cls._from_sequence(converted, beats, velocities, durations, probabilities, length)

	@classmethod
	def notes (
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
			if not (isinstance(element, int) or element is None):
				raise TypeError(f"Motif.notes takes MIDI ints or None — got {type(element).__name__}")

		return cls._from_sequence(list(notes), beats, velocities, durations, probabilities, length)

	@classmethod
	def hits (
		cls,
		pitch: typing.Union[int, str],
		beats: typing.List[float],
		length: typing.Optional[float] = None,
		velocities: typing.Any = _DEFAULT_VELOCITY,
		durations: typing.Any = 0.1,
		probabilities: typing.Any = 1.0,
	) -> "Motif":

		"""One pitch (usually a drum name) at a list of beat positions — the ``hit()`` convention."""

		return cls._from_sequence([pitch] * len(beats), list(beats), velocities, durations, probabilities, length)

	@classmethod
	def steps (
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

		return cls._from_sequence(pitch_list, onsets, velocities, durations, probabilities, length)

	@classmethod
	def euclidean (
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

		# The kernel returns one 0/1 flag per grid step; onsets are the 1s.
		flags = subsequence.sequence_utils.generate_euclidean_sequence(steps=steps, pulses=pulses)
		step_duration = length / steps
		onsets = [i * step_duration for i, flag in enumerate(flags) if flag]

		return cls._from_sequence(
			[pitch] * len(onsets),
			onsets,
			velocities, durations, probabilities, length,
		)

	# ── control-gesture constructors (mirror the pattern_midi verbs) ────

	@classmethod
	def _control_writes (
		cls,
		signal: ControlSignal,
		values: typing.List[float],
		beats: typing.List[float],
		length: typing.Optional[float],
		probabilities: typing.Any = 1.0,
	) -> "Motif":

		"""Shared core for discrete control writes."""

		if len(values) != len(beats):
			raise ValueError(f"values has {len(values)} entries for {len(beats)} beats — parallel lists must match")

		probability_list = _expand("probabilities", probabilities, len(values))

		controls = tuple(
			ControlEvent(beat=float(beats[i]), signal=signal, start=float(values[i]), probability=float(probability_list[i]))
			for i in range(len(values))
		)

		return cls(
			events = (),
			length = _computed_length((), controls) if length is None else float(length),
			controls = controls,
		)

	@classmethod
	def _control_ramp (
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
				raise ValueError("A ramp needs beat_end= (or length=, which beat_end defaults to)")
			beat_end = float(length)

		if beat_end <= beat_start:
			raise ValueError(f"beat_end ({beat_end}) must be after beat_start ({beat_start})")

		controls = (
			ControlEvent(
				beat = float(beat_start),
				signal = signal,
				start = float(start),
				end = float(end),
				span = float(beat_end) - float(beat_start),
				shape = shape,
				probability = probability,
			),
		)

		return cls(
			events = (),
			length = float(math.ceil(beat_end)) if length is None else float(length),
			controls = controls,
		)

	@classmethod
	def cc (cls, control: typing.Union[int, str], values: typing.List[int], beats: typing.List[float], length: typing.Optional[float] = None, probabilities: typing.Any = 1.0) -> "Motif":

		"""Discrete CC writes at beat positions — mirrors ``p.cc()``; names resolve at placement."""

		return cls._control_writes(CC(control), list(values), list(beats), length, probabilities)

	@classmethod
	def cc_ramp (cls, control: typing.Union[int, str], start: int, end: int, beat_start: float = 0.0, beat_end: typing.Optional[float] = None, shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear", length: typing.Optional[float] = None, probability: float = 1.0) -> "Motif":

		"""A CC value swept ``start`` → ``end`` over a beat range — mirrors ``p.cc_ramp()``."""

		return cls._control_ramp(CC(control), start, end, beat_start, beat_end, shape, length, probability)

	@classmethod
	def pitch_bend (cls, values: typing.List[float], beats: typing.List[float], length: typing.Optional[float] = None, probabilities: typing.Any = 1.0) -> "Motif":

		"""Discrete pitch-bend writes (-1.0 to 1.0) at beat positions — mirrors ``p.pitch_bend()``."""

		return cls._control_writes(PitchBend(), list(values), list(beats), length, probabilities)

	@classmethod
	def pitch_bend_ramp (cls, start: float, end: float, beat_start: float = 0.0, beat_end: typing.Optional[float] = None, shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear", length: typing.Optional[float] = None, probability: float = 1.0) -> "Motif":

		"""Pitch bend swept ``start`` → ``end`` (-1.0 to 1.0) over a beat range — mirrors ``p.pitch_bend_ramp()``."""

		return cls._control_ramp(PitchBend(), start, end, beat_start, beat_end, shape, length, probability)

	@classmethod
	def nrpn (cls, parameter: typing.Union[int, str], values: typing.List[int], beats: typing.List[float], fine: bool = False, null_reset: bool = True, length: typing.Optional[float] = None, probabilities: typing.Any = 1.0) -> "Motif":

		"""Discrete NRPN parameter writes at beat positions — mirrors ``p.nrpn()``."""

		return cls._control_writes(NRPN(parameter, fine=fine, null_reset=null_reset), list(values), list(beats), length, probabilities)

	@classmethod
	def nrpn_ramp (cls, parameter: typing.Union[int, str], start: int, end: int, beat_start: float = 0.0, beat_end: typing.Optional[float] = None, shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear", fine: bool = True, null_reset: bool = True, length: typing.Optional[float] = None, probability: float = 1.0) -> "Motif":

		"""An NRPN value swept over a beat range — mirrors ``p.nrpn_ramp()``."""

		return cls._control_ramp(NRPN(parameter, fine=fine, null_reset=null_reset), start, end, beat_start, beat_end, shape, length, probability)

	@classmethod
	def rpn (cls, parameter: typing.Union[int, str], values: typing.List[int], beats: typing.List[float], fine: bool = False, null_reset: bool = True, length: typing.Optional[float] = None, probabilities: typing.Any = 1.0) -> "Motif":

		"""Discrete RPN parameter writes at beat positions — mirrors ``p.rpn()``."""

		return cls._control_writes(RPN(parameter, fine=fine, null_reset=null_reset), list(values), list(beats), length, probabilities)

	@classmethod
	def rpn_ramp (cls, parameter: typing.Union[int, str], start: int, end: int, beat_start: float = 0.0, beat_end: typing.Optional[float] = None, shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear", fine: bool = True, null_reset: bool = True, length: typing.Optional[float] = None, probability: float = 1.0) -> "Motif":

		"""An RPN value swept over a beat range — mirrors ``p.rpn_ramp()``."""

		return cls._control_ramp(RPN(parameter, fine=fine, null_reset=null_reset), start, end, beat_start, beat_end, shape, length, probability)

	@classmethod
	def osc (cls, address: str, values: typing.List[float], beats: typing.List[float], length: typing.Optional[float] = None, probabilities: typing.Any = 1.0) -> "Motif":

		"""Discrete OSC float sends at beat positions — mirrors ``p.osc()``."""

		return cls._control_writes(OSC(address), list(values), list(beats), length, probabilities)

	@classmethod
	def osc_ramp (cls, address: str, start: float, end: float, beat_start: float = 0.0, beat_end: typing.Optional[float] = None, shape: typing.Union[str, "subsequence.easing.EasingFn"] = "linear", length: typing.Optional[float] = None, probability: float = 1.0) -> "Motif":

		"""An OSC float swept over a beat range — mirrors ``p.osc_ramp()``."""

		return cls._control_ramp(OSC(address), start, end, beat_start, beat_end, shape, length, probability)

	# ── the algebra ─────────────────────────────────────────────────────

	def then (self, other: "Motif") -> "Motif":

		"""Closed sequential concat: glue *other* after this motif into ONE longer motif."""

		if not isinstance(other, Motif):
			raise TypeError(f"then() takes a Motif — got {type(other).__name__}")

		return Motif(
			events = self.events + tuple(dataclasses.replace(e, beat=e.beat + self.length) for e in other.events),
			length = self.length + other.length,
			controls = self.controls + tuple(dataclasses.replace(c, beat=c.beat + self.length) for c in other.controls),
		)

	@classmethod
	def join (cls, motifs: typing.Iterable["Motif"]) -> "Motif":

		"""Fold a list of motifs into one with ``then`` (empty list → ``Motif.empty()``)."""

		result = cls.empty()

		for m in motifs:
			result = result.then(m)

		return result

	def stack (self, other: typing.Union["Motif", "Phrase"]) -> "Motif":

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
			raise TypeError(f"stack() takes a Motif or Phrase — got {type(other).__name__}")

		return Motif(
			events = self.events + merged.events,
			length = max(self.length, merged.length),
			controls = self.controls + merged.controls,
		)

	def slice (self, start: float, end: float) -> "Motif":

		"""
		A window onto the motif, on its own authority: events starting outside
		are dropped; durations and ramp spans truncate at the cut (a truncated
		ramp ends at its interpolated cut value).  Beats shift so the window
		starts at 0.
		"""

		if end <= start:
			raise ValueError(f"slice end ({end}) must be after start ({start})")

		events = tuple(
			dataclasses.replace(e, beat=e.beat - start, duration=min(e.duration, end - e.beat))
			for e in self.events
			if start <= e.beat < end
		)

		controls = []

		for c in self.controls:
			if not (start <= c.beat < end):
				continue
			if c.end is not None and c.beat + c.span > end:
				kept = end - c.beat
				controls.append(dataclasses.replace(
					c, beat=c.beat - start, span=kept, end=c._value_at(kept / c.span),
				))
			else:
				controls.append(dataclasses.replace(c, beat=c.beat - start))

		return Motif(events=events, length=end - start, controls=tuple(controls))

	def __add__ (self, other: typing.Any) -> "Phrase":

		"""``a + b`` — sequential: a two-segment Phrase (segmentation preserved)."""

		if isinstance(other, Motif):
			return Phrase((self, other))

		return NotImplemented

	def __mul__ (self, count: int) -> typing.Union["Motif", "Phrase"]:

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

	def __and__ (self, other: typing.Any) -> "Motif":

		"""``a & b`` — parallel merge; the spelled form is :meth:`stack`."""

		if isinstance(other, (Motif, Phrase)):
			return self.stack(other)

		return NotImplemented

	# ── transforms (pure; control gestures ride time, ignore pitch) ─────

	def reverse (self) -> "Motif":

		"""Mirror the figure in time; ramps swap direction (a rising sweep falls)."""

		events = tuple(
			dataclasses.replace(e, beat=max(0.0, self.length - e.beat - e.duration))
			for e in self.events
		)
		controls = tuple(
			dataclasses.replace(
				c,
				beat = max(0.0, self.length - c.beat - c.span),
				start = c.start if c.end is None else c.end,
				end = c.end if c.end is None else c.start,
			)
			for c in self.controls
		)

		return Motif(events=events, length=self.length, controls=controls)

	def rotate (self, beats: float) -> "Motif":

		"""Shift every onset by *beats*, wrapping modulo the length (spans ride along)."""

		if self.length == 0:
			return self

		events = tuple(dataclasses.replace(e, beat=(e.beat + beats) % self.length) for e in self.events)
		controls = tuple(dataclasses.replace(c, beat=(c.beat + beats) % self.length) for c in self.controls)

		return Motif(events=events, length=self.length, controls=controls)

	def stretch (self, factor: float) -> "Motif":

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

		return Motif(events=events, length=self.length * factor, controls=controls)

	def quantize (self, grid: float) -> "Motif":

		"""Snap note onsets to the nearest multiple of *grid* beats (control gestures untouched)."""

		if grid <= 0:
			raise ValueError(f"Quantize grid must be positive — got {grid}")

		events = tuple(
			dataclasses.replace(e, beat=round(e.beat / grid) * grid)
			for e in self.events
		)

		return Motif(events=events, length=self.length, controls=self.controls)

	def accent (self, beat: float, amount: int = 20) -> "Motif":

		"""Add *amount* velocity to every note at the given beat position (0-based beats)."""

		def boost (velocity: typing.Union[int, typing.Tuple[int, int]]) -> typing.Union[int, typing.Tuple[int, int]]:
			if isinstance(velocity, tuple):
				return (min(127, velocity[0] + amount), min(127, velocity[1] + amount))
			return min(127, velocity + amount)

		events = tuple(
			dataclasses.replace(e, velocity=boost(e.velocity)) if abs(e.beat - beat) < 1e-9 else e
			for e in self.events
		)

		return Motif(events=events, length=self.length, controls=self.controls)

	def with_velocity (self, velocity: typing.Union[int, typing.Tuple[int, int]]) -> "Motif":

		"""Replace every note's velocity (an int, or a ``(low, high)`` random range)."""

		events = tuple(dataclasses.replace(e, velocity=velocity) for e in self.events)

		return Motif(events=events, length=self.length, controls=self.controls)

	def _nudged_pitch (self, pitch: PitchSpec, rng: random.Random) -> PitchSpec:

		"""One varied pitch: a small melodic nudge that always changes the note.

		Degrees move by scale steps, MIDI ints by semitones, chord tones by
		index; an Approach's target is nudged.  Drum names raise — a varied
		drum is a different instrument, not a variation.
		"""

		if isinstance(pitch, Degree):
			steps = [pitch.step + delta for delta in (-2, -1, 1, 2) if pitch.step + delta >= 1]
			return dataclasses.replace(pitch, step = rng.choice(steps))
		if isinstance(pitch, ChordTone):
			indices = [pitch.index + delta for delta in (-1, 1) if pitch.index + delta >= 1]
			return ChordTone(rng.choice(indices), octave = pitch.octave)
		if isinstance(pitch, Approach):
			nudged = self._nudged_pitch(pitch.target, rng)
			if not isinstance(nudged, (int, Degree, ChordTone)):
				raise TypeError(f"cannot vary an Approach aimed at {type(nudged).__name__} content")
			return Approach(nudged)
		if isinstance(pitch, int):
			return pitch + rng.choice((-2, -1, 1, 2))

		raise TypeError(
			f"vary() moves pitches — {type(pitch).__name__} content cannot vary "
			"(a varied drum is a different instrument)"
		)

	def vary (
		self,
		notes: int = 1,
		position: str = "end",
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
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

		Example:
			```python
			answer = call.vary(notes=1, seed=4)     # same figure, new tail note
			```
		"""

		if notes < 0:
			raise ValueError(f"notes must be at least 0, got {notes}")
		if position not in ("end", "start", "anywhere"):
			raise ValueError(f'position must be "end", "start", or "anywhere" — got {position!r}')

		if rng is None:
			if seed is None:
				warnings.warn(
					"vary() without seed= is nondeterministic — pass seed= so the "
					"value survives live reload",
					stacklevel = 2,
				)
				rng = random.Random()
			else:
				rng = random.Random(seed)

		pitched_indices = [index for index, event in enumerate(self.events) if event.pitch is not None]
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
			events[index] = dataclasses.replace(events[index], pitch = self._nudged_pitch(events[index].pitch, rng))

		return Motif(events = tuple(events), length = self.length, controls = self.controls)

	def answer (self, to: typing.Union[int, Degree] = 1) -> "Motif":

		"""Call → response: re-aim the tail to a stable degree.

		The classic consequent move — the figure repeats but its last pitched
		note lands home (degree 1 by default; pass ``to=5`` for a half-close,
		or a full ``Degree`` for register control).  Everything else —
		rhythm, the other pitches, velocities, controls — is untouched.

		Degree content only: absolute MIDI has no degrees to re-aim (build
		the call with ``motif([...])``), and drums raise.
		"""

		target = to if isinstance(to, Degree) else Degree(int(to))

		pitched_indices = [index for index, event in enumerate(self.events) if event.pitch is not None]

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
			target = dataclasses.replace(last.pitch, step = int(to), chroma = 0)

		events = list(self.events)
		events[pitched_indices[-1]] = dataclasses.replace(last, pitch = target)

		return Motif(events = tuple(events), length = self.length, controls = self.controls)

	def pitched (self, spec: PitchSpec) -> "Motif":

		"""
		Replace every pitch with one spec — a kick rhythm becomes a bass line.

		``"root"`` / ``"third"`` / ``"fifth"`` / ``"seventh"`` become chord
		tones; any other string is a drum name; ints are MIDI; Degree /
		ChordTone / Approach pass through.
		"""

		if isinstance(spec, str) and spec in _CHORD_TONE_NAMES:
			spec = ChordTone(spec)

		events = tuple(dataclasses.replace(e, pitch=spec) for e in self.events)

		return Motif(events=events, length=self.length, controls=self.controls)

	def rhythm (self) -> "Motif":

		"""
		Strip pitches (and control gestures): a reusable rhythmic skeleton.

		Timing, velocities, durations, and probabilities survive; re-pitch
		with :meth:`pitched` before placement (placing a skeleton raises).
		"""

		events = tuple(dataclasses.replace(e, pitch=None) for e in self.events)

		return Motif(events=events, length=self.length)

	def onsets (self) -> typing.List[float]:

		"""The note onset beats, in order — ready for rhythm-first generation."""

		return [e.beat for e in self.events]

	def transpose (self, steps: typing.Optional[int] = None, semitones: typing.Optional[int] = None) -> "Motif":

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

		def move (pitch: PitchSpec) -> PitchSpec:

			if pitch is None:
				return None

			if isinstance(pitch, Approach):
				moved = move(pitch.target)
				if not isinstance(moved, (int, Degree, ChordTone)):
					raise TypeError(f"transpose cannot aim an Approach at {type(moved).__name__} content")
				return Approach(moved)

			if steps is not None:
				if isinstance(pitch, Degree):
					return dataclasses.replace(pitch, step=pitch.step + steps)
				raise TypeError(
					f"transpose(steps=) moves scale degrees — {type(pitch).__name__} content "
					f"has no degrees (use semitones= for MIDI ints)"
				)

			assert semitones is not None	# exactly one of steps/semitones is set (validated above)

			if isinstance(pitch, int):
				return pitch + semitones
			if isinstance(pitch, Degree):
				return dataclasses.replace(pitch, chroma=pitch.chroma + semitones)
			raise TypeError(f"transpose(semitones=) cannot move {type(pitch).__name__} content")

		events = tuple(dataclasses.replace(e, pitch=move(e.pitch)) for e in self.events)

		return Motif(events=events, length=self.length, controls=self.controls)

	def invert (self, pivot: typing.Optional[int] = None) -> "Motif":

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
				raise TypeError(f"invert() cannot derive a pivot from {type(first).__name__} content")

		def mirror (pitch: PitchSpec) -> PitchSpec:

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
				return dataclasses.replace(pitch, step=mirrored, chroma=-pitch.chroma)
			raise TypeError(f"invert() cannot mirror {type(pitch).__name__} content")

		events = tuple(dataclasses.replace(e, pitch=mirror(e.pitch)) for e in self.events)

		return Motif(events=events, length=self.length, controls=self.controls)

	# ── description ─────────────────────────────────────────────────────

	def describe (self) -> str:

		"""A readable one-line summary: length, notes (pitch@beat), and control gestures."""

		notes = ", ".join(f"{_pitch_label(e.pitch)}@{e.beat:g}" for e in self.events)
		parts = [f"Motif {self.length:g} beats", f"[{notes}]" if notes else "[no notes]"]

		if self.controls:
			gestures = ", ".join(_control_label(c) for c in self.controls)
			parts.append(f"controls [{gestures}]")

		return " ".join(parts)

	def __str__ (self) -> str:

		"""Printable form (same as :meth:`describe`)."""

		return self.describe()


def _pitch_label (pitch: PitchSpec) -> str:

	"""Compact label for a pitch spec in describe() output."""

	if pitch is None:
		return "·"
	if isinstance(pitch, Degree):
		marks = ("+" * pitch.octave if pitch.octave > 0 else "-" * -pitch.octave)
		chroma = (f"#{pitch.chroma}" if pitch.chroma > 0 else f"b{-pitch.chroma}" if pitch.chroma < 0 else "")
		return f"^{pitch.step}{marks}{chroma}"
	if isinstance(pitch, ChordTone):
		return f"tone{pitch.index}"
	if isinstance(pitch, Approach):
		return f">{_pitch_label(pitch.target)}"

	return str(pitch)


def _control_label (c: ControlEvent) -> str:

	"""Compact label for a control event in describe() output."""

	if isinstance(c.signal, CC):
		name = f"CC{c.signal.control}" if isinstance(c.signal.control, int) else f"CC:{c.signal.control}"
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
	"""

	source: Motif
	plan: typing.Union[typing.Tuple[str, ...], str]
	bars: int
	seed: typing.Optional[int]
	beats_per_bar: float = 4.0


def _contrast_unit (source: Motif, rng: random.Random) -> Motif:

	"""A generated contrast unit: the source's rhythm, freshly re-pitched.

	Roughly half the pitched notes move (small melodic nudges), so the unit
	is recognisably related but melodically new.  The richer rhythm-first
	generator arrives with the melody engine stage.
	"""

	pitched = sum(1 for event in source.events if event.pitch is not None)

	return source.vary(notes = max(1, pitched // 2), position = "anywhere", rng = rng)


def _call_response_units (call: Motif, seed: typing.Optional[int]) -> typing.List[Motif]:

	"""The call_response recipe: call, answer, call, varied answer."""

	response = call.answer()
	varied = response.vary(notes = 1, position = "end", rng = random.Random(f"{seed}:cr:vary"))

	return [call, response, call, varied]


# The curated recipe table — names reserved for plans whose semantics exceed
# a label skeleton.  Each takes (source_motif, seed) and returns the units.
_PHRASE_RECIPES: typing.Dict[str, typing.Callable[[Motif, typing.Optional[int]], typing.List[Motif]]] = {
	"call_response": _call_response_units,
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

	def __init__ (self, segments: typing.Iterable[Motif], recipe: typing.Optional[_PhraseRecipe] = None) -> None:

		"""Coerce any iterable of Motifs."""

		segments = tuple(segments)

		for segment in segments:
			if not isinstance(segment, Motif):
				raise TypeError(f"Phrase segments must be Motifs — got {type(segment).__name__}")

		object.__setattr__(self, "segments", segments)
		object.__setattr__(self, "recipe", recipe)

	@property
	def length (self) -> float:

		"""Total length in beats (sum of segment lengths)."""

		return sum(segment.length for segment in self.segments)

	@classmethod
	def develop (
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
				stacklevel = 2,
			)

		if isinstance(plan, str):

			if plan not in _PHRASE_RECIPES:
				known = ", ".join(sorted(_PHRASE_RECIPES))
				hint = ""
				if plan.isalpha() and plan == plan.lower() and len(set(plan)) < len(plan):
					spelled = ", ".join(repr(c) for c in plan)
					hint = f" A letter string is not a plan — a sequence of labels is a list: plan=[{spelled}]."
				raise ValueError(f"Unknown phrase recipe {plan!r}. Known recipes: {known}.{hint}")

			units = _PHRASE_RECIPES[plan](motif, seed)
			stored_plan: typing.Union[typing.Tuple[str, ...], str] = plan

		else:

			labels = list(plan)

			if not labels or not all(isinstance(label, str) and label for label in labels):
				raise ValueError("plan labels must be non-empty strings, e.g. plan=['a', 'a', 'b']")

			generated: typing.Dict[str, Motif] = {labels[0]: motif}

			for label in labels:
				if label not in generated:
					generated[label] = _contrast_unit(motif, random.Random(f"{seed}:unit:{label}"))

			units = [generated[label] for label in labels]
			stored_plan = tuple(labels)

		if bars % len(units) != 0:
			raise ValueError(
				f"bars={bars} does not divide evenly across {len(units)} plan units — "
				"each unit must fill a whole number of bars"
			)

		unit_beats = bars * beats_per_bar / len(units)

		if abs(motif.length - unit_beats) > 1e-9:
			raise ValueError(
				f"the motif is {motif.length:g} beats but each of the {len(units)} plan units "
				f"spans {unit_beats:g} beats ({bars} bars / {len(units)} units) — "
				"adjust bars, the plan, or the motif's length"
			)

		return cls(units, recipe = _PhraseRecipe(
			source = motif,
			plan = stored_plan,
			bars = bars,
			seed = seed,
			beats_per_bar = beats_per_bar,
		))

	def reroll (
		self,
		bar: typing.Optional[int] = None,
		bars: typing.Optional[typing.Sequence[int]] = None,
		seed: typing.Optional[int] = None,
	) -> "Phrase":

		"""Regenerate only the named bars — rhythm and boundary pitches kept.

		Within each named bar, the first and last pitched notes stay (the
		boundary pins) and the interior pitches re-roll from the recipe's
		stream; onsets, durations, velocities, rests, drums, and control
		gestures are untouched.  Segmentation and the recipe survive, so
		rerolls compose.

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
			raise ValueError("reroll() takes exactly one of bar= (an int) or bars= (a list)")

		region = [bar] if bar is not None else list(bars or [])
		beats_per_bar = self.recipe.beats_per_bar
		total_bars = int(round(self.length / beats_per_bar))

		for number in region:
			if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= total_bars:
				raise ValueError(f"bar {number!r} is outside this phrase (1–{total_bars})")

		if seed is None:
			warnings.warn(
				"reroll() without seed= is nondeterministic — pass seed= so the "
				"value survives live reload",
				stacklevel = 2,
			)

		windows = [
			((number - 1) * beats_per_bar, number * beats_per_bar, random.Random(f"{seed}:reroll:{number}"))
			for number in sorted(set(region))
		]

		new_segments: typing.List[Motif] = []
		offset = 0.0

		for segment in self.segments:

			events = list(segment.events)

			for window_start, window_end, rng in windows:

				inside = [
					index for index, event in enumerate(events)
					if window_start <= offset + event.beat < window_end
					and event.pitch is not None and not isinstance(event.pitch, str)
				]

				# Boundary pins: the first and last pitched notes of the bar
				# stay; only the interior re-rolls.
				for index in inside[1:-1]:
					events[index] = dataclasses.replace(
						events[index],
						pitch = segment._nudged_pitch(events[index].pitch, rng),
					)

			new_segments.append(Motif(events = tuple(events), length = segment.length, controls = segment.controls))
			offset += segment.length

		return Phrase(new_segments, recipe = self.recipe)

	def flatten (self) -> Motif:

		"""Erase segmentation: one long Motif (the monoid homomorphism onto ``then``)."""

		return Motif.join(self.segments)

	# ── algebra ─────────────────────────────────────────────────────────

	def __add__ (self, other: typing.Any) -> "Phrase":

		"""Append a Motif segment, or concatenate another Phrase's segments."""

		if isinstance(other, Motif):
			return Phrase(self.segments + (other,))
		if isinstance(other, Phrase):
			return Phrase(self.segments + other.segments)

		return NotImplemented

	def __radd__ (self, other: typing.Any) -> "Phrase":

		"""A Motif on the left prepends as a segment."""

		if isinstance(other, Motif):
			return Phrase((other,) + self.segments)

		return NotImplemented

	def __mul__ (self, count: int) -> "Phrase":

		"""Tile the segments *count* times."""

		if not isinstance(count, int):
			return NotImplemented
		if count < 0:
			raise ValueError(f"Repetition count must be non-negative — got {count}")

		return Phrase(self.segments * count)

	__rmul__ = __mul__

	def __and__ (self, other: typing.Any) -> Motif:

		"""Parallel merge is vertical: Phrase operands flatten to Motif first."""

		if isinstance(other, (Motif, Phrase)):
			return self.flatten().stack(other)

		return NotImplemented

	def stack (self, other: typing.Union[Motif, "Phrase"]) -> Motif:

		"""The spelled form of ``&`` — flattens, then merges."""

		return self.flatten().stack(other)

	def slice (self, start: float, end: float) -> "Phrase":

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

	def replace (self, position: int, motif: Motif) -> "Phrase":

		"""Replace the segment at a 1-based position (musicians count from one)."""

		if not 1 <= position <= len(self.segments):
			raise IndexError(f"Phrase has {len(self.segments)} segments — position {position} is out of range (1-based)")

		segments = list(self.segments)
		segments[position - 1] = motif

		return Phrase(segments)

	# ── transforms: lifted segment-wise, except time-reordering ─────────

	def reverse (self) -> "Phrase":

		"""Reverse the whole timeline: segments reverse order AND each reverses internally."""

		return Phrase(tuple(segment.reverse() for segment in reversed(self.segments)))

	def rotate (self, beats: float) -> "Phrase":

		"""Rotate the whole timeline modulo the total length, then re-segment at the original boundaries."""

		flat = self.flatten().rotate(beats)
		segments = []
		offset = 0.0

		# Re-segment by onset (events keep their full durations — a note may
		# ring past its new segment, exactly as it does on the flat timeline).
		for segment in self.segments:
			lo, hi = offset, offset + segment.length
			segments.append(Motif(
				events = tuple(
					dataclasses.replace(e, beat=e.beat - lo)
					for e in flat.events if lo <= e.beat < hi
				),
				length = segment.length,
				controls = tuple(
					dataclasses.replace(c, beat=c.beat - lo)
					for c in flat.controls if lo <= c.beat < hi
				),
			))
			offset = hi

		return Phrase(segments)

	def _lift (self, name: str, *args: typing.Any, **kwargs: typing.Any) -> "Phrase":

		"""Apply a Motif transform to every segment."""

		return Phrase(tuple(getattr(segment, name)(*args, **kwargs) for segment in self.segments))

	def stretch (self, factor: float) -> "Phrase":

		"""Scale time in every segment (lengths scale with them)."""

		return self._lift("stretch", factor)

	def quantize (self, grid: float) -> "Phrase":

		"""Snap note onsets segment-wise."""

		return self._lift("quantize", grid)

	def with_velocity (self, velocity: typing.Union[int, typing.Tuple[int, int]]) -> "Phrase":

		"""Replace every note's velocity, segment-wise."""

		return self._lift("with_velocity", velocity)

	def pitched (self, spec: PitchSpec) -> "Phrase":

		"""Replace every pitch, segment-wise."""

		return self._lift("pitched", spec)

	def rhythm (self) -> "Phrase":

		"""Strip pitches segment-wise: a phrase-shaped skeleton."""

		return self._lift("rhythm")

	def transpose (self, steps: typing.Optional[int] = None, semitones: typing.Optional[int] = None) -> "Phrase":

		"""Transpose every segment (see :meth:`Motif.transpose`)."""

		return self._lift("transpose", steps=steps, semitones=semitones)

	def invert (self, pivot: typing.Optional[int] = None) -> "Phrase":

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

	def describe (self) -> str:

		"""A readable summary: total length and each segment on its own line."""

		header = f"Phrase {self.length:g} beats, {len(self.segments)} segments"
		lines = [f"  {i + 1}. {segment.describe()}" for i, segment in enumerate(self.segments)]

		return "\n".join([header] + lines)

	def __str__ (self) -> str:

		"""Printable form (same as :meth:`describe`)."""

		return self.describe()


def motif (
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
		beats = beats,
		velocities = velocities,
		durations = durations,
		probabilities = probabilities,
		length = length,
	)
