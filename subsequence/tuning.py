"""Microtonal tuning support for Subsequence.

Provides the ``Tuning`` class for specifying alternative tuning systems,
a parser for Scala ``.scl`` files, and ``apply_tuning_to_pattern()`` which
injects per-note pitch bend events so that any MIDI-compatible synthesiser
can play the tuning without MPE or special hardware support.

Pitch bend is injected automatically:

- **Monophonic patterns** (no overlapping notes): a single pitch bend event
  precedes each note on the pattern's own MIDI channel.
- **Polyphonic patterns** (overlapping notes): notes are spread across an
  explicit MIDI channel pool via ``ChannelAllocator``.  Each MIDI channel receives an
  independent pitch bend, so simultaneous notes can carry different tuning
  offsets.  The MIDI channel pool must be supplied by the caller.

Typical usage via ``Composition.tuning()`` (applies globally, automatically):

    comp.tuning("meanquar.scl", bend_range=2.0)

Per-pattern override via the ``PatternBuilder.apply_tuning()`` post-build
transform:

    p.apply_tuning(Tuning.equal(19), bend_range=2.0)
"""

import dataclasses
import logging
import math
import os
import typing
import weakref

import subsequence.pattern

logger = logging.getLogger(__name__)

# Parts already told their overlapping notes share one pitch wheel, so a part
# rebuilt every cycle is told once rather than every bar (#2799).
_warned_shared_wheel: "weakref.WeakSet[subsequence.pattern.Pattern]" = weakref.WeakSet()


# ── Tuning class ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Tuning:

	"""A microtonal tuning system expressed as cent offsets from the unison.

	The ``cents`` list contains the cent values for scale degrees 1 through N.
	Degree 0 (the unison, 0.0 cents) is always implicit and not stored.
	The last entry is typically 1200.0 cents (the octave) for octave-repeating
	scales, but any period is supported.

	Create a ``Tuning`` from a file or programmatically:

	    Tuning.from_scl("meanquar.scl")          # Scala .scl file
	    Tuning.from_cents([100, 200, ..., 1200])  # explicit cents
	    Tuning.from_ratios([9/8, 5/4, ..., 2])   # frequency ratios
	    Tuning.equal(19)                          # 19-tone equal temperament

	A MIDI note plays the degree it lands on, counting up from the reference
	note, so a twelve-degree table retunes ordinary music note for note, and
	a shorter one steps consecutive notes through its degrees.
	"""

	cents: typing.List[float]
	description: str = ""

	@property
	def size (self) -> int:
		"""Number of scale degrees per period (the .scl ``count`` line)."""
		return len(self.cents)

	@property
	def period_cents (self) -> float:
		"""Cent span of one period (typically 1200.0 for octave-repeating scales)."""
		return self.cents[-1] if self.cents else 1200.0

	# ── Factory methods ───────────────────────────────────────────────────────

	@classmethod
	def from_scl (cls, source: typing.Union[str, os.PathLike]) -> "Tuning":
		"""Parse a Scala .scl file.

		``source`` is a file path.  Lines beginning with ``!`` are comments.
		The first non-comment line is the description.  The second is the
		integer count of pitch values.  Each subsequent line is a pitch:

		- Contains ``.`` → cents (float).
		- Contains ``/`` or is a bare integer → ratio; converted to cents via
		  ``1200 × log₂(ratio)``.

		Raises ``ValueError`` for malformed files.
		"""
		with open(source, "r", encoding="utf-8") as fh:
			text = fh.read()
		return cls._parse_scl_text(text)

	@classmethod
	def from_scl_string (cls, text: str) -> "Tuning":
		"""Parse a Scala .scl file from a string (useful for testing)."""
		return cls._parse_scl_text(text)

	@classmethod
	def _parse_scl_text (cls, text: str) -> "Tuning":
		lines = [line.rstrip() for line in text.splitlines()]
		non_comment: typing.List[str] = [l for l in lines if not l.lstrip().startswith("!")]

		if len(non_comment) < 2:
			raise ValueError("Malformed .scl: need description + count lines")

		description = non_comment[0].strip()

		try:
			count = int(non_comment[1].strip())
		except ValueError:
			raise ValueError(f"Malformed .scl: expected integer count, got {non_comment[1]!r}")

		pitch_lines = non_comment[2:2 + count]

		if len(pitch_lines) < count:
			raise ValueError(
				f"Malformed .scl: expected {count} pitch values, got {len(pitch_lines)}"
			)

		cents_list: typing.List[float] = []
		for raw in pitch_lines:
			# Text after the pitch value is ignored (Scala spec)
			token = raw.split()[0] if raw.split() else ""
			cents_list.append(cls._parse_pitch_token(token))

		return cls(cents=cents_list, description=description)

	@staticmethod
	def _parse_pitch_token (token: str) -> float:
		"""Convert a single .scl pitch token to cents."""
		if not token:
			raise ValueError("Empty pitch token in .scl file")
		if "." in token:
			# Cents value
			return float(token)
		if "/" in token:
			# Ratio like 3/2
			num_str, den_str = token.split("/", 1)
			ratio = int(num_str) / int(den_str)
		else:
			# Bare integer like 2 (interpreted as 2/1)
			ratio = float(token)
		if ratio <= 0:
			raise ValueError(f"Non-positive ratio in .scl: {token!r}")
		return 1200.0 * math.log2(ratio)

	@classmethod
	def from_cents (cls, cents: typing.List[float], description: str = "") -> "Tuning":
		"""Construct a tuning from a list of cent values for degrees 1..N.

		The implicit degree 0 (unison, 0.0 cents) is not included in ``cents``.
		The last value is typically 1200.0 for an octave-repeating scale.
		"""
		return cls(cents=list(cents), description=description)

	@classmethod
	def from_ratios (cls, ratios: typing.List[float], description: str = "") -> "Tuning":
		"""Construct a tuning from frequency ratios relative to 1/1.

		Each ratio is converted to cents via ``1200 × log₂(ratio)``.
		Pass ``2`` or ``2.0`` for the octave (1200 cents).
		"""
		cents = [1200.0 * math.log2(r) for r in ratios]
		return cls(cents=cents, description=description)

	@classmethod
	def equal (cls, divisions: int = 12, period: float = 1200.0) -> "Tuning":
		"""Construct an equal-tempered tuning with ``divisions`` equal steps per period.

		``Tuning.equal(12)`` is standard 12-TET (no pitch bend needed).
		``Tuning.equal(19)`` gives 19-tone equal temperament.
		"""
		step = period / divisions
		cents = [step * i for i in range(1, divisions + 1)]
		return cls(
			cents=cents,
			description=f"{divisions}-tone equal temperament",
		)

	# ── Core calculation ──────────────────────────────────────────────────────

	def _continuous_pitch (self, midi_note: int, reference_note: int = 60) -> float:

		"""The pitch *midi_note* sounds at under this tuning, as a fractional 12-TET note number.

		The note is read as a scale degree counted from ``reference_note``.
		"""

		if self.size == 0:
			return float(midi_note)

		steps_from_root = midi_note - reference_note
		degree = steps_from_root % self.size
		octave = steps_from_root // self.size

		# Cent value for this degree (degree 0 = 0.0, degree k = cents[k-1])
		degree_cents = 0.0 if degree == 0 else self.cents[degree - 1]

		# Total cents from the root, as a 12-TET note number (100 cents a semitone)
		return reference_note + (octave * self.period_cents + degree_cents) / 100.0

	def pitch_bend_for_note (
		self,
		midi_note: int,
		reference_note: int = 60,
		bend_range: float = 2.0,
	) -> typing.Tuple[int, float]:
		"""Return ``(nearest_12tet_note, bend_normalized)`` for a MIDI note number.

		The MIDI note number is interpreted as a scale degree relative to
		``reference_note`` (default 60 = C4, degree 0 of the scale).  The
		tuning's cent table determines the exact frequency, and the nearest
		12-TET MIDI note plus a fractional pitch bend corrects the remainder.

		Parameters:
			midi_note: The MIDI note to tune (0–127).
			reference_note: MIDI note number that maps to degree 0 of the scale.
			bend_range: Pitch wheel range in semitones (must match the synth's
			    pitch-bend range setting).  Default ±2 semitones.

		Returns:
			A tuple ``(nearest_note, bend_normalized)`` where ``nearest_note``
			is the integer MIDI note to send and ``bend_normalized`` is the
			normalised pitch bend value (-1.0 to +1.0).
		"""
		if self.size == 0:
			return midi_note, 0.0

		continuous = self._continuous_pitch(midi_note, reference_note)

		nearest = int(round(continuous))
		nearest = max(0, min(127, nearest))

		offset_semitones = continuous - nearest  # signed, in semitones

		if bend_range <= 0:
			bend_normalized = 0.0
		else:
			bend_normalized = max(-1.0, min(1.0, offset_semitones / bend_range))

		return nearest, bend_normalized


# ── Channel allocator ─────────────────────────────────────────────────────────

class ChannelAllocator:

	"""Assign MIDI channels from a pool, rotating a polyphonic part across them.

	Tracks which MIDI channels are busy (a note is sounding) and which are free.
	A MIDI channel is reclaimed once its note ends (pulse ≥ release_pulse).

	A simple round-robin fallback is used when every MIDI channel in the pool is busy
	(simultaneous voices exceed pool size) - accompanied by a warning log.
	"""

	def __init__ (self, channels: typing.List[int]) -> None:
		if not channels:
			raise ValueError("ChannelAllocator requires at least one channel")
		self._channels = list(channels)
		# Map channel -> pulse at which it becomes free again
		self._release: typing.Dict[int, int] = {ch: 0 for ch in channels}
		self._rr_index = 0

	def allocate (self, pulse: int, duration: int) -> int:
		"""Return a free MIDI channel for a note starting at ``pulse`` lasting ``duration`` pulses."""
		# Find a channel that is free at this pulse
		for ch in self._channels:
			if self._release[ch] <= pulse:
				self._release[ch] = pulse + duration
				return ch

		# All channels busy — round-robin with a warning
		ch = self._channels[self._rr_index % len(self._channels)]
		self._rr_index += 1
		logger.warning(
			"ChannelAllocator: pool exhausted (%d channels, all busy at pulse %d). "
			"Simultaneous voices exceed pool size. Some pitch bends may conflict.",
			len(self._channels), pulse,
		)
		self._release[ch] = pulse + duration
		return ch


def resolve_channel_pool (channels: typing.Sequence[int], zero_indexed: bool = False) -> typing.List[int]:

	"""Read a tuning's MIDI channel pool as every other MIDI channel argument is read.

	A pool is numbered 1-16, or 0-15 when the composition was made with
	``zero_indexed_channels=True``, and comes back as the 0-15 MIDI channels the
	engine sends on.  A 0 in a 1-16 pool is refused with a message that says
	why, because a pool written when pools counted from 0 would otherwise
	play one MIDI channel low without a word.

	Parameters:
		channels: The pool as the musician numbered it.
		zero_indexed: Whether the composition numbers MIDI channels from 0.
	"""

	lowest, highest = (0, 15) if zero_indexed else (1, 16)

	if not zero_indexed and 0 in channels:
		raise ValueError(
			f"channels={list(channels)}: a tuning's channel pool is numbered 1-16, like every other channel, "
			f"so 0 is not a channel. Pools used to count from 0, so a pool written then is one channel low: "
			f"{[channel + 1 for channel in channels]} is the same pool now."
		)

	for channel in channels:
		if not lowest <= channel <= highest:
			raise ValueError(f"MIDI channel must be {lowest}-{highest}, got {channel} in channels={list(channels)}")

	return [channel if zero_indexed else channel - 1 for channel in channels]


# ── Pattern transform ─────────────────────────────────────────────────────────

def apply_tuning_to_pattern (
	pattern: "subsequence.pattern.Pattern",
	tuning: Tuning,
	bend_range: float = 2.0,
	channels: typing.Optional[typing.List[int]] = None,
	reference_note: int = 60,
	shared_pool: bool = False,
) -> bool:
	"""Apply a microtonal tuning to all notes in a pattern in place.

	For each note:

	1. The nearest 12-TET MIDI note is computed and replaces ``note.pitch``.
	2. A pitchwheel ``CcEvent`` is injected at the note's onset with the
	   fractional bend that corrects from the nearest 12-TET pitch to the
	   exact tuned frequency.
	3. If ``channels`` is provided and the pattern has overlapping notes,
	   notes are spread across the MIDI channel pool (``ChannelAllocator``).
	   A part that plays one note at a time moves to the pool's first
	   MIDI channel, unless the pool is ``shared_pool``, when it keeps its own.
	   Without a pool, overlapping notes share one MIDI channel's pitch wheel, so
	   each note's bend retunes the others; that is logged once per part.

	Existing pitchwheel events (e.g., from ``p.portamento()`` or
	``p.slide()``) are shifted additively by the tuning offset of the note
	sounding at each pulse.  Bend-reset-to-zero events are replaced with
	bend-reset-to-tuning-offset events.

	A drone - a raw ``note_on`` from ``p.drone()`` - is tuned the same way,
	with its bend at its onset on the part's own MIDI channel, and a ``note_off``
	takes the same nearest note, so ``p.drone_off()`` releases the note the
	drone sounds, in whichever cycle it comes (#3475).  A drone holds the
	MIDI channel's pitch wheel while it sounds, as any long note does.

	Parameters:
		pattern: The pattern to transform in place.
		tuning: The ``Tuning`` object specifying cent offsets.
		bend_range: Must match the MIDI synth's pitch-bend range setting
		    (default ±2 semitones).
		channels: Optional explicit MIDI channel pool for polyphonic parts, as
		    the 0-15 MIDI channels the engine sends on (``resolve_channel_pool``
		    reads a musician's numbering).  When ``None``, all notes stay on
		    ``pattern.channel``.  Under polyphonic rotation a glide's bends
		    (``portamento()``, ``slide()``) are not re-routed per note, so a
		    glide and a MIDI channel pool do not combine well.
		reference_note: MIDI note number mapped to scale degree 0.
		shared_pool: The pool is the whole composition's rather than this
		    part's own, so a part that plays one note at a time keeps its own
		    MIDI channel instead of taking the pool's first.

	Returns:
		Whether the part's notes rotated through the pool.
	"""
	_tune_drones(pattern, tuning, bend_range, reference_note)

	if not pattern.steps:
		return False

	# ── Step 1: determine if polyphony requires channel rotation ─────────────
	allocator: typing.Optional[ChannelAllocator] = None
	if channels is None:
		if pattern not in _warned_shared_wheel and _has_overlapping_notes(pattern):
			_warned_shared_wheel.add(pattern)
			builder = getattr(pattern, "_builder_fn", None)
			part = f"Tuned part '{builder.__name__}'" if builder is not None else f"A tuned part on channel {pattern.channel + 1}"
			logger.warning(
				f"{part} plays notes that overlap on one MIDI channel, which has a single pitch wheel, "
				"so every note sounding together takes the last tuning bend sent and at most one of them is in tune. "
				"Give it a channels= pool with a channel for each note that sounds at once."
			)
	else:
		# Check whether the pattern actually has overlapping notes
		if _has_overlapping_notes(pattern):
			allocator = ChannelAllocator(channels)
		# A part given its own pool plays through it even one note at a time,
		# on the pool's first channel.  A pool the composition shares is for
		# parts whose notes overlap: one playing a single line keeps its own
		# channel and pitch wheel, rather than landing on the channel of
		# another part's chord note and retuning it (#2798).
		elif channels and not shared_pool:
			# Re-assign the pattern's notes to the first pool channel
			for step in pattern.steps.values():
				for note in step.notes:
					note.channel = channels[0]

			# Pre-existing expression events (portamento/slide bends, CCs)
			# with no explicit channel would otherwise stay on
			# pattern.channel — targeting a channel where nothing sounds and
			# escaping the additive-shift pass below.
			for ev in pattern.cc_events:
				if ev.channel is None:
					ev.channel = channels[0]

	# ── Step 2: build a pulse→(tuning_bend_normalized, note_channel) map ─────
	# We need this for two things:
	#   - Injecting onset pitch bend events
	#   - Shifting existing pitchwheel events additively
	#
	# tuning_map: pulse → list of (tuning_bend_raw_int, channel)
	# For overlapping notes on the same pulse, each gets its own channel.

	tuning_map: typing.Dict[int, typing.List[typing.Tuple[int, int]]] = {}

	for pulse, step in sorted(pattern.steps.items()):
		for note in step.notes:
			nearest, bend_norm = tuning.pitch_bend_for_note(
				note.pitch, reference_note=reference_note, bend_range=bend_range
			)

			# Assign channel (rotation or single channel)
			if allocator is not None:
				note.channel = allocator.allocate(pulse, note.duration)
			# (else note.channel stays as set above or unchanged)

			# Replace pitch with nearest 12-TET note
			note.pitch = nearest

			bend_raw = _norm_to_raw(bend_norm)

			if pulse not in tuning_map:
				tuning_map[pulse] = []
			tuning_map[pulse].append((bend_raw, note.channel))

	# ── Step 3: shift existing pitchwheel events additively ──────────────────
	# Build a timeline of (pulse, note_end_pulse, bend_raw, channel) for
	# all tuning bends, so we can look up which tuning offset is active
	# at any given pulse/channel.

	# Sorted list of (onset_pulse, end_pulse, bend_raw, channel)
	timeline: typing.List[typing.Tuple[int, int, int, int]] = []
	for pulse, step in sorted(pattern.steps.items()):
		for note in step.notes:
			# Find the bend_raw that was computed for this note/pulse/channel
			# (use the first matching entry for this channel)
			for br, ch in tuning_map.get(pulse, []):
				if ch == note.channel:
					timeline.append((pulse, pulse + note.duration, br, ch))
					break

	def _active_bend_at (pulse: int, channel: int) -> int:
		"""Return the tuning bend_raw active for (pulse, channel), or 0."""
		result = 0
		for onset, end, br, ch in timeline:
			if ch == channel and onset <= pulse < end:
				result = br
				break
		return result

	# Shift existing pitchwheel events
	new_cc: typing.List["subsequence.pattern.CcEvent"] = []
	for ev in pattern.cc_events:
		if ev.message_type != "pitchwheel":
			new_cc.append(ev)
			continue

		if ev.glide is not None:
			new_cc.append(dataclasses.replace(ev, value=_tuned_glide_bend(ev.value, ev.glide, tuning, bend_range, reference_note)))
			continue

		ch = ev.channel if ev.channel is not None else pattern.channel
		active = _active_bend_at(ev.pulse, ch)

		if ev.value == 0:
			# Bend-reset: replace with tuning offset (so glides land correctly)
			shifted = active
		else:
			# Additive shift
			shifted = max(-8192, min(8191, ev.value + active))

		new_cc.append(dataclasses.replace(ev, value=shifted))

	pattern.cc_events = new_cc

	# ── Step 4: inject onset tuning bend events ───────────────────────────────
	# priority=-1 makes the bend dispatch BEFORE the note_on that shares its
	# pulse — the scheduler pushes all notes before cc events, so list order
	# alone cannot deliver the bend-first requirement; the priority field on
	# MidiEvent outranks the push-order tie-breaker.
	onset_events: typing.List["subsequence.pattern.CcEvent"] = []
	for pulse, entries in sorted(tuning_map.items()):
		for bend_raw, channel in entries:
			onset_events.append(
				subsequence.pattern.CcEvent(
					pulse=pulse,
					message_type="pitchwheel",
					value=bend_raw,
					channel=channel,
					priority=-1,
				)
			)

	# Prepend onset bends (kept first in the list for readability; the
	# dispatch order guarantee comes from priority above)
	pattern.cc_events = onset_events + pattern.cc_events

	return allocator is not None


def _tune_drones (
	pattern: "subsequence.pattern.Pattern",
	tuning: Tuning,
	bend_range: float,
	reference_note: int,
) -> None:

	"""Tune a pattern's raw note events, which the step pass never visits.

	A drone's ``note_on`` sounded its 12-TET pitch beside tuned notes: under
	19-TET a note 62 became 61 bent +1078 while a drone 62 stayed 62 (#3475).
	Each ``note_on`` takes the nearest note and a bend at its onset, sent
	before it, and each ``note_off`` the same nearest note.
	"""

	bends: typing.List["subsequence.pattern.CcEvent"] = []

	for event in pattern.raw_note_events:
		nearest, bend_norm = tuning.pitch_bend_for_note(event.pitch, reference_note=reference_note, bend_range=bend_range)
		event.pitch = nearest

		if event.message_type == "note_on":
			bends.append(
				subsequence.pattern.CcEvent(
					pulse = event.pulse,
					message_type = "pitchwheel",
					value = _norm_to_raw(bend_norm),
					channel = pattern.channel,
					priority = -1,
				)
			)

	pattern.cc_events = bends + pattern.cc_events


def _tuned_glide_bend (
	value: int,
	glide: typing.Tuple[int, int, float],
	tuning: Tuning,
	bend_range: float,
	reference_note: int,
) -> int:

	"""A glide's bend re-aimed at its target's tuned pitch.

	The glide was laid in 12-TET toward its target, so under 19-TET a
	portamento from 60 to 62 climbed toward 200 cents and the target then
	sounded at 126: an overshoot and a snap (#3476).  The bend keeps its
	share of the way, and the way becomes the tuned distance between the two
	notes, measured from the nearest note the first of them sounds on - so
	the glide starts where the first note sounds and arrives where the second
	does.
	"""

	source, target, amount = glide
	start = tuning._continuous_pitch(source, reference_note)
	end = tuning._continuous_pitch(target, reference_note)
	sounding = max(0, min(127, int(round(start))))
	share = (value / 8192.0) / amount if amount else 0.0

	if bend_range <= 0:
		return 0

	return _norm_to_raw(((start - sounding) + share * (end - start)) / bend_range)


def _has_overlapping_notes (pattern: "subsequence.pattern.Pattern") -> bool:
	"""Return True if any notes in the pattern overlap in time."""
	# Build a list of (onset, offset) across all notes
	intervals: typing.List[typing.Tuple[int, int]] = []
	for pulse, step in pattern.steps.items():
		for note in step.notes:
			intervals.append((pulse, pulse + note.duration))

	# Sort by onset; check if any start before the previous one ends
	intervals.sort()
	for i in range(1, len(intervals)):
		if intervals[i][0] < intervals[i - 1][1]:
			return True
	return False


def _norm_to_raw (bend_normalized: float) -> int:
	"""Convert a normalised pitch bend (-1.0 to +1.0) to a raw MIDI value (-8192 to +8191)."""
	return max(-8192, min(8191, int(round(bend_normalized * 8192))))
