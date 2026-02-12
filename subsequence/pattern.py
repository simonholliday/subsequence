import dataclasses
import typing

import subsequence.constants


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
class Step:

	"""
	Represents a collection of notes at a single point in time.
	"""

	notes: typing.List[Note] = dataclasses.field(default_factory=list)


class Pattern:

	"""
	Allows us to define and manipulate music pattern objects.
	"""

	def __init__ (self, channel: int, length: int = 16, time_signature: typing.Tuple[int, int] = (4, 4), reschedule_lookahead: int = 1) -> None:

		"""
		Initialize a new pattern with MIDI channel, length in beats, time signature, and reschedule lookahead.
		"""

		self.channel = channel
		self.length = length
		self.time_signature = time_signature
		self.reschedule_lookahead = reschedule_lookahead

		self.steps: typing.Dict[int, Step] = {}


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


	def add_sequence (self, sequence: typing.List[int], step_duration: int, pitch: int, velocity: typing.Union[int, typing.List[int]] = 100, note_duration: int = 6) -> None:

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


	def add_sequence_beats (self, sequence: typing.List[int], step_beats: float, pitch: int, velocity: typing.Union[int, typing.List[int]] = 100, note_duration_beats: float = 0.25, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

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


	def on_reschedule (self) -> None:

		"""
		Hook called immediately before the pattern is rescheduled.
		"""

		return None
