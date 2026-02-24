import typing

import subsequence.chords


INTERVAL_DEFINITIONS: typing.Dict[str, typing.List[int]] = {
	"augmented": [0, 3, 4, 7, 8, 11],
	"augmented_7th": [0, 4, 8, 10],
	"augmented_triad": [0, 4, 8],
	"blues_scale": [0, 3, 5, 6, 7, 10],
	"chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
	"diminished_7th": [0, 3, 6, 9],
	"diminished_triad": [0, 3, 6],
	"dominant_7th": [0, 4, 7, 10],
	"dominant_9th": [0, 4, 7, 10, 14],
	"dorian_mode": [0, 2, 3, 5, 7, 9, 10],
	"double_harmonic": [0, 1, 4, 5, 7, 8, 11],
	"enigmatic": [0, 1, 4, 6, 8, 10, 11],
	"half_diminished_7th": [0, 3, 6, 10],
	"harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
	"hungarian_minor": [0, 2, 3, 6, 7, 8, 11],
	"locrian_mode": [0, 1, 3, 5, 6, 8, 10],
	"lydian": [0, 2, 4, 6, 7, 9, 11],
	"lydian_dominant": [0, 2, 4, 6, 7, 9, 10],
	"major_6th": [0, 4, 7, 9],
	"major_7th": [0, 4, 7, 11],
	"major_9th": [0, 4, 7, 11, 14],
	"major_ionian": [0, 2, 4, 5, 7, 9, 11],
	"major_pentatonic": [0, 2, 4, 7, 9],
	"major_triad": [0, 4, 7],
	"melodic_minor": [0, 2, 3, 5, 7, 9, 11],
	"minor_6th": [0, 3, 7, 9],
	"minor_7th": [0, 3, 7, 10],
	"minor_9th": [0, 3, 7, 10, 14],
	"minor_blues": [0, 3, 5, 6, 7, 10],
	"minor_major_7th": [0, 3, 7, 11],
	"minor_pentatonic": [0, 3, 5, 7, 10],
	"minor_triad": [0, 3, 7],
	"mixolydian": [0, 2, 4, 5, 7, 9, 10],
	"natural_minor": [0, 2, 3, 5, 7, 8, 10],
	"neapolitan_major": [0, 1, 3, 5, 7, 9, 11],
	"phrygian_dominant": [0, 1, 4, 5, 7, 8, 10],
	"phrygian_mode": [0, 1, 3, 5, 7, 8, 10],
	"power_chord": [0, 7],
	"superlocrian": [0, 1, 3, 4, 6, 8, 10],
	"sus2": [0, 2, 7],
	"sus4": [0, 5, 7],
	"whole_tone": [0, 2, 4, 6, 8, 10],
	# -- Non-western / pentatonic scales --
	"hirajoshi": [0, 2, 3, 7, 8],
	"in_sen": [0, 1, 5, 7, 10],
	"iwato": [0, 1, 5, 6, 10],
	"yo": [0, 2, 5, 7, 9],
	"egyptian": [0, 2, 5, 7, 10],
	"root": [0],
	"fifth": [0, 7],
	"minor_3rd": [0, 3],
	"tritone": [0, 6],
}


MAJOR_DIATONIC_TRIADS: typing.List[typing.List[int]] = [
	[0, 4, 7],
	[0, 3, 7],
	[0, 3, 7],
	[0, 4, 7],
	[0, 4, 7],
	[0, 3, 7],
	[0, 3, 6],
]


MAJOR_DIATONIC_SEVENTHS: typing.List[typing.List[int]] = [
	[0, 4, 7, 11],
	[0, 3, 7, 10],
	[0, 3, 7, 10],
	[0, 4, 7, 11],
	[0, 4, 7, 10],
	[0, 3, 7, 10],
	[0, 3, 6, 10],
]


MINOR_DIATONIC_TRIADS: typing.List[typing.List[int]] = [
	[0, 3, 7],
	[0, 3, 6],
	[0, 4, 7],
	[0, 3, 7],
	[0, 3, 7],
	[0, 4, 7],
	[0, 4, 7],
]


# ---------------------------------------------------------------------------
# Diatonic chord quality constants.
#
# Each list contains 7 chord quality strings, one per scale degree (I–VII).
# These can be paired with the corresponding scale intervals from
# INTERVAL_DEFINITIONS to build diatonic Chord objects for any key.
# ---------------------------------------------------------------------------

# -- Church modes (rotations of the major scale) --

IONIAN_QUALITIES: typing.List[str] = [
	"major", "minor", "minor", "major", "major", "minor", "diminished"
]

DORIAN_QUALITIES: typing.List[str] = [
	"minor", "minor", "major", "major", "minor", "diminished", "major"
]

PHRYGIAN_QUALITIES: typing.List[str] = [
	"minor", "major", "major", "minor", "diminished", "major", "minor"
]

LYDIAN_QUALITIES: typing.List[str] = [
	"major", "major", "minor", "diminished", "major", "minor", "minor"
]

MIXOLYDIAN_QUALITIES: typing.List[str] = [
	"major", "minor", "diminished", "major", "minor", "minor", "major"
]

AEOLIAN_QUALITIES: typing.List[str] = [
	"minor", "diminished", "major", "minor", "minor", "major", "major"
]

LOCRIAN_QUALITIES: typing.List[str] = [
	"diminished", "major", "minor", "minor", "major", "major", "minor"
]

# -- Non-modal scales --

HARMONIC_MINOR_QUALITIES: typing.List[str] = [
	"minor", "diminished", "augmented", "minor", "major", "major", "diminished"
]

MELODIC_MINOR_QUALITIES: typing.List[str] = [
	"minor", "minor", "augmented", "major", "major", "diminished", "diminished"
]


# Map mode/scale names to (interval_key, qualities) for use by helpers.
# qualities is None for scales without predefined chord mappings — these
# can still be used with scale_pitch_classes() and p.quantize(), but not
# with diatonic_chords() or composition.harmony().
SCALE_MODE_MAP: typing.Dict[str, typing.Tuple[str, typing.Optional[typing.List[str]]]] = {
	# -- Western diatonic modes (7-note, with chord qualities) --
	"ionian":         ("major_ionian",     IONIAN_QUALITIES),
	"major":          ("major_ionian",     IONIAN_QUALITIES),
	"dorian":         ("dorian_mode",      DORIAN_QUALITIES),
	"phrygian":       ("phrygian_mode",    PHRYGIAN_QUALITIES),
	"lydian":         ("lydian",           LYDIAN_QUALITIES),
	"mixolydian":     ("mixolydian",       MIXOLYDIAN_QUALITIES),
	"aeolian":        ("natural_minor",    AEOLIAN_QUALITIES),
	"minor":          ("natural_minor",    AEOLIAN_QUALITIES),
	"locrian":        ("locrian_mode",     LOCRIAN_QUALITIES),
	"harmonic_minor": ("harmonic_minor",   HARMONIC_MINOR_QUALITIES),
	"melodic_minor":  ("melodic_minor",    MELODIC_MINOR_QUALITIES),
	# -- Non-western and pentatonic scales (no chord qualities) --
	"hirajoshi":      ("hirajoshi",        None),
	"in_sen":         ("in_sen",           None),
	"iwato":          ("iwato",            None),
	"yo":             ("yo",               None),
	"egyptian":       ("egyptian",         None),
	"major_pentatonic": ("major_pentatonic", None),
	"minor_pentatonic": ("minor_pentatonic", None),
}

# Backwards-compatible alias.
DIATONIC_MODE_MAP = SCALE_MODE_MAP


def scale_pitch_classes (key_pc: int, mode: str = "ionian") -> typing.List[int]:

	"""
	Return the pitch classes (0–11) that belong to a key and mode.

	Parameters:
		key_pc: Root pitch class (0 = C, 1 = C#/Db, …, 11 = B).
		mode: Scale mode name. Supports all keys of ``DIATONIC_MODE_MAP``
		      (e.g. ``"ionian"``, ``"dorian"``, ``"minor"``, ``"harmonic_minor"``).

	Returns:
		Sorted list of pitch classes in the scale (length varies by mode).

	Example:
		```python
		# C major pitch classes
		scale_pitch_classes(0, "ionian")  # → [0, 2, 4, 5, 7, 9, 11]

		# A minor pitch classes
		scale_pitch_classes(9, "aeolian")  # → [9, 11, 0, 2, 4, 5, 7] (mod-12)
		```
	"""

	if mode not in SCALE_MODE_MAP:
		raise ValueError(
			f"Unknown mode '{mode}'. Available: {sorted(SCALE_MODE_MAP)}. "
			"Use register_scale() to add custom scales."
		)

	scale_key, _ = SCALE_MODE_MAP[mode]
	intervals = get_intervals(scale_key)
	return [(key_pc + i) % 12 for i in intervals]


def quantize_pitch (pitch: int, scale_pcs: typing.Sequence[int]) -> int:

	"""
	Snap a MIDI pitch to the nearest note in the given scale.

	Searches outward in semitone steps from the input pitch.  When two
	notes are equidistant (e.g. C# between C and D in C major), the
	upward direction is preferred.

	Parameters:
		pitch: MIDI note number to quantize.
		scale_pcs: Pitch classes accepted by the scale (0–11). Typically
		           the output of :func:`scale_pitch_classes`.

	Returns:
		A MIDI note number that lies within the scale.

	Example:
		```python
		# Snap C# (61) to C (60) in C major
		scale = scale_pitch_classes(0, "ionian")  # [0, 2, 4, 5, 7, 9, 11]
		quantize_pitch(61, scale)  # → 60
		```
	"""

	pc = pitch % 12

	if pc in scale_pcs:
		return pitch

	for offset in range(1, 7):
		if (pc + offset) % 12 in scale_pcs:
			return pitch + offset
		if (pc - offset) % 12 in scale_pcs:
			return pitch - offset

	return pitch  # Fallback: should not be reached for any scale with gaps ≤ 6 semitones


def get_intervals (name: str) -> typing.List[int]:

	"""
	Return a named interval list from the registry.
	"""

	if name not in INTERVAL_DEFINITIONS:
		raise ValueError(f"Unknown interval set: {name}")

	return list(INTERVAL_DEFINITIONS[name])


def register_scale (
	name: str,
	intervals: typing.List[int],
	qualities: typing.Optional[typing.List[str]] = None
) -> None:

	"""
	Register a custom scale for use with ``p.quantize()`` and
	``scale_pitch_classes()``.

	Parameters:
		name: Scale name (used in ``p.quantize(key, name)``).
		intervals: Semitone offsets from the root (e.g. ``[0, 2, 3, 7, 8]``
			for Hirajōshi). Must start with 0 and contain values 0–11.
		qualities: Optional chord quality per scale degree (e.g.
			``["minor", "major", "minor", "major", "diminished"]``).
			Required only if you want to use the scale with
			``diatonic_chords()`` or ``diatonic_chord_sequence()``.

	Example::

		import subsequence

		subsequence.register_scale("raga_bhairav", [0, 1, 4, 5, 7, 8, 11])

		@comp.pattern(channel=0, length=4)
		def melody (p):
			p.note(60, beat=0)
			p.quantize("C", "raga_bhairav")
	"""

	if not intervals or intervals[0] != 0:
		raise ValueError("intervals must start with 0")
	if any(i < 0 or i > 11 for i in intervals):
		raise ValueError("intervals must contain values between 0 and 11")
	if qualities is not None and len(qualities) != len(intervals):
		raise ValueError(
			f"qualities length ({len(qualities)}) must match "
			f"intervals length ({len(intervals)})"
		)

	INTERVAL_DEFINITIONS[name] = intervals
	SCALE_MODE_MAP[name] = (name, qualities)


def get_diatonic_intervals (
	scale_notes: typing.List[int],
	intervals: typing.Optional[typing.List[int]] = None,
	mode: str = "scale"
) -> typing.List[typing.List[int]]:

	"""
	Construct diatonic chords from a scale.
	"""

	if intervals is None:
		intervals = [0, 2, 4]

	if mode not in ("scale", "chromatic"):
		raise ValueError("mode must be 'scale' or 'chromatic'")

	diatonic_intervals: typing.List[typing.List[int]] = []
	num_scale_notes = len(scale_notes)

	for i in range(num_scale_notes):

		if mode == "scale":
			chord = [scale_notes[(i + offset) % num_scale_notes] for offset in intervals]

		else:
			root = scale_notes[i]
			chord = [(root + offset) % 12 for offset in intervals]

		diatonic_intervals.append(chord)

	return diatonic_intervals
