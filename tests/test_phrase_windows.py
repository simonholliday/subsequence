"""A phrase sounds the same whatever length of pattern walks it (#3010).

Each cycle takes a window with `slice()`, and `slice()` used to cut at the edge.
So an 8-beat `cc_ramp(74, 0, 127)` walked by a 4-beat pattern sent the first
half and then one event, and the filter parked at 64 for the rest of the piece;
a 2-beat note at beat 3 lasted one beat under a 4-beat pattern and two under an
8-beat one; and a shaped ramp kept its shape name over the shorter span, which
bent its curve. `phrase_part` defaults to 4-beat windows, so its standard setup
met all of it.

The window now keeps a note's whole duration — the sequencer already lets a
note ring into the next cycle — and resumes a ramp that began earlier, carrying
which part of the real curve it holds.
"""

import dataclasses
import typing

import pytest

import subsequence
import subsequence.motifs as motifs
import subsequence.pattern
import subsequence.pattern_builder


PPQ = 24


def _walked (whole: motifs.Motif, window: float) -> typing.List[typing.Tuple[int, int]]:

	"""Walk *whole* with a *window*-beat pattern; every CC it sends, in song time."""

	sent: typing.List[typing.Tuple[int, int]] = []

	for cycle in range(int(round(whole.length / window))):

		piece = whole.slice(cycle * window, (cycle + 1) * window)

		pattern = subsequence.pattern.Pattern(channel = 1, length = window)
		builder = subsequence.pattern_builder.PatternBuilder(pattern = pattern, cycle = cycle)
		builder.motif(piece, root = 60)
		builder._finish_build()

		for event in pattern.cc_events:
			sent.append((int(round(cycle * window * PPQ)) + event.pulse, event.value))

	return sorted(set(sent))


def _notes_walked (whole: motifs.Motif, window: float) -> typing.List[typing.Tuple[float, int, float]]:

	"""Every note the walk places, in song time, with the duration it was given."""

	placed = []

	for cycle in range(int(round(whole.length / window))):
		piece = whole.slice(cycle * window, (cycle + 1) * window)
		for event in piece.events:
			placed.append((cycle * window + event.beat, event.pitch, event.duration))

	return sorted(placed)


def _sweep (shape: str = "linear", length: float = 8.0) -> motifs.Motif:

	"""One long ramp and one note that rings past a window edge."""

	return motifs.Motif(
		events = (motifs.MotifEvent(beat = 3.0, pitch = 60, velocity = 100, duration = 2.0),),
		length = length,
		controls = (
			motifs.ControlEvent(
				beat = 0.0, signal = motifs.CC(74),
				start = 0.0, end = 127.0, span = length, shape = shape,
			),
		),
	)


# ---------------------------------------------------------------------------
# The same phrase, whatever walks it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("window", [1.0, 2.0, 4.0, 8.0])
@pytest.mark.parametrize("shape", ["linear", "ease_in_out", "ease_out"])
def test_a_ramp_sounds_the_same_at_every_pattern_length (window: float, shape: str) -> None:

	"""The finding in one line: an 8-beat sweep walked 4 beats at a time parked at 64."""

	whole = _sweep(shape)

	assert _walked(whole, window) == _walked(whole, 8.0), \
		f"a {window:g}-beat pattern plays the sweep differently from an 8-beat one"


@pytest.mark.parametrize("window", [1.0, 2.0, 4.0, 8.0])
def test_a_ramp_reaches_both_of_its_ends_at_every_pattern_length (window: float) -> None:

	"""Parking at 64 is what this looked like from the room."""

	values = [value for _, value in _walked(_sweep(), window)]

	assert min(values) == 0
	assert max(values) == 127


@pytest.mark.parametrize("window", [1.0, 2.0, 4.0, 8.0])
def test_a_ramp_is_sent_all_the_way_through (window: float) -> None:

	"""It used to send 96 events in cycle 0 and one in cycle 1."""

	sent = _walked(_sweep(), window)

	assert sent[0][0] == 0
	assert sent[-1][0] == int(8.0 * PPQ), f"the sweep stopped at pulse {sent[-1][0]}"


@pytest.mark.parametrize("window", [1.0, 2.0, 4.0, 8.0])
def test_a_note_lasts_as_long_as_it_was_written_at_every_pattern_length (window: float) -> None:

	"""A 2-beat note at beat 3 lasted 1 beat under a 4-beat pattern."""

	assert _notes_walked(_sweep(), window) == [(3.0, 60, 2.0)]


# ---------------------------------------------------------------------------
# What a window holds
# ---------------------------------------------------------------------------

def test_a_window_keeps_a_notes_whole_duration () -> None:

	"""The sequencer lets a note ring into the next cycle; there is nothing to cut it for."""

	whole = motifs.Motif(
		events = (motifs.MotifEvent(beat = 3.0, pitch = 60, velocity = 100, duration = 5.0),),
		length = 8.0,
	)

	assert whole.slice(0.0, 4.0).events[0].duration == 5.0


def test_a_window_resumes_a_ramp_that_began_before_it () -> None:

	"""It used to drop it entirely, which is why the value froze."""

	caught = _sweep().slice(4.0, 8.0).controls

	assert caught, "the window dropped the ramp instead of resuming it"

	piece = caught[0]

	assert piece.beat == 0.0
	assert piece.span == 4.0
	assert (piece.shape_from, piece.shape_to) == (0.5, 1.0)
	assert piece._value_at(0.0) == pytest.approx(63.5)
	assert piece._value_at(1.0) == pytest.approx(127.0)


def test_a_window_holding_the_middle_of_a_ramp_holds_only_the_middle () -> None:

	"""A window narrower than the gesture, at neither of its ends."""

	caught = _sweep().slice(2.0, 6.0).controls

	assert caught, "the window dropped the ramp instead of resuming it"

	piece = caught[0]

	assert (piece.shape_from, piece.shape_to) == (0.25, 0.75)
	assert piece._value_at(0.0) == pytest.approx(31.75)
	assert piece._value_at(1.0) == pytest.approx(95.25)


def test_a_shaped_ramp_keeps_its_curve_rather_than_its_name () -> None:

	"""Keeping the shape NAME over a shorter span re-ran the whole curve in the window.

	The second half of an ease_in_out sweep is the decelerating half, and must
	stay that way — not become a fresh ease_in_out from 63.5 to 127.
	"""

	whole = _sweep("ease_in_out")
	second = whole.slice(4.0, 8.0).controls[0]

	# A quarter of the way into the second half is five-eighths of the whole.
	assert second._value_at(0.25) == pytest.approx(whole.controls[0]._value_at(0.625))
	assert second._value_at(0.5) == pytest.approx(whole.controls[0]._value_at(0.75))


def test_a_discrete_write_outside_the_window_is_still_dropped () -> None:

	"""A write happens at a moment; it is in or it is out."""

	whole = motifs.Motif(
		events = (),
		length = 8.0,
		controls = (
			motifs.ControlEvent(beat = 1.0, signal = motifs.CC(74), start = 10.0),
			motifs.ControlEvent(beat = 5.0, signal = motifs.CC(74), start = 20.0),
		),
	)

	assert [c.start for c in whole.slice(0.0, 4.0).controls] == [10.0]
	assert [c.start for c in whole.slice(4.0, 8.0).controls] == [20.0]


def test_a_ramp_entirely_outside_the_window_is_dropped () -> None:

	"""Resuming must not mean keeping everything."""

	whole = motifs.Motif(
		events = (),
		length = 8.0,
		controls = (
			motifs.ControlEvent(beat = 0.0, signal = motifs.CC(74), start = 0.0, end = 100.0, span = 2.0),
		),
	)

	assert whole.slice(4.0, 8.0).controls == ()


def test_slicing_a_piece_again_narrows_it () -> None:

	"""A phrase window is sliced twice: once by the Phrase, once by the Motif."""

	piece = _sweep().slice(0.0, 4.0).slice(2.0, 4.0).controls[0]

	assert (piece.shape_from, piece.shape_to) == (0.25, 0.5)
	assert piece._value_at(1.0) == pytest.approx(63.5)


# ---------------------------------------------------------------------------
# Phrases and their segment boundaries
# ---------------------------------------------------------------------------

def _two_segments () -> motifs.Phrase:

	"""Two 4-beat segments, with a note in the first that rings into the second."""

	return motifs.Phrase((
		motifs.Motif(
			events = (motifs.MotifEvent(beat = 3.0, pitch = 60, velocity = 100, duration = 2.0),),
			length = 4.0,
		),
		motifs.Motif(events = (), length = 4.0),
	))


def test_a_note_rings_past_an_internal_segment_boundary () -> None:

	"""`rotate` promises a note may ring past its segment; slicing cut it."""

	phrase = _two_segments()
	sliced = phrase.slice(0.0, phrase.length)

	assert [e.duration for segment in sliced.segments for e in segment.events] == [2.0]


def test_slicing_a_whole_phrase_is_the_identity () -> None:

	"""If it is not, then walking a phrase changes it, which is the whole bug."""

	phrase = _two_segments()

	assert phrase.slice(0.0, phrase.length) == phrase


def test_slicing_a_whole_phrase_with_a_ramp_across_the_boundary_is_the_identity () -> None:

	"""The ramp case of the same law."""

	phrase = motifs.Phrase((
		motifs.Motif(
			events = (),
			length = 4.0,
			controls = (motifs.ControlEvent(beat = 2.0, signal = motifs.CC(74), start = 0.0, end = 127.0, span = 4.0),),
		),
		motifs.Motif(events = (), length = 4.0),
	))

	assert phrase.slice(0.0, phrase.length) == phrase


def test_a_rotated_phrase_still_rings_past_its_segments () -> None:

	"""What rotate() promises, through the walk that used to undo it."""

	rotated = _two_segments().rotate(1.0)
	sliced = rotated.slice(0.0, rotated.length)

	assert [e.duration for segment in sliced.segments for e in segment.events] == \
		[e.duration for segment in rotated.segments for e in segment.events]


# ---------------------------------------------------------------------------
# A motif carrying a piece of a gesture is still a value
# ---------------------------------------------------------------------------

def test_a_sliced_motif_is_still_hashable () -> None:

	"""Motifs are frozen values, and a partial ramp must not cost that."""

	assert len({_sweep().slice(0.0, 4.0), _sweep().slice(4.0, 8.0)}) == 2


def test_two_identical_windows_compare_equal () -> None:

	"""Comparison has to see the fractions, or two different pieces look the same."""

	assert _sweep().slice(0.0, 4.0) == _sweep().slice(0.0, 4.0)
	assert _sweep().slice(0.0, 4.0) != _sweep().slice(4.0, 8.0)


def test_a_partial_ramp_says_that_it_is_one () -> None:

	"""The flag the emission path reads to decide whether to rebuild the curve."""

	assert not _sweep().controls[0].is_partial
	assert _sweep().slice(0.0, 4.0).controls[0].is_partial


@pytest.mark.parametrize("shape_from, shape_to", [(-0.1, 0.5), (0.5, 0.2), (0.0, 1.5)])
def test_a_nonsense_fraction_is_refused (shape_from: float, shape_to: float) -> None:

	"""A piece of a curve runs forwards, inside the curve."""

	with pytest.raises(ValueError, match = "partial ramp"):
		motifs.ControlEvent(
			beat = 0.0, signal = motifs.CC(74), start = 0.0, end = 127.0, span = 4.0,
			shape_from = shape_from, shape_to = shape_to,
		)


def test_a_whole_ramp_keeps_its_shape_by_name () -> None:

	"""A named curve should reach the builder verb still named."""

	assert _sweep("ease_in_out").controls[0]._emission_shape() == "ease_in_out"


def test_two_pieces_of_one_gesture_at_one_beat_sort_the_same_either_way () -> None:

	"""The ordering key exists so a parallel merge does not depend on merge order.

	Two pieces of one curve sitting at one beat differ only in their fractions,
	so leaving those out of the key makes them tie — and a stable sort then
	keeps whichever order it was handed.
	"""

	first = motifs.ControlEvent(
		beat = 0.0, signal = motifs.CC(74), start = 0.0, end = 127.0, span = 2.0,
		shape_from = 0.0, shape_to = 0.25,
	)
	second = dataclasses.replace(first, shape_from = 0.25, shape_to = 0.5)

	one_way = motifs.Motif(events = (), length = 4.0, controls = (first, second))
	other_way = motifs.Motif(events = (), length = 4.0, controls = (second, first))

	assert one_way == other_way


# ---------------------------------------------------------------------------
# The write on a phrase's end, where the phrase loops (#3557)
# ---------------------------------------------------------------------------

# 64 on beat 1, and 127 on its end, where it closes the gesture (#3009).
_CLOSING = motifs.Motif.cc(74, [64, 127], beats = [1, 2])


def _phrase_sends (value: typing.Any, pattern_length: float, song_beats: float = 8.0) -> typing.List[typing.Tuple[float, int]]:

	"""Every CC ``p.phrase(value)`` sends over *song_beats*, cycle by cycle, in song beats."""

	sent: typing.List[typing.Tuple[float, int]] = []

	for cycle in range(int(round(song_beats / pattern_length))):

		pattern = subsequence.pattern.Pattern(channel = 1, length = pattern_length)
		builder = subsequence.pattern_builder.PatternBuilder(pattern = pattern, cycle = cycle)
		builder.phrase(value)
		builder._finish_build()

		sent.extend((cycle * pattern_length + event.pulse / PPQ, event.value) for event in pattern.cc_events)

	return sorted(sent)


def _motif_sends (value: motifs.Motif, song_beats: float = 8.0) -> typing.List[typing.Tuple[float, int]]:

	"""The same, placed with ``p.motif()`` by a pattern as long as the motif."""

	sent: typing.List[typing.Tuple[float, int]] = []

	for cycle in range(int(round(song_beats / value.length))):

		pattern = subsequence.pattern.Pattern(channel = 1, length = value.length)
		builder = subsequence.pattern_builder.PatternBuilder(pattern = pattern, cycle = cycle)
		builder.motif(value)
		builder._finish_build()

		sent.extend((cycle * value.length + event.pulse / PPQ, event.value) for event in pattern.cc_events)

	return sorted(sent)


@pytest.mark.parametrize("pattern_length", [1.0, 2.0, 4.0])
def test_a_looped_phrase_sends_the_write_on_its_end (pattern_length: float) -> None:

	"""A phrase's closing write fell in no window, so a looped phrase sent 64 and never 127.

	It now plays as ``p.motif()`` plays it, whatever length of pattern walks the phrase.
	"""

	expected = [(beat, 64 if beat % 2 else 127) for beat in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)]

	assert _motif_sends(_CLOSING) == expected
	assert _phrase_sends(_CLOSING, pattern_length) == expected


def test_a_phrase_of_segments_sends_the_write_on_its_last_end () -> None:

	"""The write between two segments was always inside a window; the one on the whole phrase's end was not."""

	phrase = _CLOSING + _CLOSING

	assert _phrase_sends(phrase, 4.0) == [(beat, 64 if beat % 2 else 127) for beat in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)]


def test_a_phrase_with_no_write_on_its_end_is_unchanged () -> None:

	"""A guard: nothing is added where a phrase does not close a gesture on its end."""

	# Given its length: without one, the last write would sit on the end and close it.
	inside = motifs.Motif.cc(74, [64, 100], beats = [0, 1], length = 2.0)

	assert inside.length == 2.0
	assert _phrase_sends(inside, 4.0) == [(0.0, 64), (1.0, 100), (2.0, 64), (3.0, 100), (4.0, 64), (5.0, 100), (6.0, 64), (7.0, 100)]
