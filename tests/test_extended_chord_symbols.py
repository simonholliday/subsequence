"""What a 9th, 11th or 13th chord symbol plays (#3006, decision 12 of #2991).

A bare major symbol carrying a 9, 11 or 13 is a dominant — ``C9`` is C E G Bb D,
the symbol a funk chart writes — while a spelled quality keeps its own colour.
An 11th carries the 9 under it, a 13th carries the 9 and leaves the natural 11
out over a major third, and a dominant 11th drops the third it would clash with.

The last test here reads back every label the printer emits, so the two halves
cannot drift apart again: until #3006 the library printed ``G9`` for a chord it
would have read as ``Gmaj9``.
"""

import pathlib
import typing

import mido
import pytest

import subsequence
import subsequence.progressions


def _span (symbol: str) -> subsequence.progressions.ChordSpan:

	"""The span a chord symbol parses to."""

	return subsequence.progressions.parse_element(symbol, beats = 4)


def _note_pcs_by_bar (filename: str, ticks_per_bar: int) -> typing.Dict[int, set]:

	"""Pitch classes of note_ons grouped by the bar they sound in."""

	mid = mido.MidiFile(filename)
	by_bar: typing.Dict[int, set] = {}

	for track in mid.tracks:
		now = 0
		for message in track:
			now += message.time
			if not isinstance(message, mido.MetaMessage) and message.type == "note_on" and message.velocity > 0:
				by_bar.setdefault(now // ticks_per_bar, set()).add(message.note % 12)

	return by_bar


# ---------------------------------------------------------------------------
# Which seventh a symbol carries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol, intervals", [
	("C9", [0, 4, 7, 10, 14]),
	("G9", [0, 4, 7, 10, 14]),
	("Bb9", [0, 4, 7, 10, 14]),
	("F13", [0, 4, 7, 10, 14, 21]),
	("G11", [0, 7, 10, 14, 17]),
])
def test_a_bare_major_symbol_with_an_extension_is_a_dominant (symbol: str, intervals: typing.List[int]) -> None:

	"""C9, F13 and G11 are jazz and funk symbols, so each carries a flat seventh."""

	assert _span(symbol).decorated_intervals() == intervals


@pytest.mark.parametrize("symbol, intervals", [
	("Cmaj9", [0, 4, 7, 11, 14]),
	("CM9", [0, 4, 7, 11, 14]),
	("Cmaj13", [0, 4, 7, 11, 14, 21]),
	("Cm9", [0, 3, 7, 10, 14]),
	("Cdim9", [0, 3, 6, 9, 14]),
	("C+maj9", [0, 4, 8, 11, 14]),
])
def test_a_spelled_quality_keeps_its_own_colour (symbol: str, intervals: typing.List[int]) -> None:

	"""Only the bare major changes: a named seventh still says which one it is.

	``C+maj9`` is the augmented chord's major ninth.  ``C+9`` itself has a
	minor seventh since #3499, as a chart means it; test_chord_names_read_back.py
	holds that.
	"""

	assert _span(symbol).decorated_intervals() == intervals


def test_the_two_ninths_are_different_chords () -> None:

	"""C9 and Cmaj9 were the same five notes, which is what hid the fault."""

	assert _span("C9").decorated_intervals() != _span("Cmaj9").decorated_intervals()


# ---------------------------------------------------------------------------
# What an 11th and a 13th contain
# ---------------------------------------------------------------------------

def test_an_eleventh_carries_the_ninth_under_it () -> None:

	"""Dm11 is D F A C E G — the 9 belongs to the chord, not to a separate extension."""

	assert _span("Dm11").decorated_intervals() == [0, 3, 7, 10, 14, 17]


def test_a_dominant_eleventh_drops_the_third () -> None:

	"""G11 is G D F A C: a natural 11 a semitone above the major third is not played."""

	assert _span("G11").decorated_intervals() == [0, 7, 10, 14, 17]
	assert _span("Gm11").decorated_intervals() == [0, 3, 7, 10, 14, 17]		# a minor third keeps both


def test_a_thirteenth_leaves_the_eleventh_out_over_a_major_third () -> None:

	"""G13 is G B D F A E, while Gm13 keeps its 11, because a minor third does not clash."""

	assert _span("G13").decorated_intervals() == [0, 4, 7, 10, 14, 21]
	assert _span("Gm13").decorated_intervals() == [0, 3, 7, 10, 14, 17, 21]


# ---------------------------------------------------------------------------
# Every label the printer emits, read back
# ---------------------------------------------------------------------------

_BASES = ("C", "Cm", "Cdim", "C+", "C7", "Cmaj7", "Cm7", "Cm7b5", "Cdim7", "Csus2", "Csus4")


@pytest.mark.parametrize("base", _BASES)
@pytest.mark.parametrize("extension", (7, 9, 11, 13))
def test_every_label_the_printer_emits_reads_back_as_the_same_chord (base: str, extension: int) -> None:

	"""What the library writes, the library reads: the same notes, both ways round.

	Fifteen of these could not be read until #3014 - C7sus4, Cm9b5, C+maj9 -
	because the quality's tail came after the number.  The wider sweep, with
	named extensions and slash basses, is tests/test_chord_names_read_back.py.
	"""

	span = subsequence.progression([base]).extend(extension).spans[0]
	label = span.label()

	read_back = subsequence.progressions.parse_element(label, beats = 4)

	assert read_back.decorated_intervals() == span.decorated_intervals(), (
		f"{base} extended by {extension} prints {label!r}, which reads back as a different chord"
	)


# ---------------------------------------------------------------------------
# End-to-end: what a chart of these symbols sounds
# ---------------------------------------------------------------------------

def test_a_render_of_a_funk_chart_sounds_its_flat_sevenths (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""C9 F13 G11, played: Bb under the C, Eb under the F, F under the G."""

	filename = str(tmp_path / "chart.mid")
	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 480)
	composition.harmony(progression = ["C9", "F13", "G11"])

	@composition.pattern(channel = 1, beats = 4)
	def pad (p, chord) -> None:
		for pitch in chord.tones(60):
			p.note(pitch, beat = 0, duration = 4)

	composition.render(bars = 3, filename = filename)

	ticks_per_bar = mido.MidiFile(filename).ticks_per_beat * 4
	by_bar = _note_pcs_by_bar(filename, ticks_per_bar)

	assert by_bar[0] == {0, 4, 7, 10, 2}		# C9  — C E G Bb D
	assert by_bar[1] == {5, 9, 0, 3, 7, 2}		# F13 — F A C Eb G D
	assert by_bar[2] == {7, 2, 5, 9, 0}		# G11 — G D F A C
