"""Chord definitions and pitch class utilities.

This module provides chord quality definitions, pitch class mappings, and the `Chord` class
for representing and manipulating chords.

Module-level constants:
- `NOTE_NAME_TO_PC`: Maps note names (e.g., `"C"`, `"F#"`, `"Bb"`) to pitch classes (0-11)
- `PC_TO_NOTE_NAME`: Maps pitch classes to note names
- `CHORD_INTERVALS`: Maps chord quality names to interval lists (semitones from root)
- `CHORD_SUFFIX`: Maps chord quality names to human-readable suffixes (e.g., `"m"`, `"7"`)

Chord qualities: `"major"`, `"minor"`, `"diminished"`, `"augmented"`, `"dominant_7th"`,
`"major_7th"`, `"minor_7th"`, `"half_diminished_7th"`
"""

import dataclasses
import typing

import subsequence.voicings


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


	def tones (self, root: int, inversion: int = 0, count: typing.Optional[int] = None) -> typing.List[int]:

		"""Return MIDI note numbers for chord tones starting from a root.

		Parameters:
			root: MIDI root note number (default 60 = middle C)
			inversion: Chord inversion (0 = root position, 1 = first, 2 = second, ...).
				Wraps around for values >= number of notes.
			count: Number of notes to return. When set, the chord intervals cycle
				into higher octaves until ``count`` notes are produced. When ``None``
				(default), returns the natural chord tones.

		Returns:
			List of MIDI note numbers for chord tones

		Example:
			```python
			chord = Chord(root_pc=0, quality="major")  # C major
			chord.tones(root=60)               # [60, 64, 67] — root position
			chord.tones(root=60, inversion=1)  # [60, 63, 68] — first inversion
			chord.tones(root=60, count=5)      # [60, 64, 67, 72, 76] — 5 notes cycling upward
			```
		"""

		intervals = self.intervals()

		if inversion != 0:
			intervals = subsequence.voicings.invert_chord(intervals, inversion)

		if count is not None:
			n = len(intervals)
			return [root + intervals[i % n] + 12 * (i // n) for i in range(count)]

		return [root + interval for interval in intervals]


	def name (self) -> str:

		"""
		Return a human-friendly chord name.
		"""

		root_name = PC_TO_NOTE_NAME[self.root_pc % 12]
		suffix = CHORD_SUFFIX.get(self.quality, "")

		return f"{root_name}{suffix}"
