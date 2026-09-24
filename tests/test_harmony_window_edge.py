"""The harmony window looks across a section's edge, not round its own loop (#3086).

M3 of the 2026-09-19 review: "Harmony window across sections.  The window's
lookahead wraps inside the current section instead of reporting the next
section's first chord (next_chord = C where Am follows)."

A section's spans are computed arithmetically by `_data_future`, which wraps a
progression inside its own length for ever.  That is right INSIDE a section —
a two-chord progression in a four-bar section repeats — and wrong AT its end.
Measured before the fix, with a verse of [C, F] followed by a chorus of
[Am, G]: at the verse's last bar `p.harmony.next_chord` said **C**, the
verse's own first chord, where **Am** actually followed.  Exactly the
review's numbers.

Past the edge the window reports the next section's FIRST chord and nothing
further.  It first reported `None` for a graph or generator form, whose layout
past the playhead it took to be undecided.  It is not: each section's successor
is picked as the section starts, and `p.section.next_section` names it.  So a
part anticipating the next chord went silent at every edge of a graph form, the
one place anticipation is for (#3526).  The window now reads the pick, and
`None` is left for where nothing follows.
"""

import pathlib
import typing

import pytest

import subsequence
import subsequence.forms


def _window_per_bar (
	comp: "subsequence.Composition", bars: int, tmp_path: pathlib.Path
) -> typing.List[typing.Tuple[typing.Optional[str], typing.Optional[str], typing.Optional[str]]]:

	"""Render, and report (section, chord, next_chord) as each bar's pattern saw it.

	Read through `p.harmony` rather than the horizon directly: it is anchored
	at the pattern's own cycle start, which is the reading a musician gets.  A
	scheduled function fires a beat BEFORE the bar line, so reading the section
	from one and the chord from the bar start compares two different instants.
	"""

	seen: typing.List[typing.Tuple[typing.Optional[str], typing.Optional[str], typing.Optional[str]]] = []

	@comp.pattern(channel = 1, bars = 1)
	def melody (p: typing.Any) -> None:
		section = None if p.section is None else getattr(p.section, "name", str(p.section))
		chord = None if p.harmony is None or p.harmony.chord is None else p.harmony.chord.name()
		nxt = None if p.harmony is None or p.harmony.next_chord is None else p.harmony.next_chord.name()
		seen.append((section, chord, nxt))
		p.note(pitch = 60, beat = 0, velocity = 100, duration = 1)

	comp.render(bars = bars, filename = str(tmp_path / "w.mid"))

	return seen


def test_the_last_bar_of_a_section_sees_the_next_section_s_first_chord (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""The review's own case: next_chord = C where Am follows."""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([("verse", 2), ("chorus", 2)])
	comp.section_chords("verse", ["C", "F"])
	comp.section_chords("chorus", ["Am", "G"])

	seen = _window_per_bar(comp, 4, tmp_path)

	verse = [row for row in seen if row[0] == "verse"]

	assert len(verse) == 2, f"the verse did not play its two bars: {seen}"

	_section, sounding, predicted = verse[-1]

	assert sounding == "F", f"the verse's last bar sounded {sounding}, not F"
	assert predicted == "Am", (
		f"at the verse's last bar next_chord said {predicted}, not Am — the "
		f"chorus's first chord.  The whole reading was {seen}"
	)


def test_a_short_progression_still_repeats_inside_a_longer_section (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""The guard: bounding the future must not stop a section looping WITHIN itself."""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([("verse", 4), ("chorus", 1)])
	comp.section_chords("verse", ["C", "F"])
	comp.section_chords("chorus", ["Am"])

	seen = _window_per_bar(comp, 5, tmp_path)

	verse = [row for row in seen if row[0] == "verse"]

	assert len(verse) == 4, f"the verse did not play its four bars: {seen}"

	sounding = [chord for _s, chord, _n in verse]

	assert sounding == ["C", "F", "C", "F"], (
		f"the two-chord progression did not repeat inside its four-bar "
		f"section: {sounding}"
	)

	# And the wrap inside the section is still reported as a wrap.
	assert verse[0][2] == "F", f"bar 1 should see F next, saw {verse[0][2]}"
	assert verse[1][2] == "C", f"bar 2 should wrap to C, saw {verse[1][2]}"


def test_the_last_bar_of_a_finite_form_sees_nothing_after_it (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""Nothing follows, so next_chord says so rather than wrapping."""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([("verse", 2)])
	comp.section_chords("verse", ["C", "F"])

	seen = _window_per_bar(comp, 2, tmp_path)

	verse = [row for row in seen if row[0] == "verse"]

	assert len(verse) == 2, f"the verse did not play its two bars: {seen}"
	assert verse[-1][2] is None, (
		f"at the end of a finite form next_chord said {verse[-1][2]} instead "
		f"of None"
	)


def test_a_looping_form_sees_round_to_its_first_section (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""A loop genuinely does come back, so the window may say so."""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([("verse", 2), ("chorus", 2)], at_end = "loop")
	comp.section_chords("verse", ["C", "F"])
	comp.section_chords("chorus", ["Am", "G"])

	seen = _window_per_bar(comp, 4, tmp_path)

	chorus = [row for row in seen if row[0] == "chorus"]

	assert len(chorus) == 2, f"the chorus did not play its two bars: {seen}"
	assert chorus[-1][2] == "C", (
		f"at the last bar of a looping form next_chord said {chorus[-1][2]} "
		f"instead of C, the verse's first chord"
	)


def _bars (
	comp: "subsequence.Composition", bars: int, tmp_path: pathlib.Path
) -> typing.List[typing.Tuple[typing.Optional[str], int, int, typing.Optional[str], typing.Optional[str]]]:

	"""Render, and report (section, bar in it, its bars, chord, next_chord) as each bar's pattern saw it."""

	seen: typing.List[typing.Tuple[typing.Optional[str], int, int, typing.Optional[str], typing.Optional[str]]] = []

	@comp.pattern(channel = 1, bars = 1)
	def melody (p: typing.Any) -> None:
		chord = None if p.harmony is None or p.harmony.chord is None else p.harmony.chord.name()
		nxt = None if p.harmony is None or p.harmony.next_chord is None else p.harmony.next_chord.name()
		if p.section is None:
			seen.append((None, 0, 0, chord, nxt))
		else:
			seen.append((p.section.name, p.section.bar, p.section.bars, chord, nxt))
		p.note(pitch = 60, beat = 0, velocity = 100, duration = 1)

	comp.render(bars = bars, filename = str(tmp_path / "w.mid"))

	return seen


def _edges_that_name_what_follows (seen: typing.List[typing.Tuple[typing.Any, ...]]) -> typing.List[typing.Tuple[int, typing.Any, typing.Any]]:

	"""Every section's last bar that another section follows, as (bar, the next chord it read, the chord the next bar played).

	Where the form ends there is no next section, None is right, and the harmony holds its last chord.
	"""

	return [
		(index, row[4], seen[index + 1][3])
		for index, row in enumerate(seen[:-1])
		if row[0] is not None and row[1] == row[2] - 1 and seen[index + 1][0] is not None
	]


FORMS: typing.Dict[str, typing.Callable[[], typing.Any]] = {
	# A verse that can only go to the chorus, and back.
	"graph, one way": lambda: {"verse": (2, [("chorus", 1)]), "chorus": (2, [("verse", 1)])},
	# A real choice, re-picked at every section, and a section that can follow itself.
	"graph, a choice": lambda: {
		"verse": (2, [("chorus", 2), ("bridge", 1), ("verse", 1)]),
		"chorus": (2, [("verse", 1), ("bridge", 1)]),
		"bridge": (1, [("verse", 1)]),
	},
	# One-bar sections: the pick and the reading fall in the same bar.
	"graph, one bar each": lambda: {"verse": (1, [("chorus", 1)]), "chorus": (1, [("bridge", 1), ("verse", 1)]), "bridge": (1, [("verse", 1)])},
	"generator": lambda: (section for section in [("verse", 2), ("chorus", 1), ("bridge", 2), ("verse", 1), ("chorus", 2)] * 4),
	"list": lambda: [("verse", 2), ("chorus", 1), ("bridge", 2), ("verse", 1), ("chorus", 2)],
}


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_section_s_last_bar_names_the_chord_the_next_bar_plays (
	form: str, seed: int, patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""Whatever the form, next_chord at a section's last bar is what the next bar plays.

	A chord a bar, so the one change after a section's last bar is the next
	section's first chord.  A graph or generator form reported None here (#3526).
	"""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = seed)
	layout = FORMS[form]()
	comp.form(layout, start = "verse") if isinstance(layout, dict) else comp.form(layout)

	for name, chords in (("verse", ["C", "F"]), ("chorus", ["Am", "G"]), ("bridge", ["Dm", "E"])):
		if form != "graph, one way" or name != "bridge":
			comp.section_chords(name, chords)

	seen = _bars(comp, 12, tmp_path)
	edges = _edges_that_name_what_follows(seen)

	assert len(edges) >= 3, f"too few section edges to judge: {seen}"
	assert [(index, read) for index, read, played in edges if read != played] == [], (
		f"at these last bars next_chord did not name what the next bar played: {edges}.  The whole reading was {seen}"
	)


def test_the_end_of_a_graph_form_still_says_nothing_follows (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""The verse's last bar names the outro's first chord, and the outro, with nowhere to go, ends the form: its last bar's next_chord is None."""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 1)
	comp.form({"verse": (2, [("outro", 1)]), "outro": (2, None)}, start = "verse")
	comp.section_chords("verse", ["C", "F"])
	comp.section_chords("outro", ["Am", "G"])

	seen = _bars(comp, 4, tmp_path)

	assert [row[0] for row in seen[:4]] == ["verse", "verse", "outro", "outro"], seen
	assert seen[1][4] == "Am" and seen[3][4] is None, seen


def test_the_pick_is_given_only_for_the_section_whose_edge_it_is (patch_midi: None) -> None:

	"""The window made in one section, read after a live jump or a re-bind, gets None, not another section's pick.

	No render reaches that moment, between the form moving and the harmony clock next firing, so
	this asks the composition directly.
	"""

	comp = subsequence.Composition(key = "C", bpm = 120)
	comp.form({"verse": (2, [("chorus", 1)]), "chorus": (2, [("verse", 1)])}, start = "verse")
	comp.section_chords("verse", ["C", "F"])
	comp.section_chords("chorus", ["Am", "G"])

	info = comp.form_state.get_section_info()
	here = (comp._form_generation, info.index)

	assert info.next_section == "chorus"
	assert comp._following_section_progression(here) is comp._section_progressions["chorus"]
	assert comp._following_section_progression((comp._form_generation, info.index + 1)) is None
	assert comp._following_section_progression((comp._form_generation + 1, info.index)) is None


def test_a_one_bar_next_section_is_seen_as_itself (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""The lookahead must land on the next section's FIRST bar, exactly.

	With every section two bars long, looking a bar late still lands inside
	the same section and nothing is visibly wrong — which is how the break
	harness found this test missing.  A one-bar bridge is the case that tells
	the difference: a bar late skips it entirely and reports the chorus.
	"""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([("verse", 2), ("bridge", 1), ("chorus", 2)])
	comp.section_chords("verse", ["C", "F"])
	# Dm, not Bb: the library spells that pitch class A#, and comparing chord
	# NAMES across enharmonics reports a fault that is not there.
	comp.section_chords("bridge", ["Dm"])
	comp.section_chords("chorus", ["Am", "G"])

	seen = _window_per_bar(comp, 5, tmp_path)

	verse = [row for row in seen if row[0] == "verse"]

	assert len(verse) == 2, f"the verse did not play its two bars: {seen}"

	predicted = verse[-1][2]

	assert predicted == "Dm", (
		f"the verse's last bar predicted {predicted}, not Dm — the one-bar "
		f"bridge that actually follows.  The whole reading was {seen}"
	)


def test_a_span_running_past_the_section_edge_is_clipped_to_it (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""A chord whose span outlasts its section must not carry the boundary with it.

	Where a section's chords divide its length evenly, no span ever crosses
	the edge and clipping is invisible — which is why this needs a section
	whose harmonic rhythm does NOT fit: three bars of 4/4 is 12 beats, walked
	by 8-beat spans, so the second span runs 8 to 16 and crosses at 12.
	Unclipped, the boundary after beat 8 is reported as 16, which is past the
	section, and the window reads the wrong place.
	"""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([("verse", 3), ("chorus", 2)])
	comp.section_chords("verse", subsequence.progression(["C", "F"], beats = 8))
	comp.section_chords("chorus", ["Am", "G"])

	seen = _window_per_bar(comp, 5, tmp_path)

	verse = [row for row in seen if row[0] == "verse"]

	assert len(verse) == 3, f"the verse did not play its three bars: {seen}"

	predicted = verse[-1][2]

	assert predicted == "Am", (
		f"at the verse's last bar — inside a span that outlasts the section — "
		f"next_chord said {predicted}, not Am.  The whole reading was {seen}"
	)


def test_the_next_section_s_chords_resolve_against_its_own_key (
	patch_midi: None, tmp_path: pathlib.Path
) -> None:

	"""Looking across the edge must use the NEXT section's key, not this one's."""

	comp = subsequence.Composition(key = "C", bpm = 480, seed = 5)
	comp.form([
		subsequence.forms.Section("verse", 2),
		subsequence.forms.Section("chorus", 2, key = "Eb"),
	])
	comp.section_chords("verse", ["C", "F"])
	comp.section_chords("chorus", [1, 4])			# key-relative: I, IV

	seen = _window_per_bar(comp, 4, tmp_path)

	verse = [row for row in seen if row[0] == "verse"]
	chorus = [row for row in seen if row[0] == "chorus"]

	assert len(verse) == 2 and chorus, f"the form did not play as declared: {seen}"

	# The chorus's I in Eb is Eb (D# by the other spelling) — not C.
	sounded = chorus[0][1]
	predicted = verse[-1][2]

	assert predicted == sounded, (
		f"the window predicted {predicted} but the chorus sounded {sounded}: "
		f"the lookahead resolved against the wrong key"
	)
	assert predicted not in ("C", None), (
		f"the lookahead gave {predicted}, which is the composition key's I, "
		f"not the section's"
	)


# ---------------------------------------------------------------------------
# The future, read past the committed window
# ---------------------------------------------------------------------------

def test_the_future_clips_a_span_read_beyond_the_committed_window (
	patch_midi: None
) -> None:

	"""A lookahead reaching past what is committed must still stop at the edge.

	The committed span is clipped where it is written, so a read inside the
	window cannot see this.  Past the window the horizon falls through to the
	future function instead, and an unclipped span there reports a boundary
	beyond the section — the same fault, further out.  That is a real failure
	mode rather than a rarer one, which is why the clip is in both places.

	Three bars of 4/4 is 12 beats, walked by 8-beat spans: the second runs
	8 to 16 and the section ends at 12.
	"""

	import unittest.mock

	import subsequence.composition

	captured: typing.Dict[str, typing.Any] = {}

	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24

	async def capture (callback: typing.Any, start_pulse: int = 0, reschedule_lookahead: float = 1) -> None:
		captured["callback"] = callback

	mock_seq.schedule_callback_sequence = capture

	horizon = subsequence.composition._HarmonyHorizon()

	verse = subsequence.progression(["C", "F"], beats = 8)
	chorus = subsequence.progression(["Am", "G"], beats = 4)

	import asyncio

	asyncio.run(subsequence.composition.schedule_harmonic_clock(
		sequencer = mock_seq,
		horizon = horizon,
		bar_beats = 4.0,
		cycle_beats = 4.0,
		get_harmonic_state = lambda: None,
		get_section_progression = lambda: ("verse", 0, 3, verse),
		get_section_progression_at = lambda bar: chorus if bar >= 4 else verse,
	))

	# Only beat 0 has been walked, so beat 8 is past the committed window and
	# the horizon must fall through to the future to answer at all.
	span = horizon.span_at(8.0)

	assert span is not None, "the future answered nothing at beat 8"

	_start, end, _chord = span

	assert end == pytest.approx(12.0), (
		f"the span read past the committed window ends at {end}, not 12 — it "
		f"was not clipped to the section's edge"
	)
