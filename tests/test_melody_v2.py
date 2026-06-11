"""Stage-5 tests: the melody engine v2.

Covers the CSEG/CSIM kernels, the pluggable scoring factors (contour
envelope, tessitura regression), MelodicState clone/set_pool/deferred
defaults, Motif.generate (rhythm-first, degree emission, pins, contour,
max_pitches, state copying), vary(keep_contour=True), Approach resolution
against the next chord, and the fit dial — ending with sketch (f)'s hook.
"""

import pathlib
import random
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.melodic_state
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.intervals
import subsequence.sequence_utils

M = subsequence.Motif
Degree = subsequence.Degree
ChordTone = subsequence.ChordTone
Approach = subsequence.Approach


# ---------------------------------------------------------------------------
# CSEG / CSIM kernels
# ---------------------------------------------------------------------------

def test_cseg_ranks_the_shape () -> None:

	"""CSEG abstracts the contour from exact pitch; equal pitches share ranks."""

	assert subsequence.sequence_utils.cseg([60, 67, 64]) == [0, 2, 1]
	assert subsequence.sequence_utils.cseg([50, 59, 55]) == [0, 2, 1]
	assert subsequence.sequence_utils.cseg([5, 5, 3]) == [1, 1, 0]
	assert subsequence.sequence_utils.cseg([]) == []


def test_csim_measures_shared_order_relations () -> None:

	"""1.0 for identical shapes; lower as pairwise relations disagree."""

	assert subsequence.sequence_utils.csim([60, 67, 64], [50, 59, 55]) == 1.0
	assert subsequence.sequence_utils.csim([1, 2, 3], [3, 2, 1]) == 0.0
	assert 0.0 < subsequence.sequence_utils.csim([1, 2, 3], [1, 3, 2]) < 1.0

	with pytest.raises(ValueError, match="equal-length"):
		subsequence.sequence_utils.csim([1, 2], [1, 2, 3])


# ---------------------------------------------------------------------------
# The factor list (the CHORAL split)
# ---------------------------------------------------------------------------

def test_factors_are_pluggable () -> None:

	"""Replacing the factor list reshapes the generator's taste."""

	state = subsequence.MelodicState(key="C", mode="ionian", low=60, high=72)

	# An iron fist: only pitch 64 scores.
	state.factors = [lambda s, ctx: 1.0 if ctx.candidate == 64 else 0.0]

	for _ in range(10):
		assert state.choose_next(None, random.Random(1)) == 64


def test_contour_factor_pulls_toward_the_target () -> None:

	"""With a contour target threaded, candidates near it dominate."""

	state = subsequence.MelodicState(key="C", mode="ionian", low=48, high=84, nir_strength=0.0)

	highs = [state.choose_next(None, random.Random(seed), contour_target=1.0) for seed in range(40)]
	state.history.clear()
	lows = [state.choose_next(None, random.Random(seed), contour_target=0.0) for seed in range(40)]

	average = lambda values: sum(v for v in values if v) / len(values)
	assert average(highs) - average(lows) > 12		# the envelope moves the register


def test_tessitura_regression_pulls_home () -> None:

	"""After straying high, candidates moving back toward the centre are boosted."""

	state = subsequence.MelodicState(key="C", mode="ionian", low=48, high=84, tessitura_strength=1.0, nir_strength=0.0)
	state.history = [83]		# far above centre (66)

	ctx_home = subsequence.melodic_state.ScoringContext(
		candidate=72, history=(83,), chord_tone_pcs=frozenset(), tonic_pc=0, low=48, high=84,
	)
	ctx_away = subsequence.melodic_state.ScoringContext(
		candidate=84, history=(83,), chord_tone_pcs=frozenset(), tonic_pc=0, low=48, high=84,
	)

	assert subsequence.melodic_state.tessitura_factor(state, ctx_home) > 1.0
	assert subsequence.melodic_state.tessitura_factor(state, ctx_away) == 1.0


# ---------------------------------------------------------------------------
# MelodicState: clone, set_pool, deferred defaults
# ---------------------------------------------------------------------------

def test_clone_is_independent () -> None:

	"""A clone walks alone — the original's history never moves."""

	state = subsequence.MelodicState(key="A", mode="aeolian", low=57, high=81)
	state.choose_next(None, random.Random(1))

	duplicate = state.clone()
	duplicate.choose_next(None, random.Random(2))
	duplicate.choose_next(None, random.Random(3))

	assert len(state.history) == 1
	assert len(duplicate.history) == 3
	assert duplicate.history[0] == state.history[0]


def test_set_pool_is_the_experimental_seam () -> None:

	"""An explicit pool replaces the scale entirely (sieves, hand-picked sets)."""

	state = subsequence.MelodicState(key="C", mode="ionian")
	state.set_pool([60, 61, 66])

	for seed in range(10):
		assert state.choose_next(None, random.Random(seed)) in (60, 61, 66)

	with pytest.raises(ValueError):
		state.set_pool([])


def test_melody_adopts_composition_key_and_scale () -> None:

	"""A state built bare adopts p.key/p.scale on first use; explicit args win."""

	def build (state: subsequence.MelodicState) -> None:
		pattern = subsequence.pattern.Pattern(channel=0, length=4)
		builder = subsequence.pattern_builder.PatternBuilder(
			pattern=pattern, cycle=0, key="E", scale="phrygian", rng=random.Random(1),
		)
		builder.melody(state, spacing=1.0, seed=1)

	adopted = subsequence.MelodicState()
	build(adopted)
	assert adopted.key == "E" and adopted.mode == "phrygian"

	explicit = subsequence.MelodicState(key="C", mode="ionian")
	build(explicit)
	assert explicit.key == "C" and explicit.mode == "ionian"


# ---------------------------------------------------------------------------
# Motif.generate
# ---------------------------------------------------------------------------

def test_generate_is_rhythm_first () -> None:

	"""The onsets ARE the rhythm; length defaults to the next whole bar."""

	hook = M.generate(rhythm=[0, 1, 1.5, 1.75, 2.5], seed=7)

	assert [event.beat for event in hook.events] == [0, 1, 1.5, 1.75, 2.5]
	assert hook.length == 4.0
	assert all(isinstance(event.pitch, Degree) for event in hook.events)
	assert hook.fit == 0.7		# generated motifs want to play against the changes


def test_generate_borrows_a_motifs_rhythm () -> None:

	"""rhythm= takes another motif — cross-pattern rhythm reuse is shared values."""

	kick = M.hits("kick", beats=[0, 1.5, 3], length=4)
	line = M.generate(rhythm=kick, seed=3)

	assert [event.beat for event in line.events] == [0, 1.5, 3]


def test_generate_is_deterministic_and_warns_without_seed () -> None:

	"""Same seed, same line; the generator seed policy applies."""

	assert M.generate(rhythm=[0, 1, 2, 3], seed=5) == M.generate(rhythm=[0, 1, 2, 3], seed=5)

	with pytest.warns(UserWarning, match="seed"):
		M.generate(rhythm=[0, 1])


def test_generate_end_on_and_pins () -> None:

	"""end_on pins the last note; pins fix any 1-based position (-1 = last)."""

	line = M.generate(rhythm=[0, 1, 2, 3], end_on=1, pins={1: 5}, seed=9)

	first, last = line.events[0].pitch, line.events[-1].pitch
	assert isinstance(first, Degree) and first.step == 5
	assert isinstance(last, Degree) and last.step == 1 and last.octave == 0

	with pytest.raises(ValueError, match="same position"):
		M.generate(rhythm=[0, 1], end_on=1, pins={-1: 5}, seed=1)
	with pytest.raises(ValueError, match="outside"):
		M.generate(rhythm=[0, 1], pins={9: 1}, seed=1)


def test_generate_contour_shapes_the_line () -> None:

	"""An ascending contour ends higher than it starts (statistically certain)."""

	def height (event: typing.Any) -> float:
		return event.pitch.octave * 7 + event.pitch.step

	rises = 0
	for seed in range(20):
		line = M.generate(rhythm=list(range(8)), contour="ascending", seed=seed)
		if height(line.events[-1]) > height(line.events[0]):
			rises += 1

	assert rises >= 16

	with pytest.raises(ValueError, match="contour"):
		M.generate(rhythm=[0, 1], contour="zigzag", seed=1)


def test_generate_scale_constrains_candidates () -> None:

	"""scale="minor_pentatonic" admits only pentatonic degrees (minor-family spelling)."""

	line = M.generate(rhythm=list(range(16)), length=16, scale="minor_pentatonic", seed=4)

	minor = subsequence.intervals.scale_pitch_classes(0, "minor")
	pentatonic = set(subsequence.intervals.scale_pitch_classes(0, "minor_pentatonic"))

	for event in line.events:
		offset = (minor[(event.pitch.step - 1) % 7] + event.pitch.chroma) % 12
		assert offset in pentatonic


def test_generate_max_pitches_caps_the_pool () -> None:

	"""A tight pool is a hook: at most N distinct pitches."""

	line = M.generate(rhythm=list(range(16)), length=16, max_pitches=3, seed=2)

	assert len({(e.pitch.step, e.pitch.octave, e.pitch.chroma) for e in line.events}) <= 3


def test_generate_midi_pool_is_absolute () -> None:

	"""An explicit MIDI pool switches to absolute output — the sieve path."""

	line = M.generate(rhythm=[0, 1, 2, 3], scale=[60, 61, 66, 70], seed=8)

	assert all(isinstance(event.pitch, int) for event in line.events)
	assert all(event.pitch in (60, 61, 66, 70) for event in line.events)


def test_generate_copies_the_state () -> None:

	"""A module-level MelodicState is never mutated by building a value."""

	state = subsequence.MelodicState(key="A", mode="aeolian", low=57, high=81)
	state.history = [69, 72]

	before = list(state.history)
	M.generate(rhythm=[0, 1, 2, 3], state=state, seed=6)

	assert state.history == before


# ---------------------------------------------------------------------------
# vary(keep_contour=True)
# ---------------------------------------------------------------------------

def test_keep_contour_preserves_the_cseg () -> None:

	"""Varied lines keep their shape — the motif-identity guard."""

	line = subsequence.motif([1, 5, 3, 7, 2, 6])
	ranks = lambda m: subsequence.sequence_utils.cseg([e.pitch.step for e in m.events])

	for seed in range(20):
		varied = line.vary(notes=3, position="anywhere", seed=seed, keep_contour=True)
		assert ranks(varied) == ranks(line)


def test_keep_contour_yields_where_shape_forbids_motion () -> None:

	"""When no nudge preserves the contour, the note stays — shape wins."""

	# Adjacent steps everywhere: most nudges break the order relations.
	tight = subsequence.motif([1, 2, 3])
	varied = tight.vary(notes=3, position="anywhere", seed=3, keep_contour=True)

	ranks = lambda m: subsequence.sequence_utils.cseg([e.pitch.step for e in m.events])
	assert ranks(varied) == ranks(tight)


# ---------------------------------------------------------------------------
# Approach resolution + the fit dial (placement)
# ---------------------------------------------------------------------------

class _StubHarmony:

	"""A HarmonyView stand-in with a chord change at a known beat."""

	def __init__ (self, current: typing.Any, following: typing.Any, change_at: float = 4.0) -> None:
		self._current = current
		self._following = following
		self._change_at = change_at

	def chord_at (self, beat: float) -> typing.Any:
		return self._current if beat < self._change_at else self._following

	def next_chord_at (self, beat: float) -> typing.Any:
		return self._following if beat < self._change_at else None


def _builder (harmony: typing.Any = None, length: float = 8.0, seed: int = 1) -> subsequence.pattern_builder.PatternBuilder:

	"""A standalone builder over a fresh pattern."""

	pattern = subsequence.pattern.Pattern(channel=0, length=length)

	return subsequence.pattern_builder.PatternBuilder(
		pattern=pattern, cycle=0, key="A", scale="minor", rng=random.Random(seed), harmony=harmony,
	)


def _placed (p: subsequence.pattern_builder.PatternBuilder) -> typing.List[typing.Tuple[float, int]]:

	out = []
	for pulse in sorted(p._pattern.steps):
		for note in p._pattern.steps[pulse].notes:
			out.append((pulse / subsequence.constants.MIDI_QUARTER_NOTE, note.pitch))
	return out


def test_approach_lands_a_semitone_below_the_next_chords_tone () -> None:

	"""Approach(ChordTone) reads the chord AFTER the event — the landing harmony."""

	a_minor = subsequence.chords.parse_chord("Am")
	f_major = subsequence.chords.parse_chord("F")
	view = _StubHarmony(a_minor, f_major, change_at=4.0)

	p = _builder(harmony=view)
	p.motif(M.from_events([
		subsequence.MotifEvent(beat=3.5, pitch=Approach(ChordTone("root"))),
	], length=8), root=60)

	# F's root nearest 60 is 65; the approach is 64 — into the change.
	assert _placed(p) == [(3.5, 64)]


def test_fit_snaps_strong_beats_to_chord_tones () -> None:

	"""fit=1.0: every strong-beat degree lands on a chord tone; offbeats are free."""

	a_minor = subsequence.chords.parse_chord("Am")
	view = _StubHarmony(a_minor, a_minor, change_at=99.0)
	chord_pcs = {9, 0, 4}

	line = M.degrees([2, 2, 2, 2], beats=[0.0, 1.0, 2.0, 3.0], length=4)

	snapped = _builder(harmony=view)
	snapped.motif(line, root=60, fit=1.0)
	for beat, pitch in _placed(snapped):
		assert pitch % 12 in chord_pcs		# B (degree 2) pulled to a neighbouring chord tone

	free = _builder(harmony=view)
	free.motif(line, root=60, fit=0.0)
	assert all(pitch % 12 == 11 for _, pitch in _placed(free))		# untouched


def test_fit_defaults_split_by_intent () -> None:

	"""Hand-written degrees stay sacred (no snap); generated motifs carry 0.7."""

	a_minor = subsequence.chords.parse_chord("Am")
	view = _StubHarmony(a_minor, a_minor, change_at=99.0)

	hand = _builder(harmony=view)
	hand.motif(M.degrees([2, 2, 2, 2], beats=[0.0, 1.0, 2.0, 3.0], length=4), root=60)
	assert all(pitch % 12 == 11 for _, pitch in _placed(hand))		# typed degrees untouched

	generated = M.generate(rhythm=[0, 1, 2, 3], seed=1)
	assert generated.fit == 0.7		# the default rides the value into placement


def test_fit_inactive_without_a_chord_context () -> None:

	"""No harmony, no snap — fit degrades gracefully."""

	p = _builder(harmony=None)
	p.motif(M.degrees([2, 2], beats=[0.0, 1.0], length=2), root=60, fit=1.0)

	assert all(pitch % 12 == 11 for _, pitch in _placed(p))


# ---------------------------------------------------------------------------
# Sketch (f)'s hook — the generate line, end to end
# ---------------------------------------------------------------------------

def test_sketch_f_hook_generates_develops_and_places (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""The hook line from sketch (f): generate → develop → bind → sound."""

	import mido

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="A", scale="minor", seed=42)
	composition.harmony(progression=["Am", "F", "C", "G"])
	composition.form([("verse", 8)])

	hook = subsequence.Motif.generate(
		rhythm=[0, 1, 1.5, 1.75, 2.5], scale="minor_pentatonic",
		contour="arch", end_on=1, seed=composition.seed_for("hook"),
	)
	verse_line = subsequence.Phrase.develop(hook, bars=8, plan="call_response",
		seed=composition.seed_for("verse_line"))

	composition.section_motifs("verse", verse_line, part="lead")
	composition.phrase_part(channel=4, root=78, part="lead")

	filename = str(tmp_path / "hook.mid")
	composition.render(bars=8, filename=filename)

	mid = mido.MidiFile(filename)
	note_ons = [
		msg for track in mid.tracks for msg in track
		if not isinstance(msg, mido.MetaMessage) and msg.type == "note_on" and msg.velocity > 0
	]

	# 4 call_response units x 5 hook onsets, walked bar by bar.
	assert len(note_ons) >= 20
