import dataclasses
import typing


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


	def on_reschedule (self) -> None:

		"""
		Hook called immediately before the pattern is rescheduled.
		"""

		return None
