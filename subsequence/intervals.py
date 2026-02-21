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


# Map mode names to (scale_interval_key, qualities) for use by helpers.
DIATONIC_MODE_MAP: typing.Dict[str, typing.Tuple[str, typing.List[str]]] = {
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
}


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

	if mode not in DIATONIC_MODE_MAP:
		raise ValueError(f"Unknown mode '{mode}'. Available: {sorted(DIATONIC_MODE_MAP)}")

	scale_key, _ = DIATONIC_MODE_MAP[mode]
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

	return pitch  # Fallback: return unchanged (should not be reached for any 7-note scale)


def get_intervals (name: str) -> typing.List[int]:

	"""
	Return a named interval list from the registry.
	"""

	if name not in INTERVAL_DEFINITIONS:
		raise ValueError(f"Unknown interval set: {name}")

	return list(INTERVAL_DEFINITIONS[name])


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
