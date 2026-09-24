"""Every chord label the library prints reads back as the same chord (#3014).

``ChordSpan.label()`` writes decorated names - a quality tail after the number (``C7sus4``,
``Cm9b5``, ``C+maj7``), named extensions on the end (``Cadd9``, ``Cm6``), a bass after a slash
(``C/E``) - and ``progression([...])`` refused all of them: of 2475 labels over every built-in
quality, extension and bass, 126 read back.  A progression shown on a display, logged, or sent to a
control surface could not be pasted back in.

Measuring the round trip also found labels the printer got wrong, which now read back as the chords
they are: a major-seventh sus4 printed as ``C7sus4``, a 6th was taken for a diminished seventh
(``C76`` for Cmaj7 with a 6th), and a 7 glued onto a name ending in one read as another number.

An augmented chord's number is a minor seventh, as on a chart (#3499, Simon's call on the ``C+9``
question): ``C+7`` is C E G# Bb and ``C+9`` adds the D, where ``C+9`` used to read with a major
seventh and ``C+7`` was refused.  That let the last 18 labels read back: ``C+7sus4`` and its kin.
"""

import itertools
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.progressions


# The built-in qualities, named here: other tests register their own into the shared table.
_QUALITIES = (
	"major", "minor", "diminished", "augmented", "dominant_7th", "major_7th",
	"minor_7th", "half_diminished_7th", "diminished_7th", "sus2", "sus4",
)


def _read (name: str) -> subsequence.progressions.ChordSpan:

	return subsequence.progressions.parse_element(name, beats = 4)


def _span (quality: str, extensions: typing.Tuple[typing.Any, ...] = (), bass: typing.Optional[int] = None, root: int = 0) -> subsequence.progressions.ChordSpan:

	chord = subsequence.chords.Chord(root_pc = root, quality = quality)

	return subsequence.progressions.ChordSpan(chord = chord, beats = 4, extensions = extensions, bass = bass)


def _sound (span: subsequence.progressions.ChordSpan) -> typing.Tuple[typing.Any, ...]:

	"""What a span plays: its notes above the root, the root, and the bass."""

	return (span.decorated_intervals(), span.chord.root_pc, span.bass)


def test_every_label_over_every_quality_extension_and_bass_reads_back () -> None:

	"""The whole domain the printer covers, on three roots: the same notes, root and bass, and the same label.

	The augmented chord with a number and a sus, ``C+7sus4``, was the last
	family refused, until an augmented chord's number was read as a chart
	reads it (#3499).
	"""

	misread: typing.List[str] = []
	refused: typing.Set[str] = set()
	read = 0

	for root, quality, number, name, bass in itertools.product(
		(0, 6, 10),
		_QUALITIES,
		(None, 7, 9, 11, 13),
		(None, "add9", "6", "sus2", "sus4"),
		(None, 4, 2),
	):

		span = _span(quality, tuple(e for e in (number, name) if e is not None), bass, root)
		label = span.label()

		try:
			back = _read(label)
		except ValueError:
			refused.add(label)
			continue

		read += 1

		if _sound(back) != _sound(span):
			misread.append(f"{label}: {_sound(span)} read as {_sound(back)}")
		elif back.label() != label:
			misread.append(f"{label}: prints back as {back.label()!r}")

	assert misread == []
	assert sorted(refused) == []
	assert read == 2475


@pytest.mark.parametrize("name, intervals", [
	("C7sus4", [0, 5, 7, 10]),
	("C9sus4", [0, 5, 7, 10, 14]),
	("Cm9b5", [0, 3, 6, 10, 14]),
	("C+maj7", [0, 4, 8, 11]),
	("CmMaj7", [0, 3, 7, 11]),
	("CmMaj9", [0, 3, 7, 11, 14]),
	("Cadd9", [0, 4, 7, 14]),
	("Cm6", [0, 3, 7, 9]),
	("C6add9", [0, 4, 7, 9, 14]),
	("Cmaj7sus4", [0, 5, 7, 11]),
	("Cmaj9sus2", [0, 2, 7, 11, 14]),
	("Cdim9sus2", [0, 2, 6, 9, 14]),
])
def test_a_chart_symbol_reads_as_the_chord_it_names (name: str, intervals: typing.List[int]) -> None:

	assert _read(name).decorated_intervals() == intervals


def test_a_slash_chord_puts_its_bass_under_the_chord () -> None:

	"""C/E is C major over an E, and Am7/G an A minor seventh over a G."""

	c_over_e = _read("C/E")
	a_over_g = _read("Am7/G")

	assert (c_over_e.chord.quality, c_over_e.bass) == ("major", 4)
	assert (a_over_g.chord.root_pc, a_over_g.chord.quality, a_over_g.bass) == (9, "minor_7th", 7)
	assert min(c_over_e.tones(60)) % 12 == 4


def test_a_slash_with_no_note_after_it_says_what_it_needs () -> None:

	with pytest.raises(ValueError, match = "after the slash comes a note"):
		_read("C/H")


def test_a_bare_chord_refuses_a_slash_and_says_where_one_is_read () -> None:

	"""parse_chord() makes a Chord, which has no bass: it points at the progression that does."""

	with pytest.raises(ValueError, match = r"progression\(\['C/E'\]\) reads it"):
		subsequence.chords.parse_chord("C/E")


@pytest.mark.parametrize("quality, extensions, was, now", [
	("major_7th", (7, "sus4"), "C7sus4", "Cmaj7sus4"),
	("major", (7, "6"), "C76", "Cmaj76"),
	("diminished", (7, "sus2"), "Cdim7sus2", "Cm7b5sus2"),
	("diminished_7th", (7, "sus2"), "Cdim77sus2", "Cdim7sus2"),
	("half_diminished_7th", (7, "sus4"), "Cm7b57sus4", "Cm7b5sus4"),
])
def test_the_printer_names_the_chord_it_has (quality: str, extensions: typing.Tuple[typing.Any, ...], was: str, now: str) -> None:

	"""Five labels that named a different chord, or could not be read at all."""

	assert _span(quality, extensions).label() == now


@pytest.mark.parametrize("name, intervals", [
	("C+7", [0, 4, 8, 10]),
	("Caug7", [0, 4, 8, 10]),
	("C7#5", [0, 4, 8, 10]),
	("C7+5", [0, 4, 8, 10]),
	("C+9", [0, 4, 8, 10, 14]),
	("C9#5", [0, 4, 8, 10, 14]),
	("C+13", [0, 4, 8, 10, 14, 21]),
	("C+11", [0, 8, 10, 14, 17]),
	("C+maj7", [0, 4, 8, 11]),
	("C+maj9", [0, 4, 8, 11, 14]),
	("Cmaj7#5", [0, 4, 8, 11]),
	("C+7sus4", [0, 5, 8, 10]),
])
def test_an_augmented_chord_reads_as_a_chart_writes_it (name: str, intervals: typing.List[int]) -> None:

	"""#3499: a number after '+' is a minor seventh; the major seventh is named.

	C+13 leaves out the natural 11 over the major third, and C+11 drops the third, by the same
	two jazz rules every dominant follows (decision 12 of #2991).
	"""

	assert _read(name).decorated_intervals() == intervals


@pytest.mark.parametrize("name, printed", [
	("C7#5", "C+7"),
	("Caug7", "C+7"),
	("C9#5", "C+9"),
	("Cmaj7#5", "C+maj7"),
	("C+9", "C+9"),
])
def test_a_chart_spelling_prints_as_the_library_spells_it (name: str, printed: str) -> None:

	"""What a chart spelling prints as, which reads back as the same chord."""

	span = _read(name)

	assert span.label() == printed
	assert _sound(_read(printed)) == _sound(span)


# ── A roman chord's label names the tensions it plays (#3490) ──

_ROMAN_SCALES = [name for name, (_, qualities) in subsequence.intervals.SCALE_MODE_MAP.items() if qualities is not None]


def _roman (degree: int, number: int, scale: str, key: str = "A") -> subsequence.progressions.ChordSpan:

	return subsequence.progressions.progression([degree]).extend(number).resolve(key, scale).spans[0]


def test_every_roman_chord_reads_back_as_the_chord_it_plays () -> None:

	"""Every degree of every scale with chords, extended to 7, 9, 11 and 13, in two keys.

	An extended roman takes the scale's own tensions (#3026), and the label printed only the
	number, so 108 of the 308 in A read back as a different chord: V9 in A harmonic minor
	plays E7b9 and printed ``E9``, which plays a natural ninth.
	"""

	misread: typing.List[str] = []
	refused: typing.List[str] = []
	checked = 0

	for scale, degree, number, key in itertools.product(_ROMAN_SCALES, range(1, 8), (7, 9, 11, 13), ("A", "Eb")):

		span = _roman(degree, number, scale, key)
		label = span.label()
		checked += 1

		try:
			back = _read(label)
		except ValueError:
			refused.append(label)
			continue

		if _sound(back) != _sound(span):
			misread.append(f"{scale} {degree} {number} in {key}: {label} plays {span.decorated_intervals()}, reads {back.decorated_intervals()}")

	assert misread == []
	assert refused == []
	assert checked >= 600


@pytest.mark.parametrize("scale, degree, number, label, intervals", [
	("harmonic_minor", 5, 9, "E7b9", [0, 4, 7, 10, 13]),
	("harmonic_minor", 6, 9, "Fmaj7#9", [0, 4, 7, 11, 15]),
	("harmonic_minor", 2, 9, "Bm7b5b9", [0, 3, 6, 10, 13]),
	("harmonic_minor", 7, 9, "G#dim7b9", [0, 3, 6, 9, 13]),
	("aeolian", 5, 9, "Em7b9", [0, 3, 7, 10, 13]),
	("ionian", 4, 11, "Dmaj9#11", [0, 4, 7, 11, 14, 18]),
	("ionian", 4, 13, "Dmaj13#11", [0, 4, 7, 11, 14, 18, 21]),
	("aeolian", 1, 13, "Am11b13", [0, 3, 7, 10, 14, 17, 20]),
	("harmonic_minor", 5, 13, "E7b9b13", [0, 4, 7, 10, 13, 20]),
	("harmonic_minor", 5, 11, "E11b9", [0, 7, 10, 13, 17]),
	("melodic_minor", 5, 13, "E9b13", [0, 4, 7, 10, 14, 20]),
	("melodic_minor", 7, 13, "G#m7b5b9b11b13", [0, 3, 6, 10, 13, 16, 20]),
	("mixolydian", 1, 13, "A13", [0, 4, 7, 10, 14, 21]),
])
def test_a_roman_label_names_its_altered_tensions (scale: str, degree: int, number: int, label: str, intervals: typing.List[int]) -> None:

	"""The number is the highest plain tension, and each altered one follows it, as a chart writes it."""

	span = _roman(degree, number, scale)

	assert (span.label(), span.decorated_intervals()) == (label, intervals)


def test_a_sharp_eleventh_keeps_the_third () -> None:

	"""The lydian dominant, IV11 in melodic minor: D F# A C E G#.

	A dominant 11th drops its third because the natural 11 sits a semitone above it.  The rule
	dropped it under a sharp 11 as well, which sits a tone above, so the chord lost its F#.
	"""

	assert _roman(4, 11, "melodic_minor").decorated_intervals() == [0, 4, 7, 10, 14, 18]


@pytest.mark.parametrize("name, intervals", [
	("C7b9", [0, 4, 7, 10, 13]),
	("C7#9", [0, 4, 7, 10, 15]),
	("C7b9#9", [0, 4, 7, 10, 13, 15]),
	("C9#11", [0, 4, 7, 10, 14, 18]),
	("C13b9", [0, 4, 7, 10, 13, 21]),
	("C7b9b13", [0, 4, 7, 10, 13, 20]),
	("Cmaj9#11", [0, 4, 7, 11, 14, 18]),
	("Cm7b5b9", [0, 3, 6, 10, 13]),
	("Cm11b13", [0, 3, 7, 10, 14, 17, 20]),
])
def test_a_chart_symbol_with_altered_tensions_reads (name: str, intervals: typing.List[int]) -> None:

	span = _read(name)

	assert span.decorated_intervals() == intervals
	assert span.label() == name


@pytest.mark.parametrize("name, root, intervals", [
	("C#9", 1, [0, 4, 7, 10, 14]),
	("Db9", 1, [0, 4, 7, 10, 14]),
	("Eb13", 3, [0, 4, 7, 10, 14, 21]),
	("F#11", 6, [0, 7, 10, 14, 17]),
	("Bb9", 10, [0, 4, 7, 10, 14]),
])
def test_a_sharp_or_flat_root_is_never_read_as_a_tension (name: str, root: int, intervals: typing.List[int]) -> None:

	"""A guard: ``C#9`` is the ninth chord on C#, never C with a sharp ninth.  This passed before as well."""

	span = _read(name)

	assert (span.chord.root_pc, span.decorated_intervals()) == (root, intervals)


@pytest.mark.parametrize("name", ["Cmb9", "C6b9", "Cm#11"])
def test_a_tension_after_a_chord_with_no_seventh_is_refused (name: str) -> None:

	"""Read as a triad with a tension, each would print back as a seventh chord, a different one."""

	with pytest.raises(ValueError):
		_read(name)
