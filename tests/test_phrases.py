"""Stage-4 tests: vary/answer, Phrase.develop + reroll, p.phrase placement,
the section_motifs registry, phrase_part, and sketch (b) end-to-end."""

import pathlib
import random
import typing

import mido
import pytest

import subsequence
import subsequence.constants
import subsequence.pattern
import subsequence.pattern_builder

M = subsequence.Motif
Degree = subsequence.Degree
PPQ = subsequence.constants.MIDI_QUARTER_NOTE


def steps_of (m: "subsequence.Motif") -> typing.List[typing.Optional[int]]:

	"""Degree steps per event (None for rests) — the melodic shape."""

	return [event.pitch.step if event.pitch is not None else None for event in m.events]


def rhythm_of (value: typing.Any) -> typing.List[typing.Tuple[float, float]]:

	"""(beat, duration) pairs — the rhythm skeleton."""

	flat = value.flatten() if hasattr(value, "flatten") else value

	return [(event.beat, event.duration) for event in flat.events]


def _builder (cycle: int = 0, length: float = 4.0, section: typing.Any = None, registry: typing.Any = None) -> subsequence.pattern_builder.PatternBuilder:

	"""A standalone builder over a fresh pattern."""

	pattern = subsequence.pattern.Pattern(channel=0, length=length)

	return subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = cycle,
		key = "A",
		scale = "minor",
		rng = random.Random(1),
		section = section,
		section_motifs = registry,
	)


def placed (p: subsequence.pattern_builder.PatternBuilder) -> typing.List[typing.Tuple[float, int]]:

	"""(beat, pitch) pairs for every placed note, in time order."""

	out = []

	for pulse in sorted(p._pattern.steps):
		for note in p._pattern.steps[pulse].notes:
			out.append((pulse / PPQ, note.pitch))

	return out


CALL = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3])		# 8 beats, one per beat


# ---------------------------------------------------------------------------
# Motif.vary()
# ---------------------------------------------------------------------------

def test_vary_changes_only_pitches_preserving_rhythm () -> None:

	"""Exactly N pitches move; rhythm, rests, length, controls untouched."""

	varied = CALL.vary(notes=2, seed=3)

	assert rhythm_of(varied) == rhythm_of(CALL)
	assert varied.length == CALL.length

	# The rest (beat 4) stays an absence — no event appears there.
	assert [event.beat for event in varied.events] == [0.0, 1.0, 2.0, 3.0, 5.0, 6.0, 7.0]

	changed = sum(
		1 for before, after in zip(steps_of(CALL), steps_of(varied))
		if before != after
	)
	assert changed == 2


def test_vary_positions () -> None:

	"""end varies the tail; start the head; anywhere draws from the stream."""

	tail = CALL.vary(notes=1, position="end", seed=3)
	head = CALL.vary(notes=1, position="start", seed=3)

	assert steps_of(tail)[:-1] == steps_of(CALL)[:-1] and steps_of(tail)[-1] != 3
	assert steps_of(head)[1:] == steps_of(CALL)[1:] and steps_of(head)[0] != 5


def test_vary_is_deterministic_and_clamps () -> None:

	"""Same seed, same variation; notes clamps to what exists; 0 is identity."""

	assert steps_of(CALL.vary(notes=2, seed=9)) == steps_of(CALL.vary(notes=2, seed=9))
	assert CALL.vary(notes=99, seed=1).length == CALL.length
	assert CALL.vary(notes=0, seed=1) == CALL


def test_vary_drums_raise_and_no_seed_warns () -> None:

	"""A varied drum is a different instrument; the seed policy applies."""

	kick = M.hits("kick", beats=[0, 2], length=4)

	with pytest.raises(TypeError, match="instrument"):
		kick.vary(notes=1, seed=1)

	with pytest.warns(UserWarning, match="seed"):
		CALL.vary(notes=1)


def test_vary_degree_floor () -> None:

	"""Varied degrees never drop below 1."""

	low = subsequence.motif([1, 1, 1, 1])

	for seed in range(20):
		assert all(step >= 1 for step in steps_of(low.vary(notes=4, position="anywhere", seed=seed)) if step)


# ---------------------------------------------------------------------------
# Motif.answer()
# ---------------------------------------------------------------------------

def test_answer_reaims_the_tail_home () -> None:

	"""The last pitched note lands on degree 1; everything else is untouched."""

	response = CALL.answer()

	assert steps_of(response) == [5, 6, 5, 3, 1, 2, 1]		# the rest holds no event
	assert rhythm_of(response) == rhythm_of(CALL)


def test_answer_half_close_and_register () -> None:

	"""to=5 half-closes; the original note's octave survives the re-aim."""

	high_tail = M.degrees([5, Degree(3, octave=1)])
	answered = high_tail.answer(to=5)

	assert answered.events[-1].pitch == Degree(5, octave=1)


def test_answer_non_degree_content_raises () -> None:

	"""Absolute MIDI has no degrees to re-aim."""

	with pytest.raises(TypeError, match="degrees"):
		M.notes([60, 64, 67]).answer()


# ---------------------------------------------------------------------------
# Phrase.develop()
# ---------------------------------------------------------------------------

def test_develop_label_plan () -> None:

	"""First label = the motif; repeats restate; new labels contrast (same rhythm)."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan=["a", "a", "a", "b"], seed=11)

	assert len(phrase.segments) == 4
	assert phrase.segments[0] == CALL
	assert phrase.segments[1] == CALL and phrase.segments[2] == CALL

	contrast = phrase.segments[3]
	assert contrast != CALL
	assert rhythm_of(contrast) == rhythm_of(CALL)
	assert phrase.length == 32.0
	assert phrase.recipe is not None


def test_develop_call_response_recipe () -> None:

	"""call_response = call, answer, call, varied answer."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan="call_response", seed=11)

	assert phrase.segments[0] == CALL
	assert phrase.segments[1] == CALL.answer()
	assert phrase.segments[2] == CALL
	assert phrase.segments[3] != CALL.answer()				# the tail varied
	assert rhythm_of(phrase.segments[3]) == rhythm_of(CALL)


def test_develop_letter_string_fails_name_lookup_with_list_hint () -> None:

	"""plan="aaab" is not a plan — the error suggests the list (decision 16)."""

	with pytest.raises(ValueError, match=r"plan=\['a', 'a', 'a', 'b'\]"):
		subsequence.Phrase.develop(CALL, bars=8, plan="aaab", seed=1)

	with pytest.raises(ValueError, match="Known recipes"):
		subsequence.Phrase.develop(CALL, bars=8, plan="no_such_recipe", seed=1)


def test_develop_validates_bars_against_units () -> None:

	"""Uneven bars or a mismatched motif length fail with the numbers."""

	with pytest.raises(ValueError, match="evenly"):
		subsequence.Phrase.develop(CALL, bars=7, plan=["a", "b"], seed=1)

	with pytest.raises(ValueError, match="beats"):
		subsequence.Phrase.develop(CALL, bars=2, plan=["a", "b"], seed=1)	# 4-beat units vs an 8-beat motif


def test_develop_is_deterministic_and_warns_without_seed () -> None:

	"""Same seed, same phrase; the generator seed policy applies."""

	first = subsequence.Phrase.develop(CALL, bars=8, plan=["a", "b", "a", "b"], seed=5)
	second = subsequence.Phrase.develop(CALL, bars=8, plan=["a", "b", "a", "b"], seed=5)

	assert first.segments == second.segments

	with pytest.warns(UserWarning, match="seed"):
		subsequence.Phrase.develop(CALL, bars=8, plan=["a", "a", "a", "b"])


def test_develop_requires_a_plan () -> None:

	"""No silent default plan."""

	with pytest.raises(ValueError, match="plan="):
		subsequence.Phrase.develop(CALL, bars=8, seed=1)


# ---------------------------------------------------------------------------
# Phrase.reroll()
# ---------------------------------------------------------------------------

def test_reroll_changes_only_the_named_bar () -> None:

	"""Bar 7 re-rolls; every other bar is untouched; rhythm survives everywhere."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan="call_response", seed=11)
	rerolled = phrase.reroll(bar=7, seed=4)

	assert rhythm_of(rerolled) == rhythm_of(phrase)

	original = phrase.flatten().events
	changed = rerolled.flatten().events
	bar_window = lambda event: 24.0 <= event.beat < 28.0	# bar 7 of 8 (4 beats each)

	outside_before = [event for event in original if not bar_window(event)]
	outside_after = [event for event in changed if not bar_window(event)]
	assert outside_before == outside_after

	inside_before = [event for event in original if bar_window(event)]
	inside_after = [event for event in changed if bar_window(event)]
	assert inside_before != inside_after


def test_reroll_keeps_boundary_pitches () -> None:

	"""The first and last pitched notes of the bar are pins."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan="call_response", seed=11)
	rerolled = phrase.reroll(bar=7, seed=4)

	def bar_events (value: "subsequence.Phrase") -> typing.List[typing.Any]:
		return [e for e in value.flatten().events if 24.0 <= e.beat < 28.0 and e.pitch is not None]

	before, after = bar_events(phrase), bar_events(rerolled)

	assert after[0].pitch == before[0].pitch
	assert after[-1].pitch == before[-1].pitch


def test_reroll_composes_and_is_deterministic () -> None:

	"""The recipe survives a reroll, so rerolls chain; same seed, same roll."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan="call_response", seed=11)

	once = phrase.reroll(bar=7, seed=4)
	again = phrase.reroll(bar=7, seed=4)
	assert once.flatten().events == again.flatten().events

	chained = once.reroll(bars=[3, 4], seed=9)
	assert chained.recipe is phrase.recipe


def test_reroll_literal_raises_loudly () -> None:

	"""A hand-written phrase has no recipe to regenerate from."""

	literal = subsequence.Phrase([CALL, CALL.answer()])

	with pytest.raises(ValueError, match="recipe"):
		literal.reroll(bar=1, seed=1)


def test_reroll_transformed_phrase_raises () -> None:

	"""Transforms drop the recipe — the notes no longer come from it."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan="call_response", seed=11)

	with pytest.raises(ValueError, match="recipe"):
		phrase.stretch(2.0).reroll(bar=1, seed=1)


def test_reroll_validates_region_arguments () -> None:

	"""bar=/bars= are exclusive; bars are 1-based and in range."""

	phrase = subsequence.Phrase.develop(CALL, bars=8, plan="call_response", seed=11)

	with pytest.raises(ValueError, match="exactly one"):
		phrase.reroll(bar=1, bars=[2], seed=1)
	with pytest.raises(ValueError, match="exactly one"):
		phrase.reroll(seed=1)
	with pytest.raises(ValueError, match="outside"):
		phrase.reroll(bar=9, seed=1)
	with pytest.raises(ValueError, match="outside"):
		phrase.reroll(bar=0, seed=1)


# ---------------------------------------------------------------------------
# p.phrase() — stateless placement
# ---------------------------------------------------------------------------

def test_phrase_position_walks_with_the_cycle () -> None:

	"""A 4-beat pattern walks an 8-beat phrase: first half, then second, then loops."""

	value = subsequence.Phrase([M.degrees([1, 2, 3, 4]), M.degrees([5, 6, 7, 8])])

	first = _builder(cycle=0); first.phrase(value, root=60)
	second = _builder(cycle=1); second.phrase(value, root=60)
	third = _builder(cycle=2); third.phrase(value, root=60)

	assert [pitch for _, pitch in placed(first)] == [pitch for _, pitch in placed(third)]
	assert placed(first) != placed(second)
	assert len(placed(second)) == 4


def test_phrase_wraps_across_its_end () -> None:

	"""A cycle window straddling the phrase end loops to the start."""

	value = subsequence.Phrase([M.degrees([1, 2, 3, 4, 5, 6], length=6.0)])

	wrap = _builder(cycle=1)	# beats 4..8 of a 6-beat phrase → [4,6) then [0,2)
	wrap.phrase(value, root=60)

	notes = placed(wrap)
	assert len(notes) == 4
	assert [beat for beat, _ in notes] == [0.0, 1.0, 2.0, 3.0]

	tonic = _builder(cycle=0); tonic.phrase(value, root=60)
	assert notes[2][1] == placed(tonic)[0][1]	# beat 2 of the window = the phrase's start


def test_phrase_offset_and_section_alignment () -> None:

	"""offset= phase-shifts; align="section" follows the section bar."""

	value = subsequence.Phrase([M.degrees([1, 2, 3, 4]), M.degrees([5, 6, 7, 8])])

	shifted = _builder(cycle=0)
	shifted.phrase(value, root=60, offset=4.0)
	plain = _builder(cycle=1)
	plain.phrase(value, root=60)
	assert placed(shifted) == placed(plain)

	class FakeSection:
		name = "verse"
		bar = 1		# 0-indexed: the second bar of the section

	sectioned = _builder(cycle=99, section=FakeSection())
	sectioned.phrase(value, root=60, align="section")
	assert placed(sectioned) == placed(plain)

	with pytest.raises(ValueError, match="form"):
		_builder(cycle=0).phrase(value, root=60, align="section")


def test_phrase_accepts_motifs_and_validates () -> None:

	"""Motifs duck-type in; garbage and empties fail loudly."""

	walker = _builder(cycle=0)
	walker.phrase(M.degrees([1, 2, 3, 4]), root=60)
	assert len(placed(walker)) == 4

	with pytest.raises(TypeError, match="Phrase-like"):
		_builder().phrase(42)


# ---------------------------------------------------------------------------
# section_motifs registry + phrase_part + sketch (b)
# ---------------------------------------------------------------------------

def test_section_motif_reads_the_registry () -> None:

	"""p.section_motif() returns the binding for the current section and part."""

	class FakeSection:
		name = "verse"
		bar = 0

	registry = {("verse", "lead"): CALL, ("verse", None): CALL.answer()}

	p = _builder(section=FakeSection(), registry=registry)

	assert p.section_motif("lead") == CALL
	assert p.section_motif() == CALL.answer()
	assert p.section_motif("bass") is None
	assert _builder().section_motif("lead") is None		# no form → None


def test_section_motifs_binder_validates (patch_midi: None) -> None:

	"""Unknown form sections and non-values are rejected."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="A", scale="minor")
	composition.form({"verse": (4, [("verse", 1)])}, start="verse")

	with pytest.raises(ValueError, match="not found"):
		composition.section_motifs("bridge", CALL)
	with pytest.raises(TypeError, match="Motif/Phrase"):
		composition.section_motifs("verse", [1, 2, 3])

	composition.section_motifs("verse", CALL, part="lead")
	assert composition._section_motifs[("verse", "lead")] == CALL


def test_phrase_part_follows_sections_and_silences_unbound (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""Each section sounds its bound line; a section with no binding is silent."""

	filename = str(tmp_path / "parts.mid")
	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="C")
	composition.form([("verse", 1), ("chorus", 1), ("outro", 1)])

	composition.section_motifs("verse", M.notes([60, 62, 64, 65]), part="lead")
	composition.section_motifs("chorus", M.notes([72, 74, 76, 77]), part="lead")
	# outro deliberately unbound — silence, by design

	composition.phrase_part(channel=2, part="lead", beats=4)

	composition.render(bars=3, filename=filename)

	mid = mido.MidiFile(filename)
	ticks_per_bar = mid.ticks_per_beat * 4
	by_bar: typing.Dict[int, typing.List[int]] = {}
	for track in mid.tracks:
		now = 0
		for msg in track:
			now += msg.time
			if not isinstance(msg, mido.MetaMessage) and msg.type == "note_on" and msg.velocity > 0:
				by_bar.setdefault(now // ticks_per_bar, []).append(msg.note)

	assert sorted(by_bar[0]) == [60, 62, 64, 65]
	assert sorted(by_bar[1]) == [72, 74, 76, 77]
	assert 2 not in by_bar


def test_sketch_b_motif_to_phrase_to_placement_to_reroll (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""Sketch (b): hand-written 2-bar motif → 8-bar phrase → placement → reroll bar 7."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="A", scale="minor", seed=42)

	call = subsequence.motif([5, 6, 5, 3, None, 1, 2, 3]).accent(0)
	lead_line = subsequence.Phrase.develop(call, bars=8, plan="call_response", seed=11)
	lead_line = lead_line.reroll(bar=7, seed=4)

	heard: typing.List[typing.Tuple[int, typing.Tuple[typing.Tuple[float, int], ...]]] = []

	@composition.pattern(channel=4, bars=2)
	def lead (p) -> None:
		p.phrase(lead_line, root=72, fit=0.8)
		p.legato(0.9)
		heard.append(p.cycle)

	composition.render(bars=8, filename=str(tmp_path / "sketch_b.mid"))

	# Four cycles walked the whole phrase (a fifth rebuild may prepare the
	# cycle after the render window — lookahead).
	assert heard[:4] == [0, 1, 2, 3]

	mid = mido.MidiFile(str(tmp_path / "sketch_b.mid"))
	window = mid.ticks_per_beat * 32		# the 8 rendered bars

	count = 0
	for track in mid.tracks:
		now = 0
		for msg in track:
			now += msg.time
			if not isinstance(msg, mido.MetaMessage) and msg.type == "note_on" and msg.velocity > 0 and now < window:
				count += 1

	# 8 bars x (4 notes per bar minus the rest every 2 bars) = 28 notes
	# inside the rendered window (lookahead may queue the next cycle's first
	# note exactly on the boundary).
	assert count == 28
