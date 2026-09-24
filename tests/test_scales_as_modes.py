"""Every scale the interval table names works as a scale (#3044).

``INTERVAL_DEFINITIONS`` names 51 interval sets and ``SCALE_MODE_MAP`` held the 18 that worked as
modes, while ``_BUILTIN_SCALE_NAMES`` reserved both.  So a name in the first alone was in a loop:
``scale_notes("C", "whole_tone")`` said to use ``register_scale()``, and
``register_scale("whole_tone", ...)`` refused a built-in name.

Simon's call (2026-09-24): they work as scales.  Seventeen were scales: the sixteen the review
counted, and ``augmented``, the six-note augmented scale, which it took for the chord (that one
is ``augmented_triad``).  The five spellings of existing modes carry their chords; the others,
like the pentatonics, are notes only.
"""

import pytest

import subsequence
import subsequence.harmony
import subsequence.intervals
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.progressions


# The rest of the interval table: chords and intervals, which are not scales.  A new entry in the
# table has to be one or the other, and this list is where the other is said.
NOT_SCALES = {
	"augmented_7th", "augmented_triad", "diminished_7th", "diminished_triad", "dominant_7th",
	"dominant_9th", "fifth", "half_diminished_7th", "major_6th", "major_7th", "major_9th",
	"major_triad", "minor_3rd", "minor_6th", "minor_7th", "minor_9th", "minor_major_7th",
	"minor_triad", "power_chord", "root", "sus2", "sus4", "tritone",
}

SPELLINGS = {
	"major_ionian": "ionian", "dorian_mode": "dorian", "phrygian_mode": "phrygian",
	"natural_minor": "aeolian", "locrian_mode": "locrian",
}

NOTES_ONLY = [
	"augmented", "blues_scale", "chromatic", "double_harmonic", "enigmatic", "hungarian_minor",
	"lydian_dominant", "minor_blues", "neapolitan_major", "phrygian_dominant", "superlocrian",
	"whole_tone",
]


def test_every_name_in_the_interval_table_is_a_scale_or_said_to_be_something_else () -> None:

	"""The two tables kept apart is what made the loop, so they are held together here."""

	assert set(subsequence.intervals.INTERVAL_DEFINITIONS) - set(subsequence.intervals.SCALE_MODE_MAP) == NOT_SCALES


@pytest.mark.parametrize("name", sorted(SPELLINGS) + NOTES_ONLY)
def test_a_scale_from_the_interval_table_plays_its_own_notes (name: str) -> None:

	intervals = subsequence.intervals.INTERVAL_DEFINITIONS[name]

	assert subsequence.intervals.scale_pitch_classes(2, name) == [(2 + i) % 12 for i in intervals]
	assert subsequence.scale_notes("C", name, low=60, high=71) == [60 + i for i in intervals]


def test_a_note_snaps_to_one () -> None:

	pattern = subsequence.pattern.Pattern(channel=0, length=4)
	builder = subsequence.pattern_builder.PatternBuilder(pattern=pattern, cycle=0, default_grid=16)
	builder.note(61, beat=0)
	builder.snap_to_scale("C", "whole_tone")

	assert [note.pitch for step in pattern.steps.values() for note in step.notes] in ([60], [62])


@pytest.mark.parametrize("name", sorted(SPELLINGS))
def test_another_spelling_of_a_mode_builds_its_chords (name: str) -> None:

	assert subsequence.harmony.diatonic_chords("D", name) == subsequence.harmony.diatonic_chords("D", SPELLINGS[name])


def test_chords_on_a_scale_without_them_say_how_to_get_them () -> None:

	"""The advice used to be register_scale(..., qualities=[...]), which refuses every built-in name."""

	with pytest.raises(ValueError, match="under a name of your own"):
		subsequence.harmony.diatonic_chords("C", "whole_tone")

	with pytest.raises(ValueError, match="under a name of your own"):
		subsequence.progressions.progression([2]).resolve("C", "hungarian_minor")


def test_a_chord_in_the_table_says_it_is_not_a_scale () -> None:

	"""Asked for as a scale, a chord name no longer points at a register_scale() that refuses it."""

	with pytest.raises(ValueError, match="dominant_9th' is a chord or an interval, not a scale"):
		subsequence.scale_notes("C", "dominant_9th")


@pytest.mark.parametrize("name", ["whole_tone", "natural_minor", "augmented"])
def test_a_built_in_scale_stays_reserved (name: str) -> None:

	"""A guard: a built-in name still cannot be registered over.  This held before as well."""

	with pytest.raises(ValueError, match="Cannot overwrite built-in scale"):
		subsequence.register_scale(name, [0, 2, 4])


def test_an_unknown_name_lists_the_seventeen_as_available () -> None:

	with pytest.raises(ValueError) as refused:
		subsequence.scale_notes("C", "no_such_scale")

	assert [name for name in NOTES_ONLY + sorted(SPELLINGS) if f"'{name}'" not in str(refused.value)] == []
