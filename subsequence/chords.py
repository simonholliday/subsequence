import dataclasses
import typing


NOTE_NAME_TO_PC: typing.Dict[str, int] = {
	"C": 0,
	"C#": 1,
	"Db": 1,
	"D": 2,
	"D#": 3,
	"Eb": 3,
	"E": 4,
	"F": 5,
	"F#": 6,
	"Gb": 6,
	"G": 7,
	"G#": 8,
	"Ab": 8,
	"A": 9,
	"A#": 10,
	"Bb": 10,
	"B": 11,
}

PC_TO_NOTE_NAME: typing.List[str] = [
	"C",
	"C#",
	"D",
	"D#",
	"E",
	"F",
	"F#",
	"G",
	"G#",
	"A",
	"A#",
	"B",
]


CHORD_INTERVALS: typing.Dict[str, typing.List[int]] = {
	"major": [0, 4, 7],
	"minor": [0, 3, 7],
	"diminished": [0, 3, 6],
	"augmented": [0, 4, 8],
	"dominant_7th": [0, 4, 7, 10],
	"major_7th": [0, 4, 7, 11],
	"minor_7th": [0, 3, 7, 10],
	"half_diminished_7th": [0, 3, 6, 10],
}

CHORD_SUFFIX: typing.Dict[str, str] = {
	"major": "",
	"minor": "m",
	"diminished": "dim",
	"augmented": "+",
	"dominant_7th": "7",
	"major_7th": "maj7",
	"minor_7th": "m7",
	"half_diminished_7th": "m7b5",
}


@dataclasses.dataclass(frozen=True)
class Chord:

	"""
	Represents a chord as a root pitch class and quality.
	"""

	root_pc: int
	quality: str


	def intervals (self) -> typing.List[int]:

		"""
		Return the chord intervals for this chord quality.
		"""

		if self.quality not in CHORD_INTERVALS:
			raise ValueError(f"Unknown chord quality: {self.quality}")

		return CHORD_INTERVALS[self.quality]


	def tones (self, root: int) -> typing.List[int]:

		"""
		Return MIDI note numbers for chord tones starting from a root.
		"""

		return [root + interval for interval in self.intervals()]


	def name (self) -> str:

		"""
		Return a human-friendly chord name.
		"""

		root_name = PC_TO_NOTE_NAME[self.root_pc % 12]
		suffix = CHORD_SUFFIX.get(self.quality, "")

		return f"{root_name}{suffix}"
