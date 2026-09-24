"""Note and pattern data types - the rendered output layer.

Defines ``Note`` (a single scheduled MIDI event) alongside the control-event
records (``CcEvent``, ``RawNoteEvent``, ``OscEvent``) and ``Pattern``, the
ordered bag of events that ``PatternBuilder`` produces and the sequencer
schedules.  These are plain data, and mutable: the builder fills them, and
transforms such as ``reverse()`` rewrite them in place.  Only ``PlacedNote``,
the read-back copy ``PatternBuilder.placed()`` returns, is frozen.  The
building verbs live in ``pattern_builder``.
"""

import dataclasses
import random
import typing

import subsequence.constants
import subsequence.constants.pulses
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


def check_midi_range (value: typing.Any, what: str, where: str, low: int = 0, high: int = 127) -> int:

	"""Refuse a number MIDI cannot carry, and say which number it was.

	A pitch of 140, a velocity of 300 or a CC number of 200 used to be stored
	happily and then rejected by mido on every single cycle, logged as "MIDI
	send failed (device may be disconnected)" - so the composer looked at
	their cables (#3004).  One run of ``hit_steps(velocity=(100, 160))`` dropped
	five notes of eight that way.

	It is refused where it is written instead, naming the value and the thing
	it was meant to be.  A library generator folds its own output into range
	rather than reaching here - see ``sequence_utils.fold_to_midi_range``.
	"""

	try:
		number = int(value)
	except (TypeError, ValueError):
		raise ValueError(f"{where}: {what} must be a whole number, got {value!r}") from None

	if not low <= number <= high:
		raise ValueError(
			f"{where}: {what} must be {low}–{high}, got {number}. "
			f"MIDI cannot carry it, so it would be dropped at every send."
		)

	return number


def spaced_onsets (start: float, end: float, spacing: float, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> typing.List[float]:

	"""Every onset from *start* at *spacing* beats that plays before *end*.

	Each onset is ``start + i × spacing``, never a running sum.  Adding up a
	spacing that binary cannot hold exactly (a third of a beat, a tenth)
	lands just short of *end*, and the extra onset that let through fell on
	*end* itself: the next cycle's downbeat, or the next chord's first note
	(#2960).  An onset counts only if its pulse is before *end*'s, so float
	noise cannot put one there either.
	"""

	end_pulse = subsequence.constants.pulses.beats_to_pulses(end, pulses_per_beat)
	onsets: typing.List[float] = []
	index = 0

	while True:

		onset = start + index * spacing

		if onset >= end or subsequence.constants.pulses.beats_to_pulses(onset, pulses_per_beat) >= end_pulse:
			return onsets

		onsets.append(onset)
		index += 1


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
	nudge: int = 0							# Pulses that feel (swing, a groove, randomize()) has moved this note from the pulse it was placed on.  The transforms that read the grid count a note as the step it was placed on, however far the feel has carried it (see Pattern._placed_pulse, #3447).
	legato_group: typing.Optional[int] = None	# Which chord(legato=) or strum(legato=) placed this note, so the build's end sizes that call's notes, and only them, against the next attack (#3463).  Carried through every copy a transform makes.


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

	# For a Data Entry CC (6 or 38): the ("nrpn"|"rpn", number) this value was
	# written FOR.  A ramp selects its parameter once and then sends only Data
	# Entry, so anything else selecting a parameter in the window would silently
	# redirect the rest of it; the build's closing pass re-selects where this
	# says the selection has drifted (#3070).  None on a plain p.cc(6, …), which
	# is the user addressing whatever they last selected themselves.
	parameter: typing.Optional[typing.Tuple[str, int]] = None

	# For a pitch bend laid by portamento() or slide(): the (from pitch, to
	# pitch, laid amount) of the glide it belongs to.  A glide is laid in 12-TET
	# semitones, so a tuning re-aims it at the target as tuned, keeping each
	# bend's share of the way (#3476).  None on every other bend.
	glide: typing.Optional[typing.Tuple[int, int, float]] = None


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


@dataclasses.dataclass (frozen=True)
class PlacedNote:

	"""
	One note read back off a pattern being built - see ``PatternBuilder.placed()``.

	A read-only copy rather than a view: a consumer diffing what a generator
	added must not be able to reach through the answer and edit the pattern.
	Frozen also makes it hashable, so ``set(after) - set(before)`` works.

	Positions and durations are in **pulses**, the unit the pattern stores and
	the one every grid classification already uses (``PatternBuilder.thin()``
	documents that zone arithmetic).  Handing back beats would mean a float
	divide and a rounding rule that could disagree with the caller's on a note
	groove has nudged; a caller wanting beats divides by a constant and loses
	nothing.

	``duration`` is None for a drone, which has no end until a later
	``drone_off()`` places one.

	``index`` exists so two notes that are otherwise identical stay distinct:
	nothing stops a hand-placed kick and a generated one landing on the same
	pulse, and without it a set difference would report the second as already
	present.  It is an identity token, not a count - treat it as opaque.
	"""

	position: int						# Pulse position within the pattern
	pitch: int							# Resolved MIDI note number
	origin: typing.Optional[str]		# Original drum-name string (same contract as Note.origin), None for numeric pitches
	index: int							# Distinguishes notes sharing a position and pitch; opaque, stable only within one build
	velocity: int
	duration: typing.Optional[int]		# Pulses, or None for a drone (a raw Note On with no end)
	primary_unmapped: bool = False		# True when this pitch is a placeholder that the primary device will not sound (see Note.primary_unmapped)


class Pattern:

	"""
	Allows us to define and manipulate music pattern objects.
	"""

	def __init__ (self, channel: int, length: float = 16, reschedule_lookahead: float = 1, device: int = 0, mirrors: typing.Optional[typing.Iterable[MirrorSpec]] = None) -> None:

		"""
		Initialise a new pattern with MIDI channel, length in beats, and reschedule lookahead.

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
				third element - a ``drum_note_map`` - so a mirrored drum hit is
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

		# Builds that left glides and tunings to lay once the notes are where
		# they will finally sit (#2792).  The engine finishes its own builders
		# as each build ends; a builder made by hand for the Direct Pattern API
		# is finished by _finish_builds(), when the sequencer schedules the
		# pattern (#2959).
		self._unfinished_builds: typing.List[typing.Callable[[], None]] = []

		# Drum names already warned about (absent from every destination map)
		# so the per-cycle rebuild warns once, not every bar.  A hot-reload
		# builds a fresh Pattern, which resets this — re-surfacing the warning.
		self._warned_drum_names: typing.Set[str] = set()

		# Likewise warn once if a positioned chord/strum (beat != 0) uses sustain=/detached=,
		# which size their ring from the pattern length rather than from beat.
		self._warned_positioned_articulation: bool = False

		# The seed each random cellular_2d() start drew, by its place among a
		# build's cellular_2d() calls, beside the stream it was drawn from.  Kept,
		# so the grid evolves from bar to bar instead of being drawn afresh every
		# bar (#3072).  reroll() and lock() deal the pattern a new stream, and a
		# new stream draws again.
		self._drawn_grid_seeds: typing.Dict[int, typing.Tuple[typing.Optional[random.Random], int]] = {}


	def _finish_builds (self) -> None:

		"""Lay whatever a builder left for the end of its build and has not laid yet.

		The sequencer calls this as it schedules the pattern.  After a
		Composition's own build there is nothing left; a pattern built by hand
		with a ``PatternBuilder`` has its glides and tunings laid here (#2959).
		"""

		for finish in list(self._unfinished_builds):
			finish()

		self._unfinished_builds.clear()


	def _placed_pulse (self, position: int, note: Note) -> int:

		"""The pulse *note* was placed on, before any feel moved it to *position*.

		Swing, a groove and ``randomize()`` record how far they move each note
		(``Note.nudge``), so the transforms that read the grid - ``thin()``,
		``scale_velocities()`` and ``ratchet(steps=)`` - count it as the step it
		was placed on.  Classified where it plays, a sixteenth swung half a
		step late counted as the next step, and one pulled a pulse early as the
		step before (#3447).  A note nothing has moved gives back *position*,
		so each transform keeps its own rule for it.
		"""

		if not note.nudge:
			return position

		placed = position - note.nudge
		total_pulses = subsequence.constants.pulses.beats_to_pulses(self.length)

		# rotate() and reverse() wrap a note round the cycle, which can leave
		# the pulse it was placed on just outside the cycle: fold it back in.
		return placed % total_pulses if total_pulses > 0 else placed


	def add_note (self, position: int, pitch: int, velocity: int, duration: int, origin: typing.Optional[str] = None, primary_unmapped: bool = False) -> None:

		"""
		Add a note to the pattern at a specific pulse position.

		``origin`` is the original drum-name string when the pitch was named
		(e.g. ``"hi_hat_closed"``), or ``None`` for numeric pitches.  It is
		carried on the Note so mirror destinations can re-resolve the name
		through their own ``drum_note_map`` - see ``Sequencer.schedule_pattern``.

		``primary_unmapped`` marks a named hit whose ``origin`` is absent from
		this pattern's own ``drum_note_map`` but present in a mirror's - the
		primary device can't voice it, so it stays silent and only the mapping
		mirror(s) sound it.
		"""

		# Every note placed by any verb comes through here, which is why the
		# check lives here and not at a dozen entry points (#3004).
		pitch = check_midi_range(pitch, "pitch", "note")
		velocity = check_midi_range(velocity, "velocity", "note")

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

		# An explicit empty velocity list with hits to place has no velocity
		# to give them — say so instead of a bare ZeroDivisionError at the
		# modulo below (matches the builder-level _expand_sequence_param).
		if not velocity and any(sequence):
			raise ValueError("add_sequence(): velocity list cannot be empty")

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

		position = subsequence.constants.pulses.beats_to_pulses(beat_position, pulses_per_beat)

		# A positive duration shorter than one pulse clamps to one pulse —
		# the shortest sound the clock can represent — matching the duration
		# transforms (legato/detached/stretch), which clamp the same way.
		duration = max(1, subsequence.constants.pulses.beats_to_pulses(duration_beats, pulses_per_beat))

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

		spacing_pulses = subsequence.constants.pulses.beats_to_pulses(spacing_beats, pulses_per_beat)
		note_duration = subsequence.constants.pulses.beats_to_pulses(note_duration_beats, pulses_per_beat)

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

		for pitch_index, beat in enumerate(spaced_onsets(0.0, self.length, spacing_beats, pulses_per_beat)):
			self.add_note_beats(
				beat_position = beat,
				pitch = pitches[pitch_index % len(pitches)],
				velocity = velocity,
				duration_beats = duration_beats,
				pulses_per_beat = pulses_per_beat
			)


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

		position = subsequence.constants.pulses.beats_to_pulses(beat_position, pulses_per_beat)

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
