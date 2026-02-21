"""Chord definitions and pitch class utilities.

This module provides chord quality definitions, pitch class mappings, and the `Chord` class
for representing and manipulating chords.

Module-level constants:
- `NOTE_NAME_TO_PC`: Maps note names (e.g., `"C"`, `"F#"`, `"Bb"`) to pitch classes (0-11)
- `PC_TO_NOTE_NAME`: Maps pitch classes to note names
- `CHORD_INTERVALS`: Maps chord quality names to interval lists (semitones from root)
- `CHORD_SUFFIX`: Maps chord quality names to human-readable suffixes (e.g., `"m"`, `"7"`)

Module-level helpers:
- `key_name_to_pc(key_name)`: Validate a key name and return its pitch class (0–11).
  Raises `ValueError` for unknown names. This is the canonical key validation function
  used by `harmony.py`, `pattern_builder.quantize()`, and `chord_graphs.validate_key_name()`.

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


def key_name_to_pc (key_name: str) -> int:

	"""Validate a key name and return its pitch class (0–11).

	Parameters:
		key_name: Note name (e.g. ``"C"``, ``"F#"``, ``"Bb"``).

	Returns:
		Pitch class integer (0–11).

	Raises:
		ValueError: If the key name is not recognised.

	Example:
		```python
		key_name_to_pc("C")   # → 0
		key_name_to_pc("F#")  # → 6
		key_name_to_pc("Bb")  # → 10
		```
	"""

	if key_name not in NOTE_NAME_TO_PC:
		raise ValueError(
			f"Unknown key name: {key_name!r}. Expected e.g. 'C', 'F#', 'Bb'."
		)

	return NOTE_NAME_TO_PC[key_name]


CHORD_INTERVALS: typing.Dict[str, typing.List[int]] = {
	"major": [0, 4, 7],
	"minor": [0, 3, 7],
	"diminished": [0, 3, 6],
	"augmented": [0, 4, 8],
	"dominant_7th": [0, 4, 7, 10],
	"major_7th": [0, 4, 7, 11],
	"minor_7th": [0, 3, 7, 10],
	"half_diminished_7th": [0, 3, 6, 10],
	"sus2": [0, 2, 7],
	"sus4": [0, 5, 7],
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
	"sus2": "sus2",
	"sus4": "sus4",
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

		Finds the MIDI note corresponding to the chord's root pitch class that is
		closest to the provided ``root`` argument.

		Parameters:
			root: MIDI note number (e.g., 60 = middle C) to center the chord around.
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
			chord.tones(root=60)               # [60, 64, 67] - root position around C4
			chord.tones(root=62)               # [60, 64, 67] - still finds C4 as closest root
			chord.tones(root=70)               # [72, 76, 79] - finds C5 as closest root
			```
		"""

		# Find the MIDI note for self.root_pc that is closest to the requested root.
		# This handles octaves automatically.
		offset = (self.root_pc - root) % 12
		if offset > 6:
			offset -= 12
		
		effective_root = root + offset

		intervals = self.intervals()

		if inversion != 0:
			intervals = subsequence.voicings.invert_chord(intervals, inversion)

		if count is not None:
			n = len(intervals)
			return [effective_root + intervals[i % n] + 12 * (i // n) for i in range(count)]

		return [effective_root + interval for interval in intervals]


	def root_note (self, root_midi: int) -> int:

		"""
		Return the MIDI note number for the chord root nearest to *root_midi*.

		This is equivalent to ``self.tones(root_midi)[0]`` but makes intent
		explicit when you only need the single root pitch.

		Parameters:
			root_midi: Reference MIDI note number used to find the closest octave
			           of this chord's root pitch class.

		Returns:
			MIDI note number of the chord root.

		Example:
			```python
			chord = Chord(root_pc=4, quality="major")  # E major
			chord.root_note(60)   # → 64  (E4, nearest to C4)
			chord.root_note(69)   # → 64  (E4, nearest to A4)
			```
		"""

		return self.tones(root_midi)[0]


	def bass_note (self, root_midi: int, octave_offset: int = -1) -> int:

		"""
		Return the chord root shifted by a number of octaves.

		Commonly used to produce a bass register note one or two octaves
		below the chord voicing.

		Parameters:
			root_midi: Reference MIDI note number (passed to :meth:`root_note`).
			octave_offset: Octaves to shift; negative moves down (default ``-1``).

		Returns:
			MIDI note number of the chord root in the target register.

		Example:
			```python
			chord = Chord(root_pc=4, quality="major")  # E major
			chord.bass_note(64)        # → 52  (E3, one octave down from E4)
			chord.bass_note(64, -2)    # → 40  (E2, two octaves down)
			```
		"""

		return self.root_note(root_midi) + (12 * octave_offset)


	def name (self) -> str:

		"""
		Return a human-friendly chord name.
		"""

		root_name = PC_TO_NOTE_NAME[self.root_pc % 12]
		suffix = CHORD_SUFFIX.get(self.quality, "")

		return f"{root_name}{suffix}"
