"""Immutable note and pattern data types — the rendered output layer.

Defines ``Note`` (a single scheduled MIDI event) alongside the control-event
records (``CcEvent``, ``RawNoteEvent``, ``OscEvent``) and ``Pattern``, the
ordered bag of events that ``PatternBuilder`` produces and the sequencer
schedules.  These are plain data; the building verbs live in
``pattern_builder``.
"""

import dataclasses
import typing

import subsequence.constants
import subsequence.constants.velocity


# A mirror destination: ``(device, channel)`` or, to re-resolve drum names
# per device, ``(device, channel, drum_note_map)``.  The optional third element
# lets a mirrored drum hit sound the correct voice on a device whose drum map
# differs from the primary's — see ``Sequencer.schedule_pattern``.  The
# user-facing entry points accept any of these (and lists, for JSON sources);
# ``Composition._resolve_mirrors`` normalises channel numbering before storing.
MirrorSpec = typing.Union[
	typing.Tuple[int, int],
	typing.Tuple[int, int, typing.Optional[typing.Dict[str, int]]],
]


@dataclasses.dataclass
class Note:

	"""
	Represents a single MIDI note.
	"""

	pitch: int
	velocity: int
	duration: int
	channel: int
	origin: typing.Optional[str] = None		# Original drum-name string (if the pitch was named), kept so mirror destinations can re-resolve it through their own drum_note_map.  None for numeric/pitched notes.
	primary_unmapped: bool = False			# True when origin was NOT in the pattern's own (primary) drum_note_map — the primary device has no such voice, so it stays silent; only mirror destinations whose maps contain origin sound it.  pitch then holds a placeholder (a mirror's value) used only by transforms/display, never for playback.


@dataclasses.dataclass
class CcEvent:

	"""
	A MIDI non-note event (CC, pitch bend, program change, SysEx) at a pulse position.
	"""

	pulse: int
	message_type: str					# 'control_change', 'pitchwheel', 'program_change', or 'sysex'
	control: int = 0					# CC number (0–127), ignored for other types
	value: int = 0						# 0–127 for CC/program_change, -8192..8191 for pitchwheel
	data: typing.Optional[bytes] = None	# Raw bytes payload for SysEx messages
	channel: typing.Optional[int] = None	# If set, overrides pattern.channel for this event
	device: typing.Optional[int] = None	# If set, overrides pattern.device for this event
	priority: int = 0					# Same-pulse dispatch order vs notes: negative fires BEFORE note_on (tuning onset bends), 0 keeps FIFO order


@dataclasses.dataclass
class RawNoteEvent:

	"""
	An explicit Note On or Note Off event at a pulse position, ignoring durations.
	Used for drones and infinite notes.
	"""

	pulse: int
	message_type: str					# 'note_on' or 'note_off'
	pitch: int
	velocity: int = 0
	origin: typing.Optional[str] = None	# Original drum-name string, kept so mirror destinations re-resolve it through their own drum_note_map (same contract as Note.origin)
	primary_unmapped: bool = False		# Kept for _destination_pitch compatibility; always False for drones (an unvoiceable name is dropped at build time)


@dataclasses.dataclass
class OscEvent:

	"""
	An OSC message scheduled at a pulse position within a pattern.
	"""

	pulse: int
	address: str
	args: typing.Tuple[typing.Any, ...] = ()


@dataclasses.dataclass
class Step:

	"""
	Represents a collection of notes at a single point in time.
	"""

	notes: typing.List[Note] = dataclasses.field(default_factory=list)


class Pattern:

	"""
	Allows us to define and manipulate music pattern objects.
	"""

	def __init__ (self, channel: int, length: float = 16, reschedule_lookahead: float = 1, device: int = 0, mirrors: typing.Optional[typing.Iterable[MirrorSpec]] = None) -> None:

		"""
		Initialize a new pattern with MIDI channel, length in beats, and reschedule lookahead.

		Parameters:
			channel: The MIDI channel (0-15) this pattern will output to.
			length: The duration of the pattern before it loops/rebuilds, measured
				in beats (e.g., 16 = 4 bars in 4/4 time). Defaults to 16.
			reschedule_lookahead: How many beats before the end of the pattern the next
				cycle is built. Defaults to 1 beat. This provides a safe computational
				buffer so events are queued before the clock actually needs them.
			device: Output device index (0-indexed).  0 = primary device (default).
			mirrors: Additional ``(device, channel)`` destinations to duplicate every
				note, CC, pitch bend, program change, SysEx, NRPN/RPN burst, and
				drone event onto.  Both ``device`` and ``channel`` are 0-indexed in
				canonical form; the user-facing entry points (decorator and runtime
				API on ``Composition``) translate the user's channel-numbering
				convention before storing here.  An entry may carry an optional
				third element — a ``drum_note_map`` — so a mirrored drum hit is
				re-resolved by name to that device's own note number (see
				``Sequencer.schedule_pattern``).
		"""

		self.channel = channel
		self.length = length
		self.reschedule_lookahead = reschedule_lookahead
		self.device = device
		self.mirrors: typing.List[MirrorSpec] = list(mirrors) if mirrors else []

		# Set to True by ``Composition.unregister()`` to signal the sequencer's
		# reschedule loop to stop re-adding this pattern.  Lazy removal: events
		# already queued in ``event_queue`` play out; sustaining notes are
		# stopped by the unregister() call, but no new cycles fire.
		self._removed: bool = False

		# Absolute pulse where the cycle currently being (re)built starts.
		# Written by the sequencer on schedule and on every reschedule; read
		# by rebuilds that place the cycle on the absolute beat axis (the
		# harmony window).
		self._cycle_start_pulse: int = 0

		self.steps: typing.Dict[int, Step] = {}
		self.cc_events: typing.List[CcEvent] = []
		self.osc_events: typing.List[OscEvent] = []
		self.raw_note_events: typing.List[RawNoteEvent] = []

		# Drum names already warned about (absent from every destination map)
		# so the per-cycle rebuild warns once, not every bar.  A hot-reload
		# builds a fresh Pattern, which resets this — re-surfacing the warning.
		self._warned_drum_names: typing.Set[str] = set()

		# Likewise warn once if a positioned chord/strum (beat != 0) uses sustain=/detached=,
		# which size their ring from the pattern length rather than from beat.
		self._warned_positioned_articulation: bool = False


	def add_note (self, position: int, pitch: int, velocity: int, duration: int, origin: typing.Optional[str] = None, primary_unmapped: bool = False) -> None:

		"""
		Add a note to the pattern at a specific pulse position.

		``origin`` is the original drum-name string when the pitch was named
		(e.g. ``"hi_hat_closed"``), or ``None`` for numeric pitches.  It is
		carried on the Note so mirror destinations can re-resolve the name
		through their own ``drum_note_map`` — see ``Sequencer.schedule_pattern``.

		``primary_unmapped`` marks a named hit whose ``origin`` is absent from
		this pattern's own ``drum_note_map`` but present in a mirror's — the
		primary device can't voice it, so it stays silent and only the mapping
		mirror(s) sound it.
		"""

		if position not in self.steps:
			self.steps[position] = Step()

		note = Note(
			pitch = pitch,
			velocity = velocity,
			duration = duration,
			channel = self.channel,
			origin = origin,
			primary_unmapped = primary_unmapped
		)

		self.steps[position].notes.append(note)


	def add_sequence (self, sequence: typing.List[int], spacing_pulses: int, pitch: int, velocity: typing.Union[int, typing.List[int]] = subsequence.constants.velocity.DEFAULT_VELOCITY, note_duration: int = 6) -> None:

		"""
		Add a sequence of notes to the pattern.
		"""

		if isinstance(velocity, int):
			velocity = [velocity] * len(sequence)

		for i, hit in enumerate(sequence):

			if hit:

				# Handle case where velocity list might be shorter than sequence
				vel = velocity[i % len(velocity)]

				self.add_note(
					position = i * spacing_pulses,
					pitch = pitch,
					velocity = int(vel),
					duration = note_duration
				)

	def add_note_beats (self, beat_position: float, pitch: int, velocity: int, duration_beats: float, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE, origin: typing.Optional[str] = None, primary_unmapped: bool = False) -> None:

		"""
		Add a note to the pattern at a beat position.

		``origin`` and ``primary_unmapped`` are forwarded to ``add_note`` so
		the resulting Note carries the drum name and its primary-map status.
		"""

		if beat_position < 0:
			raise ValueError("Beat position cannot be negative")

		if duration_beats <= 0:
			raise ValueError("Beat duration must be positive")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		position = int(beat_position * pulses_per_beat)

		# A positive duration shorter than one pulse clamps to one pulse —
		# the shortest sound the clock can represent — matching the duration
		# transforms (legato/detached/stretch), which clamp the same way.
		duration = max(1, int(duration_beats * pulses_per_beat))

		self.add_note(
			position = position,
			pitch = pitch,
			velocity = velocity,
			duration = duration,
			origin = origin,
			primary_unmapped = primary_unmapped
		)


	def add_sequence_beats (self, sequence: typing.List[int], spacing_beats: float, pitch: int, velocity: typing.Union[int, typing.List[int]] = subsequence.constants.velocity.DEFAULT_VELOCITY, note_duration_beats: float = 0.25, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Add a sequence of notes using beat durations.
		"""

		if spacing_beats <= 0:
			raise ValueError("Spacing must be positive")

		if note_duration_beats <= 0:
			raise ValueError("Note duration must be positive")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		spacing_pulses = int(spacing_beats * pulses_per_beat)
		note_duration = int(note_duration_beats * pulses_per_beat)

		if spacing_pulses <= 0:
			raise ValueError("Spacing must be at least one pulse")

		if note_duration <= 0:
			raise ValueError("Note duration must be at least one pulse")

		self.add_sequence(
			sequence = sequence,
			spacing_pulses = spacing_pulses,
			pitch = pitch,
			velocity = velocity,
			note_duration = note_duration
		)

	def add_arpeggio_beats (self, pitches: typing.List[int], spacing_beats: float, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration_beats: typing.Optional[float] = None, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Add an arpeggio that cycles through pitches at regular intervals.
		"""

		if not pitches:
			raise ValueError("Pitches list cannot be empty")

		if spacing_beats <= 0:
			raise ValueError("Spacing must be positive")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		if duration_beats is None:
			duration_beats = spacing_beats

		if duration_beats <= 0:
			raise ValueError("Note duration must be positive")

		beat = 0.0
		pitch_index = 0

		while beat < self.length:
			pitch = pitches[pitch_index % len(pitches)]
			self.add_note_beats(
				beat_position = beat,
				pitch = pitch,
				velocity = velocity,
				duration_beats = duration_beats,
				pulses_per_beat = pulses_per_beat
			)
			beat += spacing_beats
			pitch_index += 1


	def add_raw_note_beats (self, message_type: str, beat_position: float, pitch: int, velocity: int = 0, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE, origin: typing.Optional[str] = None) -> None:

		"""
		Add a raw Note On or Note Off event at a beat position (ignores duration).

		``origin`` carries the drum-name string (if the pitch was named) so
		mirror destinations can re-resolve it through their own maps.
		"""

		if message_type not in ('note_on', 'note_off'):
			raise ValueError("message_type must be 'note_on' or 'note_off'")

		if beat_position < 0:
			raise ValueError("Beat position cannot be negative")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		position = int(beat_position * pulses_per_beat)

		self.raw_note_events.append(
			RawNoteEvent(
				pulse = position,
				message_type = message_type,
				pitch = pitch,
				velocity = velocity,
				origin = origin
			)
		)


	def on_reschedule (self) -> None:

		"""
		Hook called immediately before the pattern is rescheduled.
		"""

		return None
