import dataclasses
import typing

import subsequence.constants
import subsequence.constants.velocity
import subsequence.swing


@dataclasses.dataclass
class Note:

	"""
	Represents a single MIDI note.
	"""

	pitch: int
	velocity: int
	duration: int
	channel: int


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

	def __init__ (self, channel: int, length: float = 16, reschedule_lookahead: float = 1) -> None:

		"""
		Initialize a new pattern with MIDI channel, length in beats, and reschedule lookahead.
		"""

		self.channel = channel
		self.length = length
		self.reschedule_lookahead = reschedule_lookahead

		self.steps: typing.Dict[int, Step] = {}
		self.cc_events: typing.List[CcEvent] = []
		self.osc_events: typing.List[OscEvent] = []


	def add_note (self, position: int, pitch: int, velocity: int, duration: int) -> None:

		"""
		Add a note to the pattern at a specific pulse position.
		"""

		if position not in self.steps:
			self.steps[position] = Step()

		note = Note(
			pitch = pitch,
			velocity = velocity,
			duration = duration,
			channel = self.channel
		)

		self.steps[position].notes.append(note)


	def add_sequence (self, sequence: typing.List[int], step_duration: int, pitch: int, velocity: typing.Union[int, typing.List[int]] = subsequence.constants.velocity.DEFAULT_VELOCITY, note_duration: int = 6) -> None:

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
					position = i * step_duration,
					pitch = pitch,
					velocity = int(vel),
					duration = note_duration
				)

	def add_note_beats (self, beat_position: float, pitch: int, velocity: int, duration_beats: float, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Add a note to the pattern at a beat position.
		"""

		if beat_position < 0:
			raise ValueError("Beat position cannot be negative")

		if duration_beats <= 0:
			raise ValueError("Beat duration must be positive")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		position = int(beat_position * pulses_per_beat)
		duration = int(duration_beats * pulses_per_beat)

		if duration <= 0:
			raise ValueError("Beat duration must be at least one pulse")

		self.add_note(
			position = position,
			pitch = pitch,
			velocity = velocity,
			duration = duration
		)


	def add_sequence_beats (self, sequence: typing.List[int], step_beats: float, pitch: int, velocity: typing.Union[int, typing.List[int]] = subsequence.constants.velocity.DEFAULT_VELOCITY, note_duration_beats: float = 0.25, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Add a sequence of notes using beat durations.
		"""

		if step_beats <= 0:
			raise ValueError("Step duration must be positive")

		if note_duration_beats <= 0:
			raise ValueError("Note duration must be positive")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		step_duration = int(step_beats * pulses_per_beat)
		note_duration = int(note_duration_beats * pulses_per_beat)

		if step_duration <= 0:
			raise ValueError("Step duration must be at least one pulse")

		if note_duration <= 0:
			raise ValueError("Note duration must be at least one pulse")

		self.add_sequence(
			sequence = sequence,
			step_duration = step_duration,
			pitch = pitch,
			velocity = velocity,
			note_duration = note_duration
		)

	def add_arpeggio_beats (self, pitches: typing.List[int], step_beats: float, velocity: int = subsequence.constants.velocity.DEFAULT_VELOCITY, duration_beats: typing.Optional[float] = None, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Add an arpeggio that cycles through pitches at regular intervals.
		"""

		if not pitches:
			raise ValueError("Pitches list cannot be empty")

		if step_beats <= 0:
			raise ValueError("Step duration must be positive")

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		if duration_beats is None:
			duration_beats = step_beats

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
			beat += step_beats
			pitch_index += 1


	def apply_swing (self, swing_ratio: float = 2.0, pulses_per_quarter: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Apply swing timing to the pattern steps.
		"""

		self.steps = subsequence.swing.apply_swing(
			steps = self.steps,
			swing_ratio = swing_ratio,
			pulses_per_quarter = pulses_per_quarter
		)


	def on_reschedule (self) -> None:

		"""
		Hook called immediately before the pattern is rescheduled.
		"""

		return None
