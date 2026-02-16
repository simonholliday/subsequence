
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
