import dataclasses
import math
import typing

import subsequence.constants
import subsequence.pattern


@dataclasses.dataclass
class MotifNote:

	"""
	Represents a motif note stored by pulse position.
	"""

	pitch: int
	velocity: int
	duration: int


class Motif:

	"""
	A lightweight container for note events that can be rendered into a Pattern.
	"""

	def __init__ (self, pulses_per_beat: int = subsequence.constants.MIDI_QUARTER_NOTE) -> None:

		"""
		Initialize an empty motif.
		"""

		if pulses_per_beat <= 0:
			raise ValueError("Pulses per beat must be positive")

		self.pulses_per_beat = pulses_per_beat
		self.notes: typing.Dict[int, typing.List[MotifNote]] = {}


	def add_note_pulses (self, position: int, pitch: int, velocity: int, duration: int) -> None:

		"""
		Add a note at a pulse position.
		"""

		if position < 0:
			raise ValueError("Position cannot be negative")

		if duration <= 0:
			raise ValueError("Duration must be positive")

		if position not in self.notes:
			self.notes[position] = []

		self.notes[position].append(MotifNote(pitch=pitch, velocity=velocity, duration=duration))


	def add_note_beats (self, beat_position: float, pitch: int, velocity: int, duration_beats: float) -> None:

		"""
		Add a note at a beat position.
		"""

		if beat_position < 0:
			raise ValueError("Beat position cannot be negative")

		if duration_beats <= 0:
			raise ValueError("Beat duration must be positive")

		position = int(beat_position * self.pulses_per_beat)
		duration = int(duration_beats * self.pulses_per_beat)

		if duration <= 0:
			raise ValueError("Beat duration must be at least one pulse")

		self.add_note_pulses(position=position, pitch=pitch, velocity=velocity, duration=duration)


	def add_chord_beats (self, beat_position: float, pitches: typing.List[int], velocity: int, duration_beats: float) -> None:

		"""
		Add a chord by placing multiple notes at the same beat.
		"""

		for pitch in pitches:
			self.add_note_beats(
				beat_position = beat_position,
				pitch = pitch,
				velocity = velocity,
				duration_beats = duration_beats
			)


	def add_motif (self, motif: "Motif", offset_pulses: int = 0) -> None:

		"""
		Add another motif's notes with a pulse offset.
		"""

		if offset_pulses < 0:
			raise ValueError("Offset cannot be negative")

		for position, note_list in motif.notes.items():

			target_position = position + offset_pulses

			for note in note_list:
				self.add_note_pulses(
					position = target_position,
					pitch = note.pitch,
					velocity = note.velocity,
					duration = note.duration
				)


	def get_length_pulses (self) -> int:

		"""
		Return the motif length in pulses based on the latest note end.
		"""

		if not self.notes:
			return 0

		max_end = 0

		for position, note_list in self.notes.items():
			for note in note_list:
				max_end = max(max_end, position + note.duration)

		return max_end


	def get_length_beats (self) -> int:

		"""
		Return the motif length in whole beats.
		"""

		length_pulses = self.get_length_pulses()

		if length_pulses == 0:
			return 0

		return int(math.ceil(length_pulses / float(self.pulses_per_beat)))


	def to_pattern (self, channel: int, length_beats: typing.Optional[int] = None, reschedule_lookahead: int = 1) -> subsequence.pattern.Pattern:

		"""
		Render the motif into a Pattern.
		"""

		if length_beats is None:
			length_beats = self.get_length_beats()

		if length_beats <= 0:
			length_beats = 1

		pattern = subsequence.pattern.Pattern(
			channel = channel,
			length = length_beats,
			reschedule_lookahead = reschedule_lookahead
		)

		for position, note_list in self.notes.items():
			for note in note_list:
				pattern.add_note(
					position = position,
					pitch = note.pitch,
					velocity = note.velocity,
					duration = note.duration
				)

		return pattern
