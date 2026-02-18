
import collections
import random

import pytest
import typing

import subsequence.chords
import subsequence.harmonic_state


class MockGraph:

	def __init__ (self, key_name: str) -> None:

		self.tonic = subsequence.chords.Chord(root_pc=0, quality="major") # C Major


	def build (self, key_name: str) -> typing.Tuple["MockGraph", subsequence.chords.Chord]:

		return self, self.tonic


	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		return set(), set()


	def choose_next (self, source: subsequence.chords.Chord, rng: typing.Any, weight_modifier: typing.Callable) -> typing.Tuple[float, float]:

		# We only care about ensuring weight_modifier is called correctly
		# and returns modified weights based on history

		# Test Case 1: Reversal (Gap Fill)
		# Previous: C (0) -> A (9, up 9 semitones)
		# Target A: F (5, down 4 semitones from A) -> Should be BOOSTED
		# Target B: C (12/0, up 3 semitones from A) -> Should be NORMAL/LOWER

		target_down = subsequence.chords.Chord(root_pc=5, quality="major") # F
		target_up = subsequence.chords.Chord(root_pc=0, quality="major")   # C (next octave conceptually)

		# Base weight is 10 for both
		w_down = weight_modifier(source, target_down, 10)
		w_up = weight_modifier(source, target_up, 10)

		return (w_down, w_up)


def test_nir_history_tracking () -> None:

	hs = subsequence.harmonic_state.HarmonicState(key_name="C")

	# Simulate a sequence: C -> F -> G
	c = subsequence.chords.Chord(root_pc=0, quality="major")
	f = subsequence.chords.Chord(root_pc=5, quality="major")
	g = subsequence.chords.Chord(root_pc=7, quality="major")

	# Manually inject history for testing
	hs.current_chord = c
	hs.step() # transition to something (mocked)

	# Step simulation
	hs.current_chord = f
	hs.step()

	assert len(hs.history) > 0
	assert hs.history[-1] == f


def test_calculate_nir_score_reversal () -> None:

	"""
	Test Rule A: Reversal (Gap Fill)
	If previous move was a Large Leap (> 5 semitones),
	BOOST targets that change direction.
	"""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C")

	"""
	Test Rule A: Reversal (Gap Fill)
	If previous move was a Large Leap (> 4 semitones),
	BOOST targets that change direction.
	"""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C")

	# History: C (0) -> G (7)
	# Modulo 12 shortest path: 7 - 0 = +7. >6 so 7-12 = -5.
	# Interval = 5 (Large Leap). Direction = DOWN.
	c = subsequence.chords.Chord(root_pc=0, quality="major")
	g = subsequence.chords.Chord(root_pc=7, quality="major")

	hs.history = [c]
	source = g

	# Target 1: A (9). G->A is +2.
	# Direction = UP (Opposite to prev DOWN).
	# Interval = 2 (Small).
	# Reversal Expects: Change Direction (Yes) AND Small Interval (Yes).
	# Should get MAX boost.
	target_reversal = subsequence.chords.Chord(root_pc=9, quality="minor")

	# Target 2: E (4). G->E is -3.
	# Direction = DOWN (Same as prev).
	# Interval = 3.
	# Should get NO boost.
	target_continuation = subsequence.chords.Chord(root_pc=4, quality="minor")

	score_rev = hs._calculate_nir_score(source, target_reversal)
	score_cont = hs._calculate_nir_score(source, target_continuation)

	assert score_rev > 1.0
	assert score_rev > score_cont


def test_calculate_nir_score_process () -> None:

	"""
	Test Rule B: Process (Continuation)
	If previous move was a Small Step (< 4 semitones),
	BOOST targets that continue in the Same Direction.
	"""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C")

	# History: C (0) -> D (2) = +2 semitones (Small Step Up)
	c = subsequence.chords.Chord(root_pc=0, quality="major")
	d = subsequence.chords.Chord(root_pc=2, quality="minor")

	hs.history = [c]
	source = d

	# Target 1: E (4) = +2 semitones (Continuation Up) -> Expect BOOST
	target_continuation = subsequence.chords.Chord(root_pc=4, quality="minor")

	# Target 2: B (11) = -3 semitones (Reversal Down) -> Expect NEUTRAL
	target_reversal = subsequence.chords.Chord(root_pc=11, quality="diminished")

	score_cont = hs._calculate_nir_score(source, target_continuation)
	score_rev = hs._calculate_nir_score(source, target_reversal)

	assert score_cont > 1.0
	assert score_cont > score_rev


def test_calculate_nir_score_closure () -> None:

	"""
	Test Rule C: Closure
	Return to Tonic implies closure and should be boosted if other conditions match.
	"""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C")

	"""
	Test Rule C: Closure
	Return to Tonic implies closure and should be boosted if other conditions match.
	"""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C")

	# History: C (0) -> E (4).
	# Interval = 4 (Neutral - neither Small Step <3 nor Large Leap >4).
	# Rule A and Rule B should NOT fire.
	c = subsequence.chords.Chord(root_pc=0, quality="major")
	e = subsequence.chords.Chord(root_pc=4, quality="minor")

	hs.history = [c]
	source = e

	# Target 1: C (0). E->C is -4. Neutral interval.
	# Gets Closure Boost (+0.2).
	target_tonic = subsequence.chords.Chord(root_pc=0, quality="major")

	# Target 2: G# (8). E->G# is +4. Neutral interval.
	# No Closure Boost.
	target_other = subsequence.chords.Chord(root_pc=8, quality="major")

	score_tonic = hs._calculate_nir_score(source, target_tonic)
	score_other = hs._calculate_nir_score(source, target_other)

	# Tonic return usually gets a small boost for closure
	assert score_tonic > score_other


def test_calculate_nir_score_proximity () -> None:

	"""
	Test Rule D: Proximity
	Small intervals (≤ 3 semitones) get a general boost.
	"""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", nir_strength=1.0)

	# History: C (0) -> E (4). Interval = 4 (neutral zone).
	c = subsequence.chords.Chord(root_pc=0, quality="major")
	e = subsequence.chords.Chord(root_pc=4, quality="minor")

	hs.history = [c]
	source = e

	# Target 1: F (5). E->F is +1 semitone (small, proximate).
	target_close = subsequence.chords.Chord(root_pc=5, quality="major")

	# Target 2: Bb (10). E->Bb is +6 semitones (large, not proximate).
	target_far = subsequence.chords.Chord(root_pc=10, quality="major")

	score_close = hs._calculate_nir_score(source, target_close)
	score_far = hs._calculate_nir_score(source, target_far)

	assert score_close > 1.0
	assert score_close > score_far


def test_nir_strength_zero_disables () -> None:

	"""With nir_strength=0.0, all NIR scores should return 1.0 (neutral)."""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", nir_strength=0.0)

	c = subsequence.chords.Chord(root_pc=0, quality="major")
	d = subsequence.chords.Chord(root_pc=2, quality="minor")
	e = subsequence.chords.Chord(root_pc=4, quality="minor")

	hs.history = [c]

	# C -> D is a small step (+2), D -> E continues (+2).
	# At full strength this would get boosted. At 0.0 it should be neutral.
	score = hs._calculate_nir_score(d, e)
	assert score == 1.0


def test_nir_strength_scales_boost () -> None:

	"""With nir_strength=0.5, boosts should be halved compared to nir_strength=1.0."""

	c = subsequence.chords.Chord(root_pc=0, quality="major")
	d = subsequence.chords.Chord(root_pc=2, quality="minor")
	e = subsequence.chords.Chord(root_pc=4, quality="minor")

	hs_full = subsequence.harmonic_state.HarmonicState(key_name="C", nir_strength=1.0)
	hs_full.history = [c]
	score_full = hs_full._calculate_nir_score(d, e)

	hs_half = subsequence.harmonic_state.HarmonicState(key_name="C", nir_strength=0.5)
	hs_half.history = [c]
	score_half = hs_half._calculate_nir_score(d, e)

	# Both should be boosted above 1.0
	assert score_full > 1.0
	assert score_half > 1.0

	# Half-strength boost should be half the full-strength boost
	boost_full = score_full - 1.0
	boost_half = score_half - 1.0
	assert abs(boost_half - boost_full * 0.5) < 0.001


# --- Root Diversity ---


def test_root_diversity_reduces_same_root_frequency () -> None:

	"""The suspended graph at gravity=0.0 should no longer get stuck on one root."""

	rng = random.Random(42)

	hs = subsequence.harmonic_state.HarmonicState(
		key_name = "C",
		graph_style = "suspended",
		key_gravity_blend = 0.0,
		nir_strength = 0.5,
		rng = rng
	)

	roots: typing.List[int] = []

	for _ in range(500):
		chord = hs.step()
		roots.append(chord.root_pc)

	counts = collections.Counter(roots)
	top_pct = counts.most_common(1)[0][1] / len(roots)

	# Was 0.63 before the fix; should now stay below 0.50.
	assert top_pct < 0.50


def test_root_diversity_does_not_suppress_entirely () -> None:

	"""Even with 4 same-root chords in history, step() should still return a chord."""

	rng = random.Random(99)

	hs = subsequence.harmonic_state.HarmonicState(
		key_name = "C",
		graph_style = "suspended",
		key_gravity_blend = 0.0,
		nir_strength = 0.5,
		rng = rng
	)

	# Fill history with 4 C-root chords.
	c_sus2 = subsequence.chords.Chord(root_pc=0, quality="sus2")
	c_sus4 = subsequence.chords.Chord(root_pc=0, quality="sus4")
	hs.history = [c_sus2, c_sus4, c_sus2, c_sus4]
	hs.current_chord = c_sus2

	# Should still produce a valid chord (modifier is 0.4^4 ≈ 0.026, not 0).
	result = hs.step()

	assert isinstance(result, subsequence.chords.Chord)


def test_root_diversity_counts_root_not_quality () -> None:

	"""History with Csus2 and Csus4 should both count toward the C-root penalty."""

	rng = random.Random(42)

	hs = subsequence.harmonic_state.HarmonicState(
		key_name = "C",
		graph_style = "suspended",
		key_gravity_blend = 1.0,
		nir_strength = 0.0,
		rng = rng
	)

	# History: two different qualities on root C.
	c_sus2 = subsequence.chords.Chord(root_pc=0, quality="sus2")
	c_sus4 = subsequence.chords.Chord(root_pc=0, quality="sus4")
	hs.history = [c_sus2, c_sus4]
	hs.current_chord = c_sus4

	# Run many steps from this state and count C-root results.
	c_root_count = 0
	trials = 200

	for _ in range(trials):
		# Reset to the same state each trial.
		hs.history = [c_sus2, c_sus4]
		hs.current_chord = c_sus4
		result = hs.step()

		if result.root_pc == 0:
			c_root_count += 1

	# With 2 C-root entries in history, the penalty is 0.4² = 0.16×.
	# C-root should appear far less than half the time.
	assert c_root_count / trials < 0.45


def test_root_diversity_disabled_at_one () -> None:

	"""Setting root_diversity=1.0 should disable the penalty entirely."""

	rng_a = random.Random(42)
	rng_b = random.Random(42)

	# With penalty (default 0.5)
	hs_with = subsequence.harmonic_state.HarmonicState(
		key_name = "C",
		graph_style = "suspended",
		key_gravity_blend = 0.0,
		nir_strength = 0.5,
		root_diversity = 0.5,
		rng = rng_a
	)

	# Without penalty (1.0 = disabled)
	hs_without = subsequence.harmonic_state.HarmonicState(
		key_name = "C",
		graph_style = "suspended",
		key_gravity_blend = 0.0,
		nir_strength = 0.5,
		root_diversity = 1.0,
		rng = rng_b
	)

	roots_with: typing.List[int] = []
	roots_without: typing.List[int] = []

	for _ in range(200):
		roots_with.append(hs_with.step().root_pc)
		roots_without.append(hs_without.step().root_pc)

	top_with = collections.Counter(roots_with).most_common(1)[0][1] / 200
	top_without = collections.Counter(roots_without).most_common(1)[0][1] / 200

	# Disabled penalty should produce more concentrated distribution.
	assert top_without > top_with
