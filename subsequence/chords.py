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
  used by `harmony.py`, `pattern_builder.snap_to_scale()`, and `chord_graphs.validate_key_name()`.

Chord qualities: `"major"`, `"minor"`, `"diminished"`, `"augmented"`, `"dominant_7th"`,
`"major_7th"`, `"minor_7th"`, `"half_diminished_7th"`, `"sus2"`, `"sus4"`
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
	"diminished_7th": [0, 3, 6, 9],
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
	"diminished_7th": "dim7",
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

		A registered quality without a suffix prints as ``root(quality)``
		(e.g. ``"C(quartal)"``) rather than masquerading as a plain major.
		"""

		root_name = PC_TO_NOTE_NAME[self.root_pc % 12]

		if self.quality not in CHORD_SUFFIX:
			return f"{root_name}({self.quality})"

		return f"{root_name}{CHORD_SUFFIX[self.quality]}"


# Quality suffixes accepted by parse_chord(), including common alternates.  The
# canonical suffixes (the values of CHORD_SUFFIX) all round-trip, so a chord's
# own name() always re-parses to the same chord.
_SUFFIX_TO_QUALITY: typing.Dict[str, str] = {
	"": "major",
	"maj": "major",
	"M": "major",
	"m": "minor",
	"min": "minor",
	"-": "minor",
	"dim": "diminished",
	"o": "diminished",
	"°": "diminished",
	"aug": "augmented",
	"+": "augmented",
	"7": "dominant_7th",
	"dom7": "dominant_7th",
	"maj7": "major_7th",
	"M7": "major_7th",
	"m7": "minor_7th",
	"min7": "minor_7th",
	"-7": "minor_7th",
	"m7b5": "half_diminished_7th",
	"ø": "half_diminished_7th",
	"ø7": "half_diminished_7th",
	"halfdim": "half_diminished_7th",
	"dim7": "diminished_7th",
	"o7": "diminished_7th",
	"°7": "diminished_7th",
	"sus2": "sus2",
	"sus4": "sus4",
	"sus": "sus4",
}

# Snapshots of the shipped tables, taken before any register_chord_quality()
# call: built-in qualities and suffixes can never be overwritten.
_BUILTIN_QUALITY_NAMES: typing.FrozenSet[str] = frozenset(CHORD_INTERVALS)
_BUILTIN_SUFFIXES: typing.FrozenSet[str] = frozenset(_SUFFIX_TO_QUALITY)


def register_chord_quality (
	name: str,
	intervals: typing.List[int],
	suffix: typing.Optional[str] = None,
) -> None:

	"""Register a custom chord quality for use everywhere chords are used.

	The counterpart to :func:`subsequence.intervals.register_scale` — it opens
	the quality table so quartal stacks, clusters, and extended chords become
	first-class symbolic chords: they work in progressions, graphs, voice
	leading, and ``describe()`` output.

	Built-in qualities (e.g. ``"minor"``) cannot be overwritten.  Custom names
	may be re-registered freely — live reload re-runs registration on every
	save, so this must not raise.

	Parameters:
		name: Quality name (used as ``Chord(root_pc, quality=name)``).
		intervals: Semitone offsets from the root (e.g. ``[0, 5, 10]`` for a
			quartal stack, ``[0, 3, 7, 10, 14]`` for a minor 9th).  Must start
			with 0, ascend strictly, and stay within 0–24 (extensions reach
			past the octave).
		suffix: Optional chord-name suffix.  When given, ``parse_chord()``
			accepts ``"A" + suffix`` and ``Chord.name()`` prints it — so
			``register_chord_quality("minor_9th", [0, 3, 7, 10, 14], suffix="m9")``
			makes ``"Am9"`` parse from then on.  Must not collide with a
			built-in suffix.

	Example:
		```python
		import subsequence

		subsequence.register_chord_quality("quartal", [0, 5, 10], suffix="q4")
		subsequence.parse_chord("Dq4")   # → Chord(root_pc=2, quality="quartal")
		```
	"""

	if name in _BUILTIN_QUALITY_NAMES:
		raise ValueError(
			f"Cannot overwrite built-in chord quality '{name}'. "
			"Choose a different name for your custom quality."
		)

	if not intervals:
		raise ValueError("intervals must not be empty")
	if not all(isinstance(i, int) and not isinstance(i, bool) for i in intervals):
		raise ValueError("intervals must be whole numbers (semitone offsets)")
	if intervals[0] != 0:
		raise ValueError("intervals must start with 0 (the root)")
	if any(b <= a for a, b in zip(intervals, intervals[1:])):
		raise ValueError("intervals must be strictly ascending")
	if any(i < 0 or i > 24 for i in intervals):
		raise ValueError("intervals must contain values between 0 and 24")

	if suffix is not None:
		if suffix in _BUILTIN_SUFFIXES:
			raise ValueError(
				f"Suffix {suffix!r} is a built-in chord suffix and cannot be reused. "
				"Choose a different suffix for your custom quality."
			)
		if not suffix or suffix[0] in "ABCDEFG#b0123456789":
			raise ValueError(
				f"Suffix {suffix!r} would be ambiguous in a chord name — "
				"it must not be empty or start with a note letter, accidental, or digit"
			)

	# Re-registration: drop any suffix this quality registered previously, so
	# renaming a suffix on live reload does not leave a stale alias behind.
	for old_suffix in [s for s, q in _SUFFIX_TO_QUALITY.items() if q == name and s not in _BUILTIN_SUFFIXES]:
		del _SUFFIX_TO_QUALITY[old_suffix]

	CHORD_INTERVALS[name] = list(intervals)

	if suffix is not None:
		CHORD_SUFFIX[name] = suffix
		_SUFFIX_TO_QUALITY[suffix] = name
	else:
		CHORD_SUFFIX.pop(name, None)


def parse_chord (name: str) -> Chord:

	"""Parse a chord name like ``"Cm7"`` or ``"Dbmaj7"`` into a :class:`Chord`.

	The name is a root note (``A``–``G`` with an optional ``#`` or ``b``) followed
	by a quality suffix: ``""`` major, ``m`` minor, ``dim`` diminished,
	``+``/``aug`` augmented, ``7`` dominant 7th, ``maj7`` major 7th, ``m7`` minor
	7th, ``m7b5``/``ø`` half-diminished 7th, ``sus2``, ``sus4``.  A few common
	alternates (``min``, ``-``, ``M7``, …) are accepted too.

	Raises ``ValueError`` for anything it can't read, so a typo surfaces at the
	call site rather than as a silently wrong chord.

	Example:
		```python
		parse_chord("Cm7")    # → Chord(root_pc=0, quality="minor_7th")
		parse_chord("Dbmaj7") # → Chord(root_pc=1, quality="major_7th")
		parse_chord("F#")     # → Chord(root_pc=6, quality="major")
		```
	"""

	stripped = name.strip()
	if not stripped or stripped[0] not in "ABCDEFG":
		raise ValueError(f"Cannot parse chord name {name!r} — expected a root like 'C', 'F#', 'Bb' then a quality, e.g. 'Cm7'")

	split = 2 if (len(stripped) > 1 and stripped[1] in "#b") else 1
	root_name = stripped[:split]
	suffix = stripped[split:]

	if root_name not in NOTE_NAME_TO_PC:
		raise ValueError(f"Cannot parse chord name {name!r} — unknown root {root_name!r}")
	if suffix not in _SUFFIX_TO_QUALITY:
		known = ", ".join(repr(key) for key in sorted(_SUFFIX_TO_QUALITY) if key)
		raise ValueError(f"Cannot parse chord name {name!r} — unknown quality {suffix!r}. Known suffixes: {known}")

	return Chord(root_pc=NOTE_NAME_TO_PC[root_name], quality=_SUFFIX_TO_QUALITY[suffix])
